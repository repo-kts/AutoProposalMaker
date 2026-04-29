import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-only-change-me-in-production-please")

COMPANY_NAME = "Kalope Tech"
COMPANY_EMAIL = "kalopetechservices@gmail.com"
DEFAULT_PREPARED_BY = COMPANY_NAME
VALIDITY_DAYS = 30

INDUSTRIES = [
    "IT & Software",
    "SaaS",
    "E-commerce",
    "Marketing & Advertising",
    "Healthcare",
    "Finance & Banking",
    "Real Estate",
    "Construction",
    "Education",
    "Manufacturing",
    "Hospitality & Travel",
    "Legal Services",
    "Consulting",
    "Media & Entertainment",
    "Logistics",
    "Non-profit",
    "Other",
]

CURRENCIES = ["INR", "USD"]


def current_date() -> str:
    return datetime.now().strftime("%B %d, %Y")
