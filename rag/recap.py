"""Monthly recap of the saved chats: emailed to Advancement and stored in the database.

    python recap.py                    # last month: store it and email it
    python recap.py --month 2026-10    # a given month
    python recap.py --no-email         # store and print only
    python recap.py --print            # print only: no email, nothing stored

A recap holds:
  - how many conversations and questions there were, and how many were answered;
  - the questions the assistant couldn't answer, most frequent first;
  - the most-asked questions and the most-cited source pages;
  - how many follow-up requests came in, and how many items redaction removed;
  - (email only) every saved message of the month as a CSV attachment, already redacted.

It is stored in the `recaps` table of the same database as the chats (chatlog.py), so with
DATABASE_URL set it is stored on that server. Recaps hold no names or contact details and are kept
after the chats they came from are deleted by CHAT_LOG_RETENTION_DAYS.

The email goes to RECAP_TO (default: NOTIFY_TO, which is Ed) on the NOTIFY_CHANNEL channel
(email, or webhook without the attachment). With NOTIFY_CHANNEL=none nothing is sent.

When RECAP_AUTO=1 (the default), the server makes last month's recap by itself: it checks at
start-up and every 6 hours, and makes it once if the table doesn't have it yet. To use cron or
Windows Task Scheduler instead, set RECAP_AUTO=0 and run `python recap.py` on the 1st of each month.
"""

import argparse
import csv
import io
import json
import logging
import re
import threading
from collections import Counter
from datetime import date, datetime, timezone

import chatlog
import config
import notify

log = logging.getLogger(__name__)

CHECK_EVERY_SECONDS = 6 * 3600
TOP_N = 10


def previous_month(today: date | None = None) -> str:
    today = today or datetime.now(timezone.utc).date()
    year, month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    return f"{year:04d}-{month:02d}"


def month_bounds(month: str) -> tuple[str, str]:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise ValueError(f"Month must look like 2026-10, not {month!r}")
    year, mon = int(month[:4]), int(month[5:])
    nxt = f"{year + 1:04d}-01" if mon == 12 else f"{year:04d}-{mon + 1:02d}"
    return f"{month}-01T00:00:00", f"{nxt}-01T00:00:00"


def _normalize(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower().rstrip("?.! "))


def _follow_up_requests(start: str, end: str) -> int:
    path = config.CONTACT_REQUESTS_FILE
    if not path.exists():
        return 0
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            received = json.loads(line).get("received", "")
        except ValueError:
            continue
        count += start <= received < end
    return count


def build(month: str) -> dict:
    """Everything in one month's recap, from the saved messages."""
    start, end = month_bounds(month)
    rows = chatlog.messages_between(start, end)
    questions = [r for r in rows if r["role"] == "user"]
    answers = [r for r in rows if r["role"] == "assistant"]
    # Each answer row comes straight after its question (same conversation and time).
    pairs = [(q, a) for q, a in zip(rows, rows[1:])
             if q["role"] == "user" and a["role"] == "assistant" and q["conversation"] == a["conversation"]]
    asked = Counter()
    shown = {}
    for q in questions:
        key = _normalize(q["text"])
        asked[key] += 1
        shown.setdefault(key, q["text"].strip())
    unanswered = Counter()
    for q, a in pairs:
        if a["unanswered"]:
            unanswered[_normalize(q["text"])] += 1
    cited = Counter(s for a in answers for s in (a["sources"] or "").split(" | ") if s)
    redacted = Counter()
    for r in rows:
        for kind, n in json.loads(r["redacted"] or "{}").items():
            redacted[kind] += n
    return {
        "month": month,
        "conversations": len({r["conversation"] for r in rows}),
        "questions": len(questions),
        "answered": sum(1 for a in answers if a["answered"]),
        "unanswered": [{"question": shown[k], "times": n} for k, n in unanswered.most_common()],
        "top_questions": [{"question": shown[k], "times": n} for k, n in asked.most_common(TOP_N)],
        "top_sources": [{"url": u, "times": n} for u, n in cited.most_common(TOP_N)],
        "follow_up_requests": _follow_up_requests(start, end),
        "redacted": dict(redacted),
        "rows": rows,
    }


