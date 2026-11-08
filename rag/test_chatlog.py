"""Check redaction of personal data and the saved-chat database, without the chat model.

    python test_chatlog.py

Uses a temporary SQLite file; the real rag/data/ is never touched. Needs the search index
(python ingest.py), like test_contact.py, because app.py loads it at import.
"""

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

import config
import redact

KEEP = redact.public_values(["Contact Ed at elc0042@auburn.edu or 334.844.1488."])

# (what is being checked, input, expected output)
REDACT_CASES = [
    ("SSN with dashes", "my ssn is 123-45-6789", "my ssn is [SSN]"),
    ("SSN with spaces", "SSN 123 45 6789 please", "SSN [SSN] please"),
    ("card number in groups", "card 4111 1111 1111 1111 was declined", "card [CARD NUMBER] was declined"),
    ("card number in one run", "4111111111111111", "[CARD NUMBER]"),
    ("phone with dashes", "call me at 334-555-0123", "call me at [PHONE]"),
    ("phone with parentheses", "(334) 555-0123 is my cell", "[PHONE] is my cell"),
    ("phone with +1 and dots", "+1 334.555.0123", "[PHONE]"),
    ("email with digits", "write to jdoe1985@gmail.com", "write to [EMAIL]"),
    ("bank account number", "account 000123456789 routing 062000019", "account [NUMBER] routing [NUMBER]"),
    ("gift amount stays", "I want to give $5,000 or $1000000", "I want to give $5,000 or $1000000"),
    ("class year and course stay", "Class of 1998, took ELEC 3810", "Class of 1998, took ELEC 3810"),
    ("percent and date stay", "5% by 12/31/2026", "5% by 12/31/2026"),
    ("public contact stays", "Ed: elc0042@auburn.edu, 334.844.1488", "Ed: elc0042@auburn.edu, 334.844.1488"),
    ("public phone in another format stays", "(334) 844-1488", "(334) 844-1488"),
]


def check_redaction() -> tuple[int, int]:
    passed = 0
    for name, text, expected in REDACT_CASES:
        got = redact.redact(text, KEEP)[0]
        ok = got == expected
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  redact: {name}" + ("" if ok else f"\n      got: {got!r}"))
    form = redact.redact("call 334-555-0123, SSN 123-45-6789", kinds=("ssn", "card", "number"))[0]
    ok = form == "call 334-555-0123, SSN [SSN]"
    print(f"{'PASS' if ok else 'FAIL'}  redact: form message keeps the phone, drops the SSN")
    return passed + ok, len(REDACT_CASES) + 1


def check_saving() -> tuple[int, int]:
    results = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"\n      {detail}" if not ok and detail else ""))

    with tempfile.TemporaryDirectory() as tmp:
        config.CHAT_LOG_DB = Path(tmp) / "chats.sqlite3"
        config.CONTACT_REQUESTS_FILE = Path(tmp) / "contact_requests.jsonl"
        config.DATABASE_URL = ""
        config.RATE_LIMIT = 100
        import app as app_module  # imported after the overrides
        import chatlog

        def fake_answer(question, history):
            return {"answer": f"Please contact {config.FALLBACK_CONTACT}. You wrote: {question}",
                    "sources": ["https://eng.auburn.edu/giving/"], "fallback": True,
                    "report_unanswered": True, "search_query": question}

        app_module.assistant.answer = fake_answer
        client = TestClient(app_module.app)
        conv = "3f2a8c1e-1111-4222-8333-944455556666"
        r = client.post("/chat", json={"message": "My SSN is 123-45-6789, call 334-555-0123",
                                       "conversation_id": conv})
        check("/chat answers", r.status_code == 200, r.text)
        client.post("/chat", json={"message": "second question", "conversation_id": conv})
        client.post("/chat", json={"message": "no id sent"})
        client.post("/chat", json={"message": "bad id", "conversation_id": "x' OR 1=1 --"})

        rows = chatlog.messages_between("0000", "9999")
        check("two rows per message (visitor and assistant)", len(rows) == 8, f"{len(rows)} rows")
        first_q, first_a = rows[0], rows[1]
        check("visitor text saved redacted", first_q["text"] == "My SSN is [SSN], call [PHONE]",
              first_q["text"])
        check("redaction counts saved", json.loads(first_q["redacted"]) == {"ssn": 1, "phone": 1},
              str(first_q["redacted"]))
        check("public contact kept in the answer", config.FALLBACK_EMAIL in first_a["text"]
              and config.FALLBACK_PHONE in first_a["text"], first_a["text"])
        check("echoed personal data removed from the answer",
              "123-45-6789" not in first_a["text"] and "[SSN]" in first_a["text"], first_a["text"])
        check("answer flags saved", first_a["answered"] == 0 and first_a["unanswered"] == 1)
        check("messages grouped by the widget's conversation ID",
              [r["conversation"] for r in rows[:4]] == [conv] * 4)
        check("missing or malformed IDs get their own conversation",
              rows[4]["conversation"].startswith("single-")
              and rows[6]["conversation"].startswith("single-")
              and rows[4]["conversation"] != rows[6]["conversation"])
        all_text = json.dumps(rows)
        check("no raw SSN or phone anywhere in the database",
              "123-45-6789" not in all_text and "334-555-0123" not in all_text)

        # Retention: an old row is deleted, a new one stays.
        chatlog.store().execute("INSERT INTO messages (conversation, at, role, text) VALUES (?, ?, ?, ?)",
                                ("old", "2000-01-01T00:00:00+00:00", "user", "old"))
        deleted = chatlog.purge_old()
        check("old messages deleted after CHAT_LOG_RETENTION_DAYS", deleted == 1, f"deleted {deleted}")

        # Follow-up form: phone and email stay, an SSN in the message does not.
        r = client.post("/contact", json={
            "first_name": "Test", "last_name": "Visitor", "email": "t.v@example.com",
            "phone": "334-555-0123", "message": "My SSN is 123-45-6789", "staff": "",
            "consent": True, "website": "", "seconds_open": 10})
        saved = json.loads(config.CONTACT_REQUESTS_FILE.read_text().splitlines()[-1])
        check("form keeps phone and email, removes an SSN from the message",
              saved["phone"] == "334-555-0123" and saved["email"] == "t.v@example.com"
              and saved["message"] == "My SSN is [SSN]", json.dumps(saved))

        # CHAT_LOG=0 saves nothing.
        config.CHAT_LOG = False
        client.post("/chat", json={"message": "not saved", "conversation_id": conv})
        config.CHAT_LOG = True
        check("CHAT_LOG=0 saves nothing", len(chatlog.messages_between("0000", "9999")) == 8)
    return sum(results), len(results)


def main():
    p1, n1 = check_redaction()
    p2, n2 = check_saving()
    print(f"\n{p1 + p2}/{n1 + n2} passed")
    raise SystemExit(0 if p1 + p2 == n1 + n2 else 1)


if __name__ == "__main__":
    main()
