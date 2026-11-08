"""Turn the curated giving doc and the scraped pages into chunks for Chroma.

Every chunk is a dict: {"id", "text", "title", "sources" (list of URLs), "kind"}.
"text" is what gets embedded; sources are stored as metadata so the bot can cite them.
"""

import csv
import re
from pathlib import Path

import config

CHUNK_HEADING = re.compile(r"^(GIVING-[A-Z0-9-]+-\d+)\s*[—–-]\s*(.+)$")
EXAMPLE_QUESTION = re.compile(r"^(\d+)[.)]\s+(.+\?)$")
# Example answers that describe bot behavior rather than facts; the response rules cover these.
BEHAVIOR_NOTE = re.compile(r"^The chatbot\b", re.I)
URL = re.compile(r"https?://\S+")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"\b\d{3}[.-]\d{3}[.-]\d{4}\b")

# Headings in the curated doc that delimit the sections we read.
RULES_HEADING = "Recommended Response Rules"
CHUNKS_HEADING = "Proposed RAG Chunks"
EXAMPLES_HEADING = "Example Questions and Grounded Answers"
TEST_PROMPTS_HEADING = "Suggested Initial Test Prompts"
SECTION_HEADINGS = {
    "Purpose and Scope",
    RULES_HEADING,
    "Source Inventory",
    CHUNKS_HEADING,
    EXAMPLES_HEADING,
    "Information Still Requiring Sponsor or Technical Confirmation",
    TEST_PROMPTS_HEADING,
}

STAFF_DIRECTORY_FILE = "eng_auburn_edu_admin_development_index_html.txt"
STAFF_DIRECTORY_URL = "https://eng.auburn.edu/admin/development/index.html"
DEPARTMENT_PREFIX = "give_auburn_edu_campaigns_"
DEPARTMENT_BOILERPLATE_START = "At an everything school"


# ---------- curated doc ----------

def current_doc_path() -> Path:
    if config.CONTENT_DOC:
        return Path(config.CONTENT_DOC)
    existing = [p for p in config.CONTENT_DOC_CANDIDATES if p.exists()]
    if not existing:
        raise FileNotFoundError(f"No content doc found in {config.PROJECT_DIR / 'content'}")
    return max(existing, key=lambda p: p.stat().st_mtime)


def _paragraphs_docx(path: Path) -> list[str]:
    import docx
    return [p.text for p in docx.Document(str(path)).paragraphs]


def _paragraphs_odt(path: Path) -> list[str]:
    from odf import teletype
    from odf.opendocument import load

    out = []

    def walk(node):
        for child in node.childNodes:
            if child.nodeType != 1:
                continue
            tag = child.qname[1]
            if tag in ("p", "h"):
                out.append(teletype.extractText(child))
            elif tag != "table":  # the Source Inventory table isn't needed
                walk(child)

    walk(load(str(path)).text)
    return out


def read_doc_sections(path: Path | None = None) -> dict:
    """Return {"rules", "chunks", "examples", "skipped_examples", "test_prompts", "path"}."""
    path = path or current_doc_path()
    reader = _paragraphs_odt if path.suffix == ".odt" else _paragraphs_docx
    lines = [l.strip() for l in reader(path)]
    lines = [l for l in lines if l]

    rules, test_prompts, chunks, examples = [], [], [], []
    section = None
    current = example = None
    for line in lines:
        if line in SECTION_HEADINGS:
            section = line
            continue
        if section == RULES_HEADING:
            rules.append(line)
        elif section == TEST_PROMPTS_HEADING:
            test_prompts.append(line)
        elif section == EXAMPLES_HEADING:
            m = EXAMPLE_QUESTION.match(line)
            if m:
                example = {"num": int(m.group(1)), "title": m.group(2), "body": []}
                examples.append(example)
            elif example is not None:
                example["body"].append(line)
        elif section == CHUNKS_HEADING:
            m = CHUNK_HEADING.match(line)
            if m:
                current = {"id": m.group(1), "title": m.group(2).strip(),
                           "body": [], "sources": [], "kind": "curated"}
                chunks.append(current)
            elif current is None:
                continue
            elif line.lower().startswith("source"):
                current["sources"] += URL.findall(line)
            elif URL.fullmatch(line):
                current["sources"].append(line)
            else:
                current["body"].append(line)

    for c in chunks:
        c["text"] = c["title"] + "\n" + "\n".join(c.pop("body"))

    if not rules or not chunks:
        raise ValueError(
            f"Parsed {len(rules)} rules and {len(chunks)} chunks from {path.name}. "
            f"Check that the headings '{RULES_HEADING}' and '{CHUNKS_HEADING}' are unchanged."
        )
    missing = [c["id"] for c in chunks if not c["sources"]]
    if missing:
        raise ValueError(f"Chunks with no Source URL in {path.name}: {', '.join(missing)}")
    example_chunks, skipped = _example_chunks(examples, chunks)
    return {"rules": rules, "chunks": chunks, "examples": example_chunks,
            "skipped_examples": skipped, "test_prompts": test_prompts, "path": path}


