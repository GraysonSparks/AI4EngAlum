"""Notify Advancement staff when a visitor leaves a follow-up request, and email the
giving questions the assistant couldn't answer once the visitor is done chatting.

leads.save_request() calls notify() after the request is stored; app.py calls notify_unanswered()
when the widget reports a finished chat's unanswered questions, with Social Security, card and
account numbers already removed (redact.py). The delivery channel depends on where the assistant is hosted, which the
Engineering web team decides, so it is chosen by env var:

    NOTIFY_CHANNEL=none     (default) nothing is sent; requests are only stored
    NOTIFY_CHANNEL=email    send an email through SMTP_HOST to NOTIFY_TO
    NOTIFY_CHANNEL=webhook  POST JSON to NOTIFY_WEBHOOK_URL (Teams / Power Automate / Slack flow)

Advancement chose email, sent to Ed Collari (NOTIFY_TO defaults to config.FALLBACK_EMAIL). Set
NOTIFY_ROUTED_STAFF=1 to also email the staff member the visitor asked for.

A failed notification never fails the visitor's request: the request is already stored, and the
error is logged so staff can check the requests file.
"""

import logging
import smtplib
import threading
from email.message import EmailMessage

import httpx

import config

log = logging.getLogger(__name__)


def message_text(request: dict) -> tuple[str, str]:
    """Subject and body for one request. Only the fields the visitor typed are included."""
    name = f"{request['first_name']} {request['last_name']}"
    staff = request.get("staff") or "the Engineering Advancement team"
    subject = f"Giving assistant: follow-up request from {name}"
    lines = [
        f"{name} asked for a follow-up from {staff} through the giving assistant.",
        "",
        f"Email: {request['email']}",
        f"Phone: {request.get('phone') or '(not given)'}",
        f"Received: {request['received']} (UTC)",
        "",
        "Message:",
        request.get("message") or "(none)",
        "",
        "The visitor consented to being contacted. The chat conversation is not attached.",
    ]
    return subject, "\n".join(lines)


def recipients(request: dict, staff_emails: dict[str, str] | None = None) -> list[str]:
    to = [a for a in config.NOTIFY_TO if a]
    if config.NOTIFY_ROUTED_STAFF and request.get("staff") and staff_emails:
        email = staff_emails.get(request["staff"])
        if email and email not in to:
            to.append(email)
    return to


def unanswered_text(questions: list[str]) -> tuple[str, str]:
    """Subject and body for one finished chat's unanswered questions. Nothing else is included."""
    n = len(questions)
    subject = f"Giving assistant: {n} unanswered question{'s' if n != 1 else ''}"
    lines = ["A visitor asked the giving assistant these questions and it had no approved answer:",
             ""]
    lines += [f"- {q}" for q in questions]
    lines += ["", "Only the question text is sent, with Social Security, card and account numbers "
                  "removed. The rest of the conversation is not included."]
    return subject, "\n".join(lines)


def send_email(subject: str, body: str, to: list[str], reply_to: str | None = None,
               attachments: list[tuple[str, bytes]] = ()) -> None:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, config.NOTIFY_FROM, ", ".join(to)
    if reply_to:
        msg["Reply-To"] = reply_to  # staff can reply straight to the visitor
    msg.set_content(body)
    for name, data in attachments:  # the monthly recap's CSV (recap.py)
        msg.add_attachment(data, maintype="text", subtype="csv", filename=name)
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
        if config.SMTP_STARTTLS:
            smtp.starttls()
        if config.SMTP_USER:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
        smtp.send_message(msg)


def send_webhook(subject: str, body: str, extra: dict) -> None:
    # "text" is what Teams/Slack incoming webhooks display; extra is for Power Automate flows.
    r = httpx.post(config.NOTIFY_WEBHOOK_URL, timeout=20,
                   json={"title": subject, "text": body, **extra})
    r.raise_for_status()


def _deliver(subject: str, body: str, to: list[str], extra: dict,
             reply_to: str | None = None, attachments: list[tuple[str, bytes]] = ()) -> str:
    """Send on the configured channel. A webhook gets no attachments."""
    channel = config.NOTIFY_CHANNEL
    if channel == "email":
        if not to:
            raise ValueError("NOTIFY_CHANNEL=email but NOTIFY_TO is empty")
        send_email(subject, body, to, reply_to, attachments)
    elif channel == "webhook":
        send_webhook(subject, body, extra)
    elif channel != "none":
        raise ValueError(f"Unknown NOTIFY_CHANNEL {channel!r}")
    return channel


def deliver(request: dict, staff_emails: dict[str, str] | None = None) -> str:
    """Send one follow-up notification on the configured channel. Returns the channel used."""
    subject, body = message_text(request)
    return _deliver(subject, body, recipients(request, staff_emails), {"request": request},
                    reply_to=request["email"])


def deliver_unanswered(questions: list[str]) -> str:
    subject, body = unanswered_text(questions)
    return _deliver(subject, body, [a for a in config.NOTIFY_TO if a], {"questions": questions})


def _background(send, what: str, wait: bool) -> None:
    """Deliver in the background so the visitor isn't kept waiting on SMTP or a webhook."""
    def run():
        try:
            send()
        except Exception:
            log.exception("%s failed", what)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    if wait:
        t.join()


def notify(request: dict, staff_emails: dict[str, str] | None = None, wait: bool = False) -> None:
    _background(lambda: deliver(request, staff_emails),
                f"Follow-up notification (the request is still stored in {config.CONTACT_REQUESTS_FILE})",
                wait)


def notify_unanswered(questions: list[str], wait: bool = False) -> None:
    _background(lambda: deliver_unanswered(questions), "Unanswered-question email", wait)
