"""Run the doc's "Suggested Initial Test Prompts" (plus any extra prompts given as args)
through the full pipeline and print answers, retrieved chunks, and distances.

    python run_test_prompts.py
    python run_test_prompts.py "Who is the liaison for Mechanical Engineering?"
"""

import sys

from content import read_doc_sections
from rag import Assistant


def main():
    prompts = sys.argv[1:] or read_doc_sections()["test_prompts"]
    assistant = Assistant()
    print(f"Rules from: {assistant.rules_source}\n")
    for q in prompts:
        r = assistant.answer(q)
        hits = ", ".join(f"{h['id']}={h['distance']:.2f}" for h in r["retrieved"])
        print("=" * 80)
        print(f"Q: {q}")
        print(f"retrieved: {hits}")
        print(f"{'FALLBACK' if r['fallback'] else 'A'}: {r['answer']}")
        print(f"sources: {r['sources']}")


if __name__ == "__main__":
    main()