def _fact_tokens(text: str) -> set[str]:
    """Emails, phone numbers, dollar amounts, and content words, for matching examples to chunks."""
    facts = set(EMAIL.findall(text.lower())) | {re.sub(r"\D", "", p) for p in
                                                PHONE.findall(text)}
    facts |= set(re.findall(r"\$[\d,]+", text))
    words = {w for w in re.findall(r"[a-z']+", text.lower()) if len(w) > 4}
    return facts | words


def _example_chunks(examples: list[dict], chunks: list[dict]) -> tuple[list[dict], list[dict]]:
    """Turn the doc's example Q&As into chunks. Examples without their own URL take the source of
    the curated chunk they overlap with most (shared contacts count far more than shared words)."""
    out, skipped = [], []
    for ex in examples:
        answer = " ".join(ex["body"])
        if not answer or BEHAVIOR_NOTE.match(answer):
            skipped.append(ex)
            continue
        sources = URL.findall(answer)
        sources = [u.rstrip(".,;:") for u in sources]
        matched = None
        if not sources:
            ex_tokens = _fact_tokens(ex["title"] + " " + answer)

            def score(c):
                shared = ex_tokens & _fact_tokens(c["text"])
                return sum(10 if ("@" in t or t.isdigit() or t.startswith("$")) else 1
                           for t in shared)

            matched = max(chunks, key=score)
            sources = matched["sources"]
        out.append({"id": f"EXAMPLE-{ex['num']:02d}", "title": ex["title"],
                    "text": ex["title"] + "\n" + answer, "sources": sources,
                    "kind": "example", "matched": matched["id"] if matched else None})
    return out, skipped


# ---------- scraped pages ----------

def _manifest_urls() -> dict[str, str]:
    with open(config.SCRAPED_DIR / "_manifest.csv", newline="") as f:
        return {row["filename"]: row["url"] for row in csv.DictReader(f)}


def _staff_records() -> list[dict]:
    """Parse the Engineering Advancement staff directory into one record per person."""
    lines = [l.strip() for l in
             (config.SCRAPED_DIR / STAFF_DIRECTORY_FILE).read_text().splitlines()]
    # A person's block starts with: name, title, blank line, "Office of ...".
    starts = [i for i in range(len(lines) - 3)
              if lines[i] and lines[i + 1] and not lines[i + 2]
              and lines[i + 3].startswith("Office of")]
    records = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        block = [l for l in lines[start:end] if l]
        room = next((l for l in block if "Shelby Center" in l), None)
        records.append({
            "name": block[0],
            "title": block[1],
            "email": next((m.group() for l in block for m in [EMAIL.search(l)] if m), None),
            "phone": next((m.group() for l in block for m in [PHONE.search(l)] if m), None),
            "room": room,
            "details": " ".join(l for l in block[2:]
                                if not l.startswith("Office of") and l != room
                                and not EMAIL.fullmatch(l) and not PHONE.fullmatch(l)),
        })
    return records


