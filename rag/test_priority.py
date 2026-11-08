"""Check source priority (primary sources matched first) without the models or the index.

    python test_priority.py
"""

from pathlib import Path

import config
import content
import rag


class FakeCollection:
    """Returns fixed nearest chunks, nearest first, like Chroma's query()."""

    def __init__(self, chunks):
        self.chunks = chunks

    def query(self, query_embeddings, n_results):
        found = self.chunks[:n_results]
        return {"ids": [[c[0] for c in found]], "documents": [["text"] * len(found)],
                "distances": [[c[2] for c in found]],
                "metadatas": [[{"title": c[0], "kind": c[1], "sources": "https://example.edu",
                                **({"tier": c[3]} if len(c) > 3 else {})} for c in found]]}


# (id, kind, distance[, tier stored by ingest.py])
NEAREST = [
    ("DEPT-MECH", "department", 0.21),
    ("GIVING-DEPARTMENTS-01", "curated", 0.25),
    ("DEPT-CHEM", "department", 0.27),
    ("EXAMPLE-01", "example", 0.28),
    ("STAFF-A", "staff", 0.29),
    ("EXAMPLE-02", "example", 0.30),
    ("GIVING-PROMOTED-01", "department", 0.32, "primary"),
]


def ids(penalty, top_k=4, candidates=12, nearest=NEAREST):
    config.SECONDARY_PENALTY, config.TOP_K, config.CANDIDATES = penalty, top_k, candidates
    a = rag.Assistant.__new__(rag.Assistant)  # skip __init__: no index or model needed
    a.collection = FakeCollection(nearest)
    return [h["id"] for h in a.retrieve("question")], a.retrieve("question")


def main():
    rag.embed = lambda texts, prefix: [[0.0]]
    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"\n      {detail}" if not ok and detail else ""))

    got, _ = ids(0)
    check("SECONDARY_PENALTY=0 keeps plain distance order",
          got == ["DEPT-MECH", "GIVING-DEPARTMENTS-01", "DEPT-CHEM", "EXAMPLE-01"], str(got))
    got, hits = ids(0.05)
    check("primary chunk within the penalty comes first",
          got[:2] == ["GIVING-DEPARTMENTS-01", "DEPT-MECH"], str(got))
    check("a closer secondary chunk still makes the cut", "DEPT-MECH" in got, str(got))
    check("a far secondary chunk gives way to a primary one",
          "DEPT-CHEM" not in got and "EXAMPLE-02" in got, str(got))
    check("reported distance is the real one, not the ranked one",
          next(h for h in hits if h["id"] == "DEPT-MECH")["distance"] == 0.21)
    got, _ = ids(1)
    check("a large penalty puts every primary chunk first",
          got == ["GIVING-DEPARTMENTS-01", "EXAMPLE-01", "EXAMPLE-02", "GIVING-PROMOTED-01"], str(got))
    check("a tier stored in the index overrides the kind", "GIVING-PROMOTED-01" in got, str(got))
    got, _ = ids(0.05, nearest=[(c[0], c[1], c[2]) for c in NEAREST])
    check("an index without tiers falls back to the kind",
          got[:2] == ["GIVING-DEPARTMENTS-01", "DEPT-MECH"], str(got))

    # "Priority:" lines in the content document.
    lines = ["Recommended Response Rules", "Be brief.", "Proposed RAG Chunks",
             "GIVING-A-01 — First", "Body A.", "Priority: secondary", "Source: https://a.example",
             "GIVING-B-01 — Second", "Body B.", "Source: https://b.example"]
    original = content._paragraphs_docx
    content._paragraphs_docx = lambda path: lines
    try:
        doc = content.read_doc_sections(Path("fake.docx"))
    finally:
        content._paragraphs_docx = original
    a, b = doc["chunks"]
    check("'Priority: secondary' line sets the section's tier",
          content.tier(a) == "secondary" and content.tier(b) == "primary",
          f"{content.tier(a)}, {content.tier(b)}")
    check("the Priority line is not part of the embedded text", "Priority" not in a["text"], a["text"])

    print(f"\n{sum(results)}/{len(results)} passed")
    raise SystemExit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
