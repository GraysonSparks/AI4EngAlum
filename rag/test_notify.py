"""Check staff notifications for follow-up requests and the unanswered-question email
without sending anything.

    python test_notify.py

SMTP and the webhook are replaced with fakes that record what would have been sent.
"""

import os

import config
import notify

REQUEST = {"received": "2026-10-18T15:00:00+00:00", "first_name": "Test", "last_name": "Visitor",
           "email": "test.visitor@example.com", "phone": "", "message": "Endowed scholarship.",
           "staff": "Jon Sirico"}
STAFF_EMAILS = {"Jon Sirico": "jon.sirico@example.edu"}

sent = []


class FakeSMTP:
    def __init__(self, host, port, timeout):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        sent.append(("email", msg))


class FakeResponse:
    def raise_for_status(self):
        pass


def fake_post(url, timeout, json):
    sent.append(("webhook", url, json))
    return FakeResponse()


def failing_post(url, timeout, json):
    raise ConnectionError("webhook unreachable")


def setup(channel, to=(), routed=False, webhook=""):
    sent.clear()
    config.NOTIFY_CHANNEL, config.NOTIFY_TO = channel, list(to)
    config.NOTIFY_ROUTED_STAFF, config.NOTIFY_WEBHOOK_URL = routed, webhook


def main():
    checks = [("alerts go to the main contact unless NOTIFY_TO says otherwise",
               config.NOTIFY_TO == [config.FALLBACK_EMAIL] or "NOTIFY_TO" in os.environ)]
    notify.smtplib.SMTP = FakeSMTP
    notify.httpx.post = fake_post

    subject, body = notify.message_text(REQUEST)
    checks.append(("message names the visitor and the staff member",
                   "Test Visitor" in subject and "Jon Sirico" in body))
    checks.append(("message has the visitor's email and the received time",
                   REQUEST["email"] in body and REQUEST["received"] in body))
    checks.append(("blank phone shows as not given", "(not given)" in body))

    setup("none")
    notify.notify(REQUEST, STAFF_EMAILS, wait=True)
    checks.append(("channel none sends nothing", sent == []))

    setup("email", to=["augiving@example.edu"])
    notify.notify(REQUEST, STAFF_EMAILS, wait=True)
    msg = sent[0][1] if sent else {}
    checks.append(("email goes to NOTIFY_TO only by default", msg.get("To") == "augiving@example.edu"))
    checks.append(("reply-to is the visitor", msg.get("Reply-To") == REQUEST["email"]))

    setup("email", to=["augiving@example.edu"], routed=True)
    notify.notify(REQUEST, STAFF_EMAILS, wait=True)
    checks.append(("NOTIFY_ROUTED_STAFF=1 adds the routed staff member",
                   bool(sent) and "jon.sirico@example.edu" in sent[0][1]["To"]))

    setup("email")
    notify.notify(REQUEST, STAFF_EMAILS, wait=True)  # no recipients: logged, not raised
    checks.append(("email with no NOTIFY_TO sends nothing and doesn't raise", sent == []))

    setup("webhook", webhook="https://hooks.example.edu/flow")
    notify.notify(REQUEST, STAFF_EMAILS, wait=True)
    checks.append(("webhook posts title, text and the request",
                   bool(sent) and sent[0][1] == config.NOTIFY_WEBHOOK_URL
                   and set(sent[0][2]) == {"title", "text", "request"}))

    setup("email", to=[config.FALLBACK_EMAIL])
    notify.notify_unanswered(["Can I give cryptocurrency?", "Do you accept gifts of land?"], wait=True)
    msg = sent[0][1] if sent else {}
    body = msg.get_content() if sent else ""
    checks.append(("unanswered questions are emailed to the main contact",
                   msg.get("To") == config.FALLBACK_EMAIL and "Do you accept gifts of land?" in body
                   and "2 unanswered questions" in msg.get("Subject", "")))
    checks.append(("unanswered email has no Reply-To (the visitor is anonymous)",
                   bool(sent) and msg.get("Reply-To") is None))

    notify.httpx.post = failing_post
    setup("webhook", webhook="https://hooks.example.edu/flow")
    try:
        notify.notify(REQUEST, STAFF_EMAILS, wait=True)
        ok = True
    except Exception:
        ok = False
    checks.append(("a failed webhook doesn't raise", ok))

    failed = 0
    for label, ok in checks:
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {label}")
    print(f"\n{len(checks) - failed}/{len(checks)} passed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)  # the failure cases log tracebacks on purpose
    main()