def _contact(person: dict) -> str:
    parts = [p for p in (person["email"], person["phone"]) if p]
    return f"{person['name']} ({person['title']}; {', '.join(parts)})"


def staff_chunks() -> list[dict]:
    """One chunk per person. The role description leads so it dominates the embedding."""
    chunks = []
    for p in _staff_records():
        text = f"{p['name']}, {p['title']}, Auburn Engineering Office of Advancement."
        if p["details"]:
            text += " " + p["details"]
        text += f"\nContact: {_contact(p)}."
        if p["room"]:
            text += f" Office: {p['room']}."
        slug = re.sub(r"[^A-Z]+", "-", p["name"].upper()).strip("-")
        chunks.append({"id": f"STAFF-{slug}", "title": f"{p['name']} — {p['title']}",
                       "text": text, "sources": [STAFF_DIRECTORY_URL], "kind": "staff"})
    return chunks


# Keyword that identifies each department in both the campaign filename and the
# directory's "liaison to the departments of ..." sentences.
DEPARTMENT_KEYWORDS = ["aerospace", "biosystems", "chemical", "civil", "computer science",
                       "electrical", "industrial", "materials", "mechanical", "wireless"]


def _liaisons() -> dict[str, list[dict]]:
    """Map department keyword -> staff listed as liaison to that department."""
    out: dict[str, list[dict]] = {}
    for p in _staff_records():
        for sentence in re.split(r"(?<=\.)\s+", p["details"]):
            low = sentence.lower()
            if "liaison" in low and "department" in low:
                for kw in DEPARTMENT_KEYWORDS:
                    if kw in low:
                        out.setdefault(kw, []).append(p)
    return out


def department_chunks() -> list[dict]:
    """One chunk per department campaign page, keeping only the department-specific text."""
    urls = _manifest_urls()
    liaisons = _liaisons()
    chunks = []
    for path in sorted(config.SCRAPED_DIR.glob(DEPARTMENT_PREFIX + "*.txt")):
        lines = [l.strip() for l in path.read_text().splitlines() if l.strip()]
        if lines and lines[0] == "Share on":
            lines = lines[1:]
        cut = next((i for i, l in enumerate(lines)
                    if l.startswith(DEPARTMENT_BOILERPLATE_START)), len(lines))
        name, unique = lines[0], lines[1:cut]
        url = urls[path.name]
        text = (f"Giving to {name} at Auburn Engineering.\n" + "\n".join(unique) +
                f"\nGive online to this department at {url}")
        kw = next(k for k in DEPARTMENT_KEYWORDS if k.replace(" ", "_") in path.stem)
        if kw in liaisons:
            text += ("\nEngineering Advancement liaison for this department: " +
                     "; ".join(_contact(p) for p in liaisons[kw]) + ".")
        slug = path.stem.removeprefix(DEPARTMENT_PREFIX).upper().replace("_", "-")
        sources = [url, STAFF_DIRECTORY_URL] if kw in liaisons else [url]
        chunks.append({"id": f"DEPT-{slug}", "title": name, "text": text,
                       "sources": sources, "kind": "department"})
    return chunks


def all_chunks() -> tuple[list[dict], dict]:
    doc = read_doc_sections()
    chunks = doc["chunks"] + doc["examples"] + staff_chunks() + department_chunks()
    ids = [c["id"] for c in chunks]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"Duplicate chunk IDs: {sorted(dupes)}")
    return chunks, doc


if __name__ == "__main__":
    chunks, doc = all_chunks()
    print(f"Doc: {doc['path'].name}")
    print(f"{len(doc['rules'])} rules, {len(doc['test_prompts'])} test prompts")
    print("Skipped behavior-only examples: " +
          ", ".join(f"#{e['num']}" for e in doc["skipped_examples"]))
    for c in chunks:
        print(f"\n[{c['id']}] ({c['kind']}) sources={c['sources']}\n{c['text']}")
