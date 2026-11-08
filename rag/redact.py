"""Remove personal numbers and email addresses from text before it is saved or emailed.

Visitors are never asked for personal data in the chat, but some will type it anyway ("my card
4111 1111 1111 1111 was declined", "call me at 334-555-0123"). Each match is replaced with a label
that says what was there, so a saved chat still reads naturally and staff can see that a visitor
tried to share contact details:

    [EMAIL]  [PHONE]  [SSN]  [CARD NUMBER]  [NUMBER]

Only these patterns are removed. Short numbers stay, because most numbers in a giving chat are
useful and not personal: gift amounts ($5,000), class years (1998), course numbers, percentages.
[NUMBER] catches any other run of 7 or more digits (bank account, routing and student ID numbers).

Contact details that are already public in the approved content (Ed's phone, augiving@auburn.edu)
are passed in as `keep` and are not removed, so the assistant's own answers stay readable.

What this does not catch: names, street addresses and dates of birth. They have no reliable
pattern, and removing every name would also remove the staff names the assistant gives out.

    python redact.py "my SSN is 123-45-6789, call 334.555.0123"   # try it
"""

import re
import sys

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
SSN = re.compile(r"(?<![\d-])\d{3}[- ]\d{2}[- ]\d{4}(?![\d-])")
# 13 to 19 digits, optionally in groups split by spaces or dashes: card numbers.
CARD = re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])")
PHONE = re.compile(r"(?<![\d$])(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)")
# Any other long digit run (account, routing, ID numbers). Amounts written with "$" or commas are kept.
LONG_NUMBER = re.compile(r"(?<![\d$,.])\d{7,}(?![\d,])")

LABELS = {"email": "[EMAIL]", "ssn": "[SSN]", "card": "[CARD NUMBER]", "phone": "[PHONE]",
          "number": "[NUMBER]"}
ALL_KINDS = tuple(LABELS)


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def public_values(texts: list[str]) -> frozenset[str]:
    """The emails and phone numbers that appear in approved content, normalized for `keep`."""
    found = set()
    for t in texts:
        found.update(m.lower() for m in EMAIL.findall(t))
        found.update(digits(m)[-10:] for m in PHONE.findall(t))
    return frozenset(found)


def redact(text: str, keep: frozenset[str] = frozenset(),
           kinds: tuple[str, ...] = ALL_KINDS) -> tuple[str, dict[str, int]]:
    """Return the text with personal data replaced, and how many of each kind were replaced."""
    counts: dict[str, int] = {}

    def sub(kind: str, pattern: re.Pattern, text: str, is_kept=lambda m: False) -> str:
        if kind not in kinds:
            return text

        def repl(m: re.Match) -> str:
            if is_kept(m.group(0)):
                return m.group(0)
            counts[kind] = counts.get(kind, 0) + 1
            return LABELS[kind]
        return pattern.sub(repl, text)

    # Order matters: an email can hold digits, and a card number holds a phone-length run.
    text = sub("email", EMAIL, text, lambda s: s.lower() in keep)
    text = sub("ssn", SSN, text)
    text = sub("card", CARD, text)
    text = sub("phone", PHONE, text, lambda s: digits(s)[-10:] in keep)
    text = sub("number", LONG_NUMBER, text)
    return text, counts


if __name__ == "__main__":
    print(redact(" ".join(sys.argv[1:]))[0])