def text(recap: dict) -> tuple[str, str]:
    """Subject and plain-text body."""
    q, a = recap["questions"], recap["answered"]
    share = f" ({a * 100 // q}%)" if q else ""
    subject = f"Giving assistant: recap for {recap['month']}"
    lines = [f"Giving assistant recap for {recap['month']}", "",
             f"Conversations: {recap['conversations']}",
             f"Questions: {q}, answered from approved content: {a}{share}",
             f"Follow-up requests through the form: {recap['follow_up_requests']}"]
    if recap["redacted"]:
        lines.append("Personal data removed before saving: "
                     + ", ".join(f"{n} {k}" for k, n in sorted(recap["redacted"].items())))
    lines += ["", "Questions it could not answer (consider adding these to the content document):"]
    lines += [f"- {u['question']} ({u['times']}x)" for u in recap["unanswered"]] or ["- none"]
    lines += ["", "Most-asked questions:"]
    lines += [f"- {t['question']} ({t['times']}x)" for t in recap["top_questions"]] or ["- none"]
    lines += ["", "Most-cited pages:"]
    lines += [f"- {s['url']} ({s['times']}x)" for s in recap["top_sources"]] or ["- none"]
    lines += ["", "Every message of the month is attached as a CSV, with personal numbers and emails "
                  "removed. No names or IP addresses are saved."]
    return subject, "\n".join(lines)


def messages_csv(rows: list[dict]) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["conversation", "time_utc", "who", "text", "answered", "unanswered", "sources"])
    for r in rows:
        w.writerow([r["conversation"], r["at"], "visitor" if r["role"] == "user" else "assistant",
                    r["text"], "" if r["answered"] is None else r["answered"],
                    "" if r["unanswered"] is None else r["unanswered"], r["sources"] or ""])
    return out.getvalue().encode("utf-8-sig")  # BOM so Excel opens it as UTF-8


def store(recap: dict) -> None:
    summary = {k: v for k, v in recap.items() if k != "rows"}
    s = chatlog.store()
    s.execute("DELETE FROM recaps WHERE month = ?", (recap["month"],))
    s.execute("INSERT INTO recaps (month, created, conversations, questions, answered, summary) "
              "VALUES (?, ?, ?, ?, ?, ?)",
              (recap["month"], chatlog.now(), recap["conversations"], recap["questions"],
               recap["answered"], json.dumps(summary, ensure_ascii=False)))


def stored(month: str) -> dict | None:
    rows = chatlog.store().execute("SELECT summary FROM recaps WHERE month = ?", (month,))
    return json.loads(rows[0][0]) if rows else None


def send(recap: dict) -> str:
    subject, body = text(recap)
    to = config.RECAP_TO or [a for a in config.NOTIFY_TO if a]
    attachment = (f"giving-assistant-chats-{recap['month']}.csv", messages_csv(recap["rows"]))
    summary = {k: v for k, v in recap.items() if k != "rows"}
    return notify._deliver(subject, body, to, {"recap": summary}, attachments=[attachment])


def run(month: str | None = None, email: bool = True, keep: bool = True) -> dict:
    month = month or previous_month()
    chatlog.purge_old()
    recap = build(month)
    if keep:
        store(recap)
    if email:
        channel = send(recap)
        log.info("Recap for %s sent on %s", month, channel)
    return recap


def _auto_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        month = previous_month()
        try:
            if stored(month) is None:
                run(month)
        except Exception:
            log.exception("Monthly recap failed; it will be tried again in 6 hours")
        stop.wait(CHECK_EVERY_SECONDS)


def start_auto() -> threading.Event | None:
    """Called by app.py at start-up when RECAP_AUTO=1 and chats are being saved."""
    if not (config.RECAP_AUTO and config.CHAT_LOG):
        return None
    stop = threading.Event()
    threading.Thread(target=_auto_loop, args=(stop,), daemon=True, name="monthly-recap").start()
    return stop


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--month", help="YYYY-MM (default: last month)")
    p.add_argument("--no-email", action="store_true", help="store and print, but don't send")
    p.add_argument("--print", action="store_true", help="print only: no email, nothing stored")
    args = p.parse_args()
    recap = run(args.month, email=not (args.no_email or args.print), keep=not args.print)
    print(text(recap)[1])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
