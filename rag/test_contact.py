"""Check the follow-up form endpoint, its spam protection, and the unanswered-question
report, without touching the real requests file or sending anything.

    python test_contact.py
"""

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

import config

VALID = {"first_name": " Test ", "last_name": "Visitor", "email": "test.visitor@example.com",
         "phone": "", "message": "Interested in an endowed scholarship.", "staff": "", "consent": True,
         "website": "", "seconds_open": 12.5}

# (what is being checked, changes to the valid request, expected status)
CASES = [
    ("valid request", {}, 200),
    ("routed to a staff member in the directory", {"staff": "Jon Sirico"}, 200),
    ("asked the main contact from a dead-end card", {"staff": config.FALLBACK_NAME}, 200),
    ("no consent", {"consent": False}, 422),
    ("blank first name", {"first_name": "   "}, 422),
    ("malformed email", {"email": "not-an-email"}, 422),
    ("staff member not in the directory", {"staff": "Someone Else"}, 422),
    ("message over 1000 characters", {"message": "x" * 1001}, 422),
    # Spam: bots get the same 200 as a person, but nothing is stored (checked below).
    ("hidden website field filled in", {"website": "http://spam.example"}, 200),
    ("submitted 1 second after the form opened", {"seconds_open": 1}, 200),
    ("posted directly, without the form's timer", {"seconds_open": None}, 200),
]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        config.CONTACT_REQUESTS_FILE = Path(tmp) / "contact_requests.jsonl"
        config.RATE_LIMIT = 100  # the cases below all come from one address
        import app as app_module  # imported after the override so nothing is written to rag/data/
        import notify

        client = TestClient(app_module.app)
        failed = 0
        for label, changes, expected in CASES:
            status = client.post("/contact", json={**VALID, **changes}).status_code
            failed += status != expected
            print(f"{'ok  ' if status == expected else 'FAIL'} {label}: {status} (expected {expected})")

        stored = [json.loads(l) for l in config.CONTACT_REQUESTS_FILE.read_text().splitlines()]
        expected_keys = {"received", "first_name", "last_name", "email", "phone", "message", "staff"}
        checks = [
            ("only the accepted requests were stored (none of the spam)", len(stored) == 3),
            ("stored fields are exactly the form fields plus a timestamp",
             all(set(r) == expected_keys for r in stored)),
            ("whitespace is trimmed", stored[0]["first_name"] == "Test"),
        ]

        app_module._hits.clear()
        config.RATE_LIMIT = 2
        statuses = [client.post("/contact", json=VALID).status_code for _ in range(3)]
        checks.append(("third request from one address in the window gets 429", statuses == [200, 200, 429]))

        sent = []
        notify.notify_unanswered = lambda questions: sent.append(questions)
        app_module._hits.clear()
        config.RATE_LIMIT = 100
        q = "Do you accept gifts of land?"
        good = {"question": q, "token": app_module.sign(q)}
        forged = {"question": "Buy cheap watches", "token": "0" * 32}
        r = client.post("/unanswered", content=json.dumps({"questions": [good, forged, good]}),
                        headers={"Content-Type": "text/plain"})
        checks.append(("unanswered report emails only signed questions, once each",
                       r.status_code == 204 and sent == [[q]]))
        sent.clear()
        client.post("/unanswered", content=json.dumps({"questions": [forged]}))
        checks.append(("a report with only forged questions sends nothing", sent == []))
        r = client.post("/unanswered", content="not json")
        checks.append(("malformed report is rejected", r.status_code == 422))
        for label, ok in checks:
            failed += not ok
            print(f"{'ok  ' if ok else 'FAIL'} {label}")
        print(f"\n{len(CASES) + len(checks) - failed}/{len(CASES) + len(checks)} passed")
        raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
