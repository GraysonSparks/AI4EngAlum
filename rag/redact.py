"""Remove sensitive numbers from text before it is saved or emailed. Phone numbers and email
addresses are kept.

Visitors are never asked for sensitive data in the chat, but some type it anyway ("my card
4111 1111 1111 1111 was declined"). Each match is replaced with a label that says what was there,
so a saved chat still reads naturally:

    [SSN]  [CARD NUMBER]  [ACCOUNT NUMBER]  [ROUTING NUMBER]  [PIN]  [SECURITY CODE]
    [PASSWORD]  [ID NUMBER]  [NUMBER]

Phone numbers and email addresses are KEPT, so a visitor who types "call me at 334-555-0123" can
be contacted (the chat footer tells visitors chats are saved). Set REDACT_CONTACT_DETAILS=1 to
remove them too ([PHONE], [EMAIL]).

How the order works, because the same digits can mean different things:

1. Email addresses are set aside first, so "jdoe1985@gmail.com" never looks like a number.
2. A number right after a word that names it is removed whatever its format: "SSN 123456789",
   "account # 0012-3456-78", "routing: 062000019", "PIN 4321", "CVV 123", "password: hunter2",
   "driver's license 1234567". This catches numbers that would otherwise look like a phone number.
3. Social Security numbers in their usual shape: 123-45-6789, 123 45 6789, 123.45.6789.
4. Card numbers: 13 to 19 digits, run together or in groups of digits split by spaces or dashes
   (4-4-4-4, Amex 4-6-5). A Luhn-valid one is [CARD NUMBER]; another run of that length is [NUMBER].
5. Phone numbers are set aside (kept): (334) 555-0123, 334.555.0123, +1 334 555 0123,
   3345550123, 1-800-555-0199, 555-0123, "ext. 12", and international numbers starting with +.
6. Any other run of 8 or more digits, or digit groups adding up to 9 or more digits, is [NUMBER]:
   account, routing and student ID numbers typed without a word in front.

Short numbers stay, because most numbers in a giving chat are useful and not personal: gift amounts
($5,000, $1000000), class years (1998), course numbers (ELEC 3810), dates (12/31/2026), percentages.

Not caught: numbers written as words ("one two three"), names, street addresses and dates of birth.

    python redact.py "my SSN is 123-45-6789, call 334.555.0123"   # try it
"""

import re
import sys

import config

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# A word that names what follows it, then up to 3 short filler words or symbols, then the value.
_FILLER = r"(?:\s*(?:[:#=]|\bno\.?|\bnumber\b|\bnum\b|\bis\b|\bwas\b|\bmy\b|\bof\b|\bending in\b|\bends in\b)\s*){0,3}\s*"
_DIGITS = r"(\d(?:[\s.-]?\d){2,22})(?!\d)"
CONTEXT = [
    ("ssn", r"\b(?:ssn|ss#|social security(?: number| no\.?| #)?|social)\b"),
    ("routing", r"\b(?:routing|aba|rtn)\b"),
    ("account", r"\b(?:(?:bank|checking|savings)\s+)?(?:account|acct|a/c)\b"),
    ("card", r"\b(?:credit card|debit card|card|visa|mastercard|amex)\b"),
    ("security_code", r"\b(?:cvv2?|cvc2?|cid|security code)\b"),
    ("pin", r"\bpin\b"),
    ("id", r"\b(?:passport|driver'?s? licen[cs]e|license|licence|dl|tax id|tin|ein|itin|student id|au id|banner id)\b"),
]
CONTEXT_RES = [(kind, re.compile(f"(?i)({word}){_FILLER}" + _DIGITS)) for kind, word in CONTEXT]
# The fewest digits that count after each word, so "card 25" or "social 2026" are left alone.
# 4 covers "last four of my social 6789" and "card ending in 1234".
MIN_DIGITS = {"ssn": 4, "routing": 9, "account": 4, "card": 4, "security_code": 3, "pin": 4, "id": 5}
PASSWORD = re.compile(r"(?i)\b(password|passcode|pwd)(\s*(?:is|was|:|=)\s*)(\S+)")

SSN = re.compile(r"(?<![\d.-])\d{3}([-. ])\d{2}\1\d{4}(?![\d-])")
CARD = re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])")
PHONE = re.compile(
    r"(?<![\w$])(?:"
    r"\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}"            # international, +44 20 7946 0958
    r"|(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-]?)\d{3}[\s.-]?\d{4}"   # US/Canada, with or without 1
    r"|\d{3}[\s.-]\d{4}"                                                # 555-0123, no area code
    r")(?:\s*(?:x|ext\.?|extension)\s*\d{1,5})?(?![\d-])", re.I)
LONG_NUMBER = re.compile(r"(?<![\d$,.])\d{8,}(?![\d,])")
# Digits typed in groups ("0012 3456 7890"), 9 or more digits in total.
GROUPED_NUMBER = re.compile(r"(?<![\d$,.])\d{2,6}(?:[ -]\d{2,6}){1,5}(?![\d,])")

