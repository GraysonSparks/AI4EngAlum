"""FastAPI backend for the giving chat widget.

    uvicorn app:app --port 8000

Then open http://localhost:8000/ for the test site (static/site/), or POST {"message": "..."} to /chat.
POST /contact stores a follow-up request from the widget's contact form (see leads.py) and notifies
staff on the channel set by NOTIFY_CHANNEL (see notify.py). POST /unanswered emails the giving
questions a finished chat couldn't answer. Each /chat message and answer is saved with personal
numbers and emails removed (see chatlog.py and redact.py; CHAT_LOG=0 turns this off).
"""

import hashlib
import hmac
import json
import os
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

import chatlog
import config
import leads
import notify
import recap
import redact
from rag import MAIN_CONTACT_CARD, Assistant



@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = recap.start_auto()  # last month's recap, made once (RECAP_AUTO, see recap.py)
    yield
    if stop:
        stop.set()


app = FastAPI(title="AI4EngAlum Giving Assistant", lifespan=lifespan)

# The test site is served from this app (same origin), so CORS only matters when chat-widget.js
# is embedded on a page hosted somewhere else. Set CORS_ORIGINS="https://a.example,https://b.example" to allow those.
origins = [o for o in os.environ.get("CORS_ORIGINS", "").split(",") if o]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins,
                       allow_methods=["POST"], allow_headers=["Content-Type"])

assistant = Assistant()
# Emails and phone numbers already in the approved content (staff contacts, the giving office) are
# public, so redaction leaves them in the saved answers.
PUBLIC_CONTACTS = redact.public_values(
    assistant.collection.get(include=["documents"])["documents"]
    + [config.FALLBACK_EMAIL, config.FALLBACK_PHONE, config.GIVING_OFFICE_EMAIL,
       config.GIVING_OFFICE_PHONE])
chatlog.purge_old()

# ---- Spam protection: per-address rate limit, held in memory only ----
_hits: dict[tuple[str, str], deque] = defaultdict(deque)
_hits_lock = threading.Lock()


def client_address(request: Request) -> str:
    if config.TRUST_FORWARDED_FOR and request.headers.get("x-forwarded-for"):
        return request.headers["x-forwarded-for"].split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limited(bucket: str, request: Request) -> bool:
    """True once an address has used up RATE_LIMIT requests to this endpoint in the window. The
    address is only a key in this in-memory table and drops out when its window passes."""
    now, key = time.monotonic(), (bucket, client_address(request))
    with _hits_lock:
        for k in [k for k, q in _hits.items() if q and q[-1] < now - config.RATE_WINDOW_SECONDS]:
            del _hits[k]
        q = _hits[key]
        while q and q[0] < now - config.RATE_WINDOW_SECONDS:
            q.popleft()
        if len(q) >= config.RATE_LIMIT:
            return True
        q.append(now)
        return False


def sign(question: str) -> str:
    return hmac.new(config.UNANSWERED_SECRET, question.encode(), hashlib.sha256).hexdigest()[:32]


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    # Earlier turns of the live conversation, sent by the widget with each request. They are used
    # to answer this one request and then discarded (they were saved when they were new).
    history: list[Turn] = Field(default_factory=list, max_length=20)
    # A random ID the widget makes for each conversation, so saved messages can be grouped. It is
    # not linked to the visitor in any way.
    conversation_id: str | None = Field(default=None, max_length=64)


class StaffContact(BaseModel):
    name: str
    title: str
    email: str | None
    phone: str | None
    topic: str


