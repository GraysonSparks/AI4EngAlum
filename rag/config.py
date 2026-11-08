"""Shared settings for the AI4EngAlum RAG prototype. Override any of these with env vars."""

import os
from pathlib import Path

RAG_DIR = Path(__file__).resolve().parent
PROJECT_DIR = RAG_DIR.parent  # 3_Code/: rag/, content/, scraped_pages/, scraper/

# The hand-curated Q&A doc (content/). Both the .docx and .odt copies exist; content.py uses
# whichever was saved most recently unless CONTENT_DOC points at a specific file.
CONTENT_DOC = os.environ.get("CONTENT_DOC")
CONTENT_DOC_CANDIDATES = [
    PROJECT_DIR / "content" / "AI4EngAlum Giving Content for RAG.odt",
    PROJECT_DIR / "content" / "AI4EngAlum Giving Content for RAG.docx",
]
SCRAPED_DIR = Path(os.environ.get("SCRAPED_DIR", PROJECT_DIR / "scraped_pages"))

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "qwen3.5:9b")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")

CHROMA_DIR = Path(os.environ.get("CHROMA_DIR", RAG_DIR / "chroma_db"))
COLLECTION = "giving"

TOP_K = int(os.environ.get("TOP_K", "4"))
# How many earlier messages (user + assistant) from the live conversation are used per request.
# The client sends them with each request; only the newest message and its answer are saved (below).
HISTORY_MESSAGES = int(os.environ.get("HISTORY_MESSAGES", "6"))
# Cosine distance (0 = identical). Chunks farther than this are treated as "not relevant";
# if nothing is closer, the bot returns the fallback without calling the chat model.
MAX_DISTANCE = float(os.environ.get("MAX_DISTANCE", "0.5"))

# Follow-up requests left through the widget's contact form, one JSON object per line.
CONTACT_REQUESTS_FILE = Path(os.environ.get("CONTACT_REQUESTS_FILE",
                                            RAG_DIR / "data" / "contact_requests.jsonl"))

# The sponsor's choice of main point of contact. Every dead end gives their details first, then
# offers to have them reach out (the follow-up form) as the second option. They are also the
# default recipient of every notification. `python routing.py` warns if
# these no longer match that person's entry in the scraped staff directory.
FALLBACK_NAME = os.environ.get("FALLBACK_NAME", "Ed Collari")
FALLBACK_TITLE = os.environ.get("FALLBACK_TITLE", "Executive Director of Development")
FALLBACK_EMAIL = os.environ.get("FALLBACK_EMAIL", "elc0042@auburn.edu")
FALLBACK_PHONE = os.environ.get("FALLBACK_PHONE", "334.844.1488")
FALLBACK_CONTACT = f"{FALLBACK_NAME}, {FALLBACK_TITLE}, at {FALLBACK_EMAIL} or {FALLBACK_PHONE}"
# Auburn's central giving office (give.auburn.edu: "For additional giving options or if you have
# questions..."), named after the main contact when a visitor asks who to contact in general.
GIVING_OFFICE_EMAIL = os.environ.get("GIVING_OFFICE_EMAIL", "augiving@auburn.edu")
GIVING_OFFICE_PHONE = os.environ.get("GIVING_OFFICE_PHONE", "334-844-1427")
# Second option, after the contact details: the widget shows the card's button right below.
FALLBACK_INVITE = (f"If you'd rather have {FALLBACK_NAME.split()[0]} reach out to you, use the "
                   "button below to leave your details.")
FALLBACK_REPLY = (
    "I don't have approved information to answer that. For help, please contact "
    f"{FALLBACK_CONTACT}. {FALLBACK_INVITE}"
)

# Saved chats (see chatlog.py). Each message and answer is saved with personal numbers and emails
# removed (redact.py). CHAT_LOG=0 turns saving off. DATABASE_URL=postgresql://... saves to a
# PostgreSQL server instead of the local SQLite file.
CHAT_LOG = os.environ.get("CHAT_LOG", "1") == "1"
CHAT_LOG_DB = Path(os.environ.get("CHAT_LOG_DB", RAG_DIR / "data" / "chats.sqlite3"))
DATABASE_URL = os.environ.get("DATABASE_URL", "")
CHAT_LOG_RETENTION_DAYS = int(os.environ.get("CHAT_LOG_RETENTION_DAYS", "400"))

# Staff notifications (see notify.py): none | email | webhook. Advancement chose email; it stays
# "none" until the assistant is hosted so local testing never emails anyone.
NOTIFY_CHANNEL = os.environ.get("NOTIFY_CHANNEL", "none").lower()
NOTIFY_TO = [a.strip() for a in os.environ.get("NOTIFY_TO", FALLBACK_EMAIL).split(",") if a.strip()]
NOTIFY_FROM = os.environ.get("NOTIFY_FROM", "giving-assistant@eng.auburn.edu")
NOTIFY_ROUTED_STAFF = os.environ.get("NOTIFY_ROUTED_STAFF", "0") == "1"
NOTIFY_WEBHOOK_URL = os.environ.get("NOTIFY_WEBHOOK_URL", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "localhost")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "25"))
SMTP_STARTTLS = os.environ.get("SMTP_STARTTLS", "0") == "1"
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")

# Spam protection for the follow-up form and the unanswered-question report (see app.py).
# Counts are kept in memory per client address for the window and never written anywhere.
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", "5"))
RATE_WINDOW_SECONDS = int(os.environ.get("RATE_WINDOW_SECONDS", "600"))
# Behind the web team's proxy every request comes from the proxy's address, so the limit must use
# the visitor's address from X-Forwarded-For instead. Only turn this on behind a proxy that sets it.
TRUST_FORWARDED_FOR = os.environ.get("TRUST_FORWARDED_FOR", "0") == "1"
# A form submitted faster than this after it opened is treated as a bot and quietly dropped.
FORM_MIN_SECONDS = float(os.environ.get("FORM_MIN_SECONDS", "3"))
# Signs the unanswered questions /chat hands the widget, so /unanswered only emails questions the
# assistant really failed on. A new random key per start is fine: a chat that spans a restart just
# loses its pending report.
UNANSWERED_SECRET = os.environ.get("UNANSWERED_SECRET", "").encode() or os.urandom(32)
