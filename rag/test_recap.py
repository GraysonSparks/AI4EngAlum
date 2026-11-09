"""Check the monthly recap: what it counts, that it is stored, and the email with its CSV.

    python test_recap.py

Uses a temporary SQLite file and a fake mail server; nothing is sent and rag/data/ is not touched.
"""

import csv
import io
import json
import tempfile
from datetime import date
from pathlib import Path

import chatlog
import config
import notify
import recap
import test_notify  # its FakeSMTP records messages instead of sending them

DIRECTORY = "https://eng.auburn.edu/admin/development/"
WAYS = "https://eng.auburn.edu/giving/ways-to-give/"


def turn(conv, at, question, answered, unanswered=False, sources=(), redacted=None):
    s = chatlog.store()
    s.execute("INSERT INTO messages (conversation, at, role, text, redacted) VALUES (?, ?, ?, ?, ?)",
              (conv, at, "user", question, json.dumps(redacted) if redacted else None))
    s.execute("INSERT INTO messages (conversation, at, role, text, answered, unanswered, sources) "
              "VALUES (?, ?, ?, ?, ?, ?, ?)",
              (conv, at, "assistant", "answer", int(answered), int(unanswered), " | ".join(sources)))


def main():
    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"\n      {detail}" if not ok and detail else ""))

    with tempfile.TemporaryDirectory() as tmp:
        config.CHAT_LOG, config.DATABASE_URL = True, ""
        config.CHAT_LOG_DB = Path(tmp) / "chats.sqlite3"
        config.CHAT_LOG_RETENTION_DAYS = 0
        config.CONTACT_REQUESTS_FILE = Path(tmp) / "contact_requests.jsonl"
        config.CONTACT_REQUESTS_FILE.write_text(
            json.dumps({"received": "2026-10-20T15:00:00+00:00"}) + "\n"
            + json.dumps({"received": "2026-11-02T15:00:00+00:00"}) + "\n")

        turn("a", "2026-10-03T14:00:00+00:00", "How do I make a gift?", True, sources=[WAYS])
        turn("a", "2026-10-03T14:01:00+00:00", "Can I give stock?", False, unanswered=True)
        turn("b", "2026-10-15T09:00:00+00:00", "how do I make a gift", True, sources=[WAYS, DIRECTORY])
        turn("c", "2026-10-31T23:59:59+00:00", "Can I give stock?", False, unanswered=True,
             redacted={"phone": 1})
        turn("d", "2026-10-31T23:00:00+00:00", "What's the weather?", False)  # off-topic: not unanswered
        turn("d", "2026-10-31T23:30:00+00:00", "Please call me at 334-555-0123", True)
        turn("d", "2026-10-31T23:31:00+00:00", f"Is Ed's number {config.FALLBACK_PHONE}?", True)  # public: not listed
        turn("e", "2026-11-01T00:00:00+00:00", "November question", True)   # next month
        turn("f", "2026-09-30T23:59:59+00:00", "September question", True)  # previous month

        r = recap.build("2026-10")
        check("counts only the month's conversations", r["conversations"] == 4, str(r["conversations"]))
        check("counts questions and answered", (r["questions"], r["answered"]) == (7, 4),
              f"{r['questions']}, {r['answered']}")
        check("unanswered questions grouped, most frequent first",
              r["unanswered"] == [{"question": "Can I give stock?", "times": 2}], str(r["unanswered"]))
        check("off-topic declines are not listed as unanswered",
              all("weather" not in u["question"] for u in r["unanswered"]))
        check("same question in different case/punctuation counted together",
              r["top_questions"][0]["times"] == 2 and "gift" in r["top_questions"][0]["question"].lower(),
              str(r["top_questions"]))
        check("most-cited pages", r["top_sources"][0] == {"url": WAYS, "times": 2}, str(r["top_sources"]))
        check("follow-up requests in the month", r["follow_up_requests"] == 1)
        check("redaction totals", r["redacted"] == {"phone": 1}, str(r["redacted"]))
        check("visitors who typed their own contact details are listed",
              [c["message"] for c in r["contact_left"]] == ["Please call me at 334-555-0123"],
              str(r["contact_left"]))

        subject, body = recap.text(r)
        check("subject names the month", subject == "Giving assistant: recap for 2026-10", subject)
        check("body lists the unanswered question", "- Can I give stock? (2x)" in body, body)
        check("body lists the contact details left in the chat",
              "Please call me at 334-555-0123" in body, body)

        recap.store(r)
        recap.store(r)  # running twice replaces the month's row
        rows = chatlog.store().execute("SELECT month, questions FROM recaps")
        check("stored once in the recaps table", rows == [("2026-10", 7)], str(rows))
        check("stored recap can be read back", recap.stored("2026-10")["answered"] == 4)
        check("a missing month reads back as None", recap.stored("2026-09") is None)

        # Email with the CSV attachment, through the fake SMTP server.
        test_notify.setup("email", to=["ed@example.edu"])
        notify.smtplib.SMTP = test_notify.FakeSMTP
        config.RECAP_TO = []
        recap.send(r)
        sent = test_notify.sent
        check("one email sent", len(sent) == 1 and sent[0][0] == "email")
        msg = sent[0][1]
        check("sent to NOTIFY_TO when RECAP_TO is empty", msg["To"] == "ed@example.edu", msg["To"])
        parts = list(msg.iter_attachments())
        check("CSV attached", len(parts) == 1
              and parts[0].get_filename() == "giving-assistant-chats-2026-10.csv")
        table = list(csv.reader(io.StringIO(parts[0].get_content().lstrip("﻿"))))
        check("CSV has a header and the month's 14 messages", len(table) == 15, str(len(table)))

        test_notify.setup("none")
        check("NOTIFY_CHANNEL=none sends nothing", recap.send(r) == "none" and not test_notify.sent)

        check("previous month in January is December",
              recap.previous_month(date(2027, 1, 5)) == "2026-12")
        try:
            recap.month_bounds("2026-13")
            check("a bad month is refused", False)
        except ValueError:
            check("a bad month is refused", True)

    print(f"\n{sum(results)}/{len(results)} passed")
    raise SystemExit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