LABELS = {"email": "[EMAIL]", "phone": "[PHONE]", "ssn": "[SSN]", "card": "[CARD NUMBER]",
          "account": "[ACCOUNT NUMBER]", "routing": "[ROUTING NUMBER]", "pin": "[PIN]",
          "security_code": "[SECURITY CODE]", "password": "[PASSWORD]", "id": "[ID NUMBER]",
          "number": "[NUMBER]"}
SENSITIVE = ("ssn", "card", "account", "routing", "pin", "security_code", "password", "id", "number")
CONTACT = ("phone", "email")


def default_kinds() -> tuple[str, ...]:
    return SENSITIVE + (CONTACT if config.REDACT_CONTACT_DETAILS else ())


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def luhn(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def public_values(texts: list[str]) -> frozenset[str]:
    """The emails and phone numbers in approved content, normalized for `keep`. Only used when
    REDACT_CONTACT_DETAILS=1: public contacts then stay in the saved answers."""
    found = set()
    for t in texts:
        found.update(m.lower() for m in EMAIL.findall(t))
        found.update(digits(m.group(0))[-10:] for m in PHONE.finditer(t))
    return frozenset(found)


def contact_details(text: str, keep: frozenset[str] = frozenset()) -> list[str]:
    """Phone numbers and emails in a visitor's message that aren't public contacts (for the recap)."""
    found = [m.group(0) for m in EMAIL.finditer(text) if m.group(0).lower() not in keep]
    rest = EMAIL.sub(" ", text)
    for kind, pattern in CONTEXT_RES:  # "account 3345550123" is not a phone number
        rest = pattern.sub(lambda m, k=kind: " " if len(digits(m.group(2))) >= MIN_DIGITS[k]
                           else m.group(0), rest)
    rest = SSN.sub(" ", rest)
    rest = CARD.sub(" ", rest)
    found += [m.group(0).strip() for m in PHONE.finditer(rest)
              if digits(m.group(0))[-10:] not in keep and len(digits(m.group(0))) >= 7]
    return found


def redact(text: str, keep: frozenset[str] = frozenset(),
           kinds: tuple[str, ...] | None = None) -> tuple[str, dict[str, int]]:
    """Return the text with sensitive data replaced, and how many of each kind were replaced.
    kinds: what to remove (default: SENSITIVE, plus phone and email when REDACT_CONTACT_DETAILS=1)."""
    kinds = default_kinds() if kinds is None else kinds
    counts: dict[str, int] = {}
    held: list[str] = []

    def hold(value: str) -> str:
        held.append(value)
        return f"{chr(0xE100 + len(held) - 1)}"  # a placeholder with no digits

    def label(kind: str) -> str:
        counts[kind] = counts.get(kind, 0) + 1
        return LABELS[kind]

    # 1. Emails.
    def email(m):
        if "email" in kinds and m.group(0).lower() not in keep:
            return hold(label("email"))
        return hold(m.group(0))
    text = EMAIL.sub(email, text)

    # 2. Numbers named by the word in front of them, and passwords.
    for kind, pattern in CONTEXT_RES:
        if kind in kinds:
            text = pattern.sub(
                lambda m, k=kind: (m.group(0)[:m.start(2) - m.start(0)] + hold(label(k))
                                   if len(digits(m.group(2))) >= MIN_DIGITS[k] else m.group(0)),
                text)
    if "password" in kinds:
        text = PASSWORD.sub(lambda m: m.group(1) + m.group(2) + hold(label("password")), text)

    # 3-4. SSNs and card numbers in their usual shapes.
    if "ssn" in kinds:
        text = SSN.sub(lambda m: hold(label("ssn")), text)
    if "card" in kinds or "number" in kinds:
        def card(m):
            if "card" in kinds and luhn(digits(m.group(0))):
                return hold(label("card"))
            return hold(label("number")) if "number" in kinds else m.group(0)
        text = CARD.sub(card, text)

    # 5. Phone numbers: kept (or labeled), and set aside so step 6 leaves them alone.
    def phone(m):
        if "phone" in kinds and digits(m.group(0))[-10:] not in keep:
            return hold(label("phone"))
        return hold(m.group(0))
    text = PHONE.sub(phone, text)

    # 6. Any other long number.
    if "number" in kinds:
        text = LONG_NUMBER.sub(lambda m: hold(label("number")), text)
        text = GROUPED_NUMBER.sub(
            lambda m: hold(label("number")) if len(digits(m.group(0))) >= 9 else m.group(0), text)

    text = re.sub("(.)", lambda m: held[ord(m.group(1)) - 0xE100], text)
    return text, counts


if __name__ == "__main__":
    print(redact(" ".join(sys.argv[1:]))[0])
