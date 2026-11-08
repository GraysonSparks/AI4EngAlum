"""Embed all chunks with nomic-embed-text and (re)build the local Chroma collection.

Re-run this any time the content doc or scraped pages change:
    python ingest.py
"""

import chromadb

import config
from content import all_chunks
from rag import DOC_PREFIX, embed


def main():
    chunks, doc = all_chunks()
    print(f"Content doc: {doc['path'].name}")
    print(f"Chunks: {len(chunks)} "
          f"({', '.join(f'{k}={sum(c['kind'] == k for c in chunks)}' for k in ('curated', 'example', 'staff', 'department'))})")

    embeddings = embed([c["text"] for c in chunks], DOC_PREFIX)

    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    try:
        client.delete_collection(config.COLLECTION)
    except Exception:
        pass  # first run: nothing to delete
    collection = client.create_collection(config.COLLECTION,
                                          metadata={"hnsw:space": "cosine"})
    collection.add(
        ids=[c["id"] for c in chunks],
        documents=[c["text"] for c in chunks],
        embeddings=embeddings,
        metadatas=[{"title": c["title"], "kind": c["kind"],
                    "sources": " | ".join(c["sources"])} for c in chunks],
    )
    print(f"Wrote {collection.count()} chunks to {config.CHROMA_DIR}")


if __name__ == "__main__":
    main()
