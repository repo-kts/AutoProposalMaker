import json
import os
import re
import shutil
from io import BytesIO

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import OpenAI
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from xhtml2pdf import default as xhtml2pdf_default
from xhtml2pdf import pisa

import config
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


app = FastAPI(title="AutoProposalMaker")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

openai_client = OpenAI(api_key=config.OPENAI_API_KEY)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "company_name": config.COMPANY_NAME,
            "company_email": config.COMPANY_EMAIL,
            "industries": config.INDUSTRIES,
            "currencies": config.CURRENCIES,
        },
    )


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
async def generate_module(request: Request):
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
async def pdf(request: Request):
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