class Unanswered(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    token: str = Field(min_length=32, max_length=32)


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    fallback: bool
    # Staff the question was routed to; the widget shows them as contact cards.
    contacts: list[StaffContact] = Field(default_factory=list)
    # True when the visitor asked to be contacted; the widget shows its follow-up form.
    offer_contact: bool = False
    # True when the assistant couldn't answer an in-scope question; the widget offers the form.
    offer_followup: bool = False
    # That unanswered question, signed. The widget holds it in memory and posts it to /unanswered
    # when the visitor is done chatting.
    unanswered: Unanswered | None = None


class UnansweredReport(BaseModel):
    questions: list[Unanswered] = Field(min_length=1, max_length=20)


class ContactRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str = Field(default="", max_length=30)
    message: str = Field(default="", max_length=1000)
    # Staff member the visitor was routed to, if they opened the form from a contact card.
    staff: str = Field(default="", max_length=80)
    # The form's consent checkbox. Nothing is stored without it.
    consent: bool
    # Spam checks, never stored: a hidden field people never fill in, and how long the form was open.
    website: str = Field(default="", max_length=200)
    seconds_open: float | None = None


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"  # conversations aren't cached anywhere
    try:
        result = assistant.answer(req.message.strip(),
                                  [t.model_dump() for t in req.history])
    except Exception as e:  # Ollama down, collection missing, etc.
        raise HTTPException(status_code=503, detail=f"Assistant unavailable: {e}")
    chatlog.save_turn(req.conversation_id, req.message.strip(), result, PUBLIC_CONTACTS)
    unanswered = None
    if result.get("report_unanswered"):
        q = result["search_query"][:1000]  # the question with follow-ups like "that" resolved
        unanswered = Unanswered(question=q, token=sign(q))
    return ChatResponse(answer=result["answer"], sources=result["sources"],
                        fallback=result["fallback"], contacts=result.get("contacts", []),
                        offer_contact=result.get("offer_contact", False),
                        offer_followup=result.get("offer_followup", False),
                        unanswered=unanswered)


@app.post("/contact")
def contact(req: ContactRequest, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if not req.consent:
        raise HTTPException(status_code=422, detail="Consent is required to store a request.")
    staff_emails = {p["name"]: p.get("email") for r in assistant.router.routes for p in r["people"]}
    staff_emails[MAIN_CONTACT_CARD["name"]] = MAIN_CONTACT_CARD["email"]
    if req.staff and req.staff not in staff_emails:
        raise HTTPException(status_code=422, detail="Unknown staff member.")
    if rate_limited("contact", request):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
    # A bot gets the same reply as a person, so it can't tell it was caught; nothing is stored.
    if req.website or req.seconds_open is None or req.seconds_open < config.FORM_MIN_SECONDS:
        return {"ok": True}
    request_data = req.model_dump(exclude={"consent", "website", "seconds_open"})
    # The form asks for email and phone, so those fields stay. The free-text message must not carry
    # card, Social Security or account numbers.
    request_data["message"] = redact.redact(request_data["message"],
                                            kinds=("ssn", "card", "number"))[0]
    leads.save_request(request_data, staff_emails)
    return {"ok": True}


@app.post("/unanswered", status_code=204)
async def unanswered(request: Request):
    """Email one finished chat's unanswered giving questions to NOTIFY_TO. The widget sends this
    with navigator.sendBeacon as plain text (so no CORS preflight), hence the manual parsing.
    Only questions carrying a valid signature from /chat are sent, with personal numbers and
    emails removed."""
    try:
        report = UnansweredReport.model_validate(json.loads(await request.body()))
    except ValueError:
        raise HTTPException(status_code=422, detail="Malformed report.")
    if rate_limited("unanswered", request):
        raise HTTPException(status_code=429, detail="Too many requests.")
    questions = list(dict.fromkeys(u.question for u in report.questions
                                   if hmac.compare_digest(u.token, sign(u.question))))
    questions = list(dict.fromkeys(redact.redact(q, PUBLIC_CONTACTS)[0] for q in questions))
    if questions:
        notify.notify_unanswered(questions)
    return Response(status_code=204)


@app.post("/reload-rules")
def reload_rules():
    """Pick up edits to the Response Rules in the content doc without restarting."""
    assistant.reload_rules()
    return {"rules_source": assistant.rules_source}


@app.get("/health")
def health():
    return {"chunks": assistant.collection.count(), "chat_model": config.CHAT_MODEL,
            "embed_model": config.EMBED_MODEL, "rules_source": assistant.rules_source}


# Mounted last so the API routes above take precedence. Serves the test site and chat-widget.js.
app.mount("/", StaticFiles(directory=config.RAG_DIR / "static" / "site", html=True), name="site")
