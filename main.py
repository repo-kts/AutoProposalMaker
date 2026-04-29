import json
import os
import re
import shutil
from contextlib import asynccontextmanager
from io import BytesIO

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import OpenAI
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from xhtml2pdf import default as xhtml2pdf_default
from xhtml2pdf import pisa

import config
from auth import (
    get_session_user,
    hash_password,
    require_user,
    verify_password,
)
from sqlalchemy.exc import IntegrityError
from db import Proposal, User, get_db, init_db
from prompts import SYSTEM_PROMPT, build_module_prompt, build_proposal_prompt


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(BASE_DIR, "static", "fonts")
os.makedirs(FONT_DIR, exist_ok=True)


def _setup_unicode_font():
    """Copy a Unicode TTF locally, register it with reportlab, and wire it
    into xhtml2pdf's font-name map so `font-family: ProposalFont` resolves to it.

    Prefers Segoe UI on Windows (has ₹ / U+20B9). Falls back to Arial / DejaVu.
    """
    target_regular = os.path.join(FONT_DIR, "ProposalFont.ttf")
    target_bold = os.path.join(FONT_DIR, "ProposalFont-Bold.ttf")

    if not os.path.exists(target_regular):
        candidates = [
            ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
            ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
            ("/System/Library/Fonts/Supplemental/Arial.ttf",
             "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ]
        for normal, bold in candidates:
            if os.path.exists(normal):
                try:
                    shutil.copy(normal, target_regular)
                    if bold and os.path.exists(bold):
                        shutil.copy(bold, target_bold)
                    break
                except Exception:
                    continue

    if not os.path.exists(target_regular):
        return "Helvetica"

    try:
        pdfmetrics.registerFont(TTFont("ProposalFont", target_regular))
        if os.path.exists(target_bold):
            pdfmetrics.registerFont(TTFont("ProposalFont-Bold", target_bold))
            pdfmetrics.registerFontFamily(
                "ProposalFont", normal="ProposalFont", bold="ProposalFont-Bold"
            )
        else:
            pdfmetrics.registerFontFamily("ProposalFont", normal="ProposalFont")
        xhtml2pdf_default.DEFAULT_FONT["proposalfont"] = "ProposalFont"
    except Exception:
        return "Helvetica"

    return "ProposalFont"


FONT_FAMILY = _setup_unicode_font()


def _link_callback(uri, rel):
    uri = str(uri)
    if uri.startswith("/static/"):
        return os.path.join(BASE_DIR, uri.lstrip("/").replace("/", os.sep))
    if uri.startswith("static/"):
        return os.path.join(BASE_DIR, uri.replace("/", os.sep))
    return uri


_LEADING_NUM_RE = re.compile(r"^\s*\d+[.)]\s+")


def _strip_leading_number(s):
    if not isinstance(s, str):
        return s
    return _LEADING_NUM_RE.sub("", s)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="AutoProposalMaker", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET, max_age=60 * 60 * 24 * 14)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

openai_client = OpenAI(api_key=config.OPENAI_API_KEY)


def _redirect_to_login() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=302)


def _proposal_summary(p: Proposal) -> dict:
    return {
        "id": p.id,
        "title": p.title,
        "client_name": p.client_name,
        "status": p.status,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


# --- Auth pages ---

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: Session = Depends(get_db)):
    if get_session_user(request, db):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(
        request, "login.html",
        {
            "company_name": config.COMPANY_NAME,
            "company_email": config.COMPANY_EMAIL,
            "error": None,
            "email": "",
        },
    )


@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email_norm = email.strip().lower()
    user = db.query(User).filter(User.email == email_norm).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request, "login.html",
            {
                "company_name": config.COMPANY_NAME,
                "company_email": config.COMPANY_EMAIL,
                "error": "Invalid email or password.",
                "email": email_norm,
            },
            status_code=401,
        )
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=302)


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request, db: Session = Depends(get_db)):
    if get_session_user(request, db):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(
        request, "signup.html",
        {
            "company_name": config.COMPANY_NAME,
            "company_email": config.COMPANY_EMAIL,
            "error": None,
            "email": "",
        },
    )


