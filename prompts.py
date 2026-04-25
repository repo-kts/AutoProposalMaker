SYSTEM_PROMPT = (
    "You are a senior proposal writer at Kalope Tech, a professional technology "
    "services company. You write clear, confident, specific proposals that win "
    "business. You always return valid JSON exactly matching the requested schema."
)


def build_module_prompt(project_title: str, industry: str, project_description: str,
                        module_name: str, user_prompt: str, next_code: str,
                        existing_modules) -> str:
    existing = "\n".join(
        f"- {m.get('module_code', '')} {m.get('module_name', '')}"
        for m in (existing_modules or [])
    ) or "(none)"
    return f"""Add a new scope module to an existing project proposal.

PROJECT CONTEXT
- Project: {project_title}
- Client industry: {industry}
- Project description: {project_description}

EXISTING MODULES (do not duplicate their screens)
{existing}

NEW MODULE TO GENERATE
- Module name: {module_name}
- Module code: {next_code}
- User direction: {user_prompt or '(generate sensible, specific screens for this module)'}

Return ONLY a valid JSON object:
{{
  "module_code": "{next_code}",
  "module_name": "{module_name}",
  "screens": [
    {{"code": "{next_code}.1", "name": "Short screen / feature name", "description": "One-line description"}}
  ]
}}

Strict requirements:
- Generate 3-8 screens consistent with the project and industry.
- Screen codes increment from 1 following "{next_code}" (e.g. {next_code}.1, {next_code}.2).
- Do not duplicate screens already present in existing modules.
- Be specific — no generic filler.
- Return ONLY the JSON object. No surrounding prose, no code fences."""


def build_proposal_prompt(client_name: str, industry: str, project_description: str,
                          days: int, budget: str, currency: str) -> str:
    return f"""Generate a project proposal using the inputs below.

INPUTS
- Client: {client_name}
- Client industry: {industry}
- Project description (from client): {project_description}
- Tentative duration: {days} days
- Client-approved budget: {currency} {budget}

Return ONLY a valid JSON object with this exact structure:

{{
  "project_title": "Full project title with version, e.g. 'Learning Management System (LMS) - Version 1.0'",
  "project_title_short": "Short label used inside the document, e.g. 'LMS' or 'Platform'",
  "introduction": "2-3 short paragraphs. Paragraph 1: appreciate the opportunity and state what this document covers. Paragraph 2: describe what the platform/solution will do for the client at a high level. Separate paragraphs with \\n\\n.",

  "executive_summary": "One confident paragraph summarising what Kalope Tech will deliver and the measurable business outcome for {client_name}.",

  "scope_modules": [
    {{
      "module_code": "2.1",
      "module_name": "e.g. Authentication Module, Customer Portal, Marketing Engine",
      "screens": [
        {{"code": "2.1.1", "name": "Short screen / feature name", "description": "One-line description"}}
      ]
    }}
  ],
  "additional_features": ["nice-to-have features as bullets (count determined by budget rubric below)"],

  "technology_stack": [
    {{"layer": "Frontend | Backend | Database | Cache | Authentication | File Storage | Payments | Hosting | CI/CD | etc.",
      "technology": "Specific tools, comma-separated"}}
  ],

  "timeline": [
    {{"phase": "Phase 1 - UI/UX Design",
      "description": "One-line description of the phase",
      "duration_days": 10}}
  ],
  "total_duration_label": "e.g. '~{days} Days' or '{days} Days'",
  "total_duration_note": "e.g. 'post-launch maintenance & support to be agreed separately'",

  "project_cost": {{
    "amount_display": "The budget formatted in the local convention for {currency}. For INR use Indian numbering with the ₹ symbol, e.g. ₹8,90,000. For USD use the $ symbol with thousand separators, e.g. $12,000.",
    "amount_words": "The amount written in words, e.g. 'Eight Lakhs Ninety Thousand INR' or 'Twelve Thousand US Dollars'",
    "description": "1-2 sentences clarifying what is covered and what is not (e.g. 'This price covers complete design, development, testing, and deployment. Post-launch maintenance will be scoped separately.')"
  }},

  "recurring_costs": {{
    "note": "One sentence clarifying these are client-borne infrastructure costs.",
    "items": [
      {{"service": "e.g. Hosting (Vercel + Railway / AWS)", "monthly_cost": "e.g. $50 or $100+"}}
    ],
    "estimated_total": "e.g. '~$250 / month'"
  }},

  "deliverables": ["concrete final artefacts handed over at project close (count determined by budget rubric below)"],

  "terms_and_conditions": [
    {{"label": "Scope Changes", "text": "Any additions or modifications to the agreed scope will be treated as change requests and quoted separately."}},
    {{"label": "Intellectual Property", "text": "Full ownership of the codebase and all assets is transferred to the client upon receipt of final payment."}},
    {{"label": "Confidentiality", "text": "..."}},
    {{"label": "Timeline", "text": "..."}},
    {{"label": "Warranty", "text": "..."}}
  ],

  "closing_message": "A short warm closing line, e.g. 'Thank you for your trust. We look forward to building something great together.'"
}}

SCOPE COMPLEXITY — SCALE WITH BUDGET
The breadth AND depth of this proposal MUST match the budget of {currency} {budget}. Judge
the budget relative to the described project and industry — for example, ₹300,000 is modest
for a full LMS but generous for a simple landing page; $5,000 is small for enterprise software
but healthy for a marketing site. Use the rubric below, stepping between tiers as appropriate:

- SMALL budget (leanest acceptable scope):
    * 2-3 scope_modules, 3-5 screens each
    * 3 timeline phases
    * 5-6 technology_stack layers (no premium / managed tools)
    * 3-4 recurring_costs items
    * 4-6 deliverables
    * 2-3 additional_features
    * 5 terms_and_conditions
    * Short, concise one-line descriptions throughout.

- MEDIUM budget (standard delivery):
    * 4-5 scope_modules, 5-8 screens each
    * 4 timeline phases
    * 7-9 technology_stack layers
    * 4-5 recurring_costs items
    * 6-8 deliverables
    * 3-5 additional_features
    * 6-7 terms_and_conditions
    * Descriptions are specific and technical where relevant.

- LARGE budget (premium / enterprise):
    * 6-8 scope_modules, 6-12 screens each
    * 5-7 timeline phases
    * 9-12 technology_stack layers, including managed / premium options (e.g. Mux, Clerk,
      Datadog, Snowflake, dedicated cache tier)
    * 5-7 recurring_costs items
    * 8-12 deliverables
    * 5-7 additional_features
    * 8-10 terms_and_conditions
    * Descriptions are longer (up to two sentences) with concrete technical depth and
      measurable outcomes where appropriate.

Scope should feel proportionate — a small-budget proposal must not read as a cut-down
enterprise proposal; a large-budget proposal must not read as a small site with extras
tacked on.

Strict requirements:
- Every timeline phase's duration_days is an integer. Phases must sum to approximately {days} days (within +/- 10 percent).
- Module codes are "2.1", "2.2", ... Screen codes follow the module code ("2.1.1", "2.1.2", ...).
- For software/tech projects the modules group user roles or functional areas (Auth, User-facing, Admin, API, etc.). For non-tech projects group by workstream (Research, Design, Execution, Reporting, etc.) and use "Deliverable" in place of "Screen".
- Technology stack items appropriate for a {industry} client. Recurring-cost estimates should be in USD regardless of project currency (infra is billed in USD by convention), unless the project currency is USD in which case keep USD.
- Be specific to {industry} and the project description. No generic filler, no emojis.
- Return ONLY the JSON object. No surrounding prose, no code fences."""