@app.post("/signup", response_class=HTMLResponse)
async def signup_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    email_norm = email.strip().lower()

    def render_error(msg: str, code: int = 400):
        return templates.TemplateResponse(
            request, "signup.html",
            {
                "company_name": config.COMPANY_NAME,
                "company_email": config.COMPANY_EMAIL,
                "error": msg,
                "email": email_norm,
            },
            status_code=code,
        )

    if "@" not in email_norm or "." not in email_norm.split("@")[-1]:
        return render_error("That doesn't look like a valid email address.")
    if len(password) < 8:
        return render_error("Password must be at least 8 characters.")
    if password != confirm:
        return render_error("Passwords don't match.")

    existing = db.query(User).filter(User.email == email_norm).first()
    if existing:
        return render_error("An account with that email already exists. Try signing in.")

    user = User(email=email_norm, password_hash=hash_password(password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return render_error("An account with that email already exists. Try signing in.")
    db.refresh(user)

    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=302)


# --- App pages (require auth) ---

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    user = get_session_user(request, db)
    if not user:
        return _redirect_to_login()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "company_name": config.COMPANY_NAME,
            "company_email": config.COMPANY_EMAIL,
            "industries": config.INDUSTRIES,
            "currencies": config.CURRENCIES,
            "user": user,
            "preloaded": None,
        },
    )


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, db: Session = Depends(get_db)):
    user = get_session_user(request, db)
    if not user:
        return _redirect_to_login()
    proposals = (
        db.query(Proposal)
        .filter(Proposal.user_id == user.id)
        .order_by(Proposal.updated_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        request, "history.html",
        {
            "company_name": config.COMPANY_NAME,
            "company_email": config.COMPANY_EMAIL,
            "user": user,
            "proposals": proposals,
        },
    )


@app.get("/proposal/{proposal_id}", response_class=HTMLResponse)
async def open_proposal(proposal_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_session_user(request, db)
    if not user:
        return _redirect_to_login()
    p = (
        db.query(Proposal)
        .filter(Proposal.id == proposal_id, Proposal.user_id == user.id)
        .first()
    )
    if not p:
        return RedirectResponse("/history", status_code=302)
    preloaded = {
        "id": p.id,
        "status": p.status,
        "data": p.data,
    }
    return templates.TemplateResponse(
        request, "index.html",
        {
            "company_name": config.COMPANY_NAME,
            "company_email": config.COMPANY_EMAIL,
            "industries": config.INDUSTRIES,
            "currencies": config.CURRENCIES,
            "user": user,
            "preloaded": json.dumps(preloaded),
        },
    )


@app.post("/proposal/{proposal_id}/delete")
async def delete_proposal(proposal_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_session_user(request, db)
    if not user:
        return _redirect_to_login()
    p = (
        db.query(Proposal)
        .filter(Proposal.id == proposal_id, Proposal.user_id == user.id)
        .first()
    )
    if p:
        db.delete(p)
        db.commit()
    return RedirectResponse("/history", status_code=302)


# --- Save / update proposal (JSON API) ---

@app.post("/save")
async def save_proposal(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    body = await request.json()
    proposal_data = body.get("data") or {}
    status_value = (body.get("status") or "draft").lower()
    if status_value not in {"draft", "final"}:
        status_value = "draft"
    proposal_id = body.get("id")

    meta = proposal_data.get("_meta") or {}
    title = (proposal_data.get("project_title") or "(untitled)").strip()[:500]
    client_name = (meta.get("client_name") or "").strip()[:255]

    if proposal_id:
        p = (
            db.query(Proposal)
            .filter(Proposal.id == int(proposal_id), Proposal.user_id == user.id)
            .first()
        )
        if not p:
            raise HTTPException(status_code=404, detail="Proposal not found")
        p.title = title
        p.client_name = client_name
        p.status = status_value
        p.data = proposal_data
    else:
        p = Proposal(
            user_id=user.id,
            title=title,
            client_name=client_name,
            status=status_value,
            data=proposal_data,
        )
        db.add(p)

    db.commit()
    db.refresh(p)
    return _proposal_summary(p)


@app.post("/generate")
async def generate(
    client_name: str = Form(...),
    industry: str = Form(...),
    industry_other: str = Form(""),
    project_description: str = Form(...),
    timeline_days: int = Form(...),
    budget: str = Form(...),
    currency: str = Form(...),
    prepared_by: str = Form(""),
    user: User = Depends(require_user),
):
    final_industry = (
        industry_other.strip()
        if industry == "Other" and industry_other.strip()
        else industry
    )
    final_prepared_by = prepared_by.strip() or config.DEFAULT_PREPARED_BY

    prompt = build_proposal_prompt(
        client_name=client_name,
        industry=final_industry,
        project_description=project_description,
        days=timeline_days,
        budget=budget,
        currency=currency,
    )

    try:
        completion = openai_client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        proposal = json.loads(completion.choices[0].message.content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI generation failed: {e}")

    if isinstance(proposal.get("deliverables"), list):
        proposal["deliverables"] = [_strip_leading_number(x) for x in proposal["deliverables"]]
    if isinstance(proposal.get("additional_features"), list):
        proposal["additional_features"] = [_strip_leading_number(x) for x in proposal["additional_features"]]

    proposal["_meta"] = {
        "client_name": client_name,
        "industry": final_industry,
        "timeline_days": timeline_days,
        "budget": budget,
        "currency": currency,
        "company_name": config.COMPANY_NAME,
        "company_email": config.COMPANY_EMAIL,
        "prepared_by": final_prepared_by,
        "validity_days": config.VALIDITY_DAYS,
        "date": config.current_date(),
    }
    return proposal


@app.post("/generate-module")
async def generate_module(request: Request, user: User = Depends(require_user)):
    data = await request.json()
    module_name = (data.get("module_name") or "").strip()
    if not module_name:
        raise HTTPException(status_code=400, detail="module_name is required")

    prompt = build_module_prompt(
        project_title=data.get("project_title", ""),
        industry=data.get("industry", ""),
        project_description=data.get("project_description", ""),
        module_name=module_name,
        user_prompt=(data.get("user_prompt") or "").strip(),
        next_code=data.get("next_code", "2.X"),
        existing_modules=data.get("existing_modules", []),
    )

    try:
        completion = openai_client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        module = json.loads(completion.choices[0].message.content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI generation failed: {e}")

    return module


@app.post("/pdf")
async def pdf(request: Request, user: User = Depends(require_user)):
    data = await request.json()
    html = templates.get_template("proposal.html").render(
        p=data, meta=data.get("_meta", {}), font_family=FONT_FAMILY
    )

    buf = BytesIO()
    result = pisa.CreatePDF(
        html, dest=buf, encoding="utf-8", link_callback=_link_callback
    )
    if result.err:
        raise HTTPException(status_code=500, detail="PDF generation failed")

    client_slug = (
        str(data.get("_meta", {}).get("client_name", "client"))
        .replace(" ", "_")
        .replace("/", "_")
    )
    filename = f"Proposal_{client_slug}.pdf"

    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
