"""Save chat messages to a database, with personal numbers and emails removed (see redact.py).

Each /chat request saves two rows: the visitor's message and the assistant's answer. A row holds
the redacted text, a random conversation ID made by the widget, the time, whether the assistant
could answer, and the sources it cited. It holds no IP address, browser details or name.

Where the rows go:

    CHAT_LOG=0                     nothing is saved
    CHAT_LOG_DB=<path>             (default) a SQLite file, rag/data/chats.sqlite3
    DATABASE_URL=postgresql://...  a PostgreSQL server, for example on another machine
                                   (needs `pip install "psycopg[binary]"`)

Rows older than CHAT_LOG_RETENTION_DAYS (default 400, so a full year of monthly recaps) are deleted
when the server starts and each time a recap runs.

A database error never stops a visitor's chat: it is logged and the answer is still returned.
"""

import json
import logging
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import config
import redact

log = logging.getLogger(__name__)

# A conversation ID from the widget: crypto.randomUUID(), or anything similar and short.
CONVERSATION_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")

SCHEMA = {
    "sqlite": [
        """CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation TEXT NOT NULL,
            at TEXT NOT NULL,
            role TEXT NOT NULL,
            text TEXT NOT NULL,
            answered INTEGER,
            unanswered INTEGER,
            sources TEXT,
            redacted TEXT)""",
        "CREATE INDEX IF NOT EXISTS messages_at ON messages (at)",
        "CREATE INDEX IF NOT EXISTS messages_conversation ON messages (conversation)",
    ],
    "postgres": [
        """CREATE TABLE IF NOT EXISTS messages (
            id BIGSERIAL PRIMARY KEY,
            conversation TEXT NOT NULL,
            at TEXT NOT NULL,
            role TEXT NOT NULL,
            text TEXT NOT NULL,
            answered INTEGER,
            unanswered INTEGER,
            sources TEXT,
            redacted TEXT)""",
        "CREATE INDEX IF NOT EXISTS messages_at ON messages (at)",
        "CREATE INDEX IF NOT EXISTS messages_conversation ON messages (conversation)",
    ],
}


class Store:
    """A small wrapper so the same SQL runs on SQLite and PostgreSQL ("?" placeholders)."""

    def __init__(self, url: str | None = None, path=None):
        self.url = url if url is not None else config.DATABASE_URL
        self.path = path or config.CHAT_LOG_DB
        self.dialect = "postgres" if self.url.startswith(("postgres://", "postgresql://")) else "sqlite"
        self._lock = threading.Lock()
        self._ready = False

    @contextmanager
    def connect(self):
        if self.dialect == "postgres":
            import psycopg  # optional: only needed when DATABASE_URL is set
            conn = psycopg.connect(self.url)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=10)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.dialect == "postgres" else sql

    def execute(self, sql: str, params=(), many: bool = False):
        with self._lock, self.connect() as conn:
            if not self._ready:
                for stmt in SCHEMA[self.dialect]:
                    conn.execute(stmt)
                self._ready = True
            cur = conn.cursor()
            (cur.executemany if many else cur.execute)(self._sql(sql), params)
            return cur.fetchall() if cur.description else cur.rowcount


_store: Store | None = None


def store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_turn(conversation: str | None, question: str, result: dict,
              keep: frozenset[str] = frozenset()) -> None:
    """Save one visitor message and the answer, redacted. Does nothing when CHAT_LOG=0."""
    if not config.CHAT_LOG:
        return
    conversation = conversation if conversation and CONVERSATION_ID.match(conversation) else None
    conversation = conversation or f"single-{datetime.now(timezone.utc).timestamp():.6f}"
    q_text, q_found = redact.redact(question, keep)
    a_text, a_found = redact.redact(result.get("answer", ""), keep)
    at = now()
    rows = [
        (conversation, at, "user", q_text, None, None, None, json.dumps(q_found) if q_found else None),
        (conversation, at, "assistant", a_text, int(not result.get("fallback")),
         int(bool(result.get("report_unanswered"))), " | ".join(result.get("sources", [])),
         json.dumps(a_found) if a_found else None),
    ]
    try:
        store().execute("INSERT INTO messages (conversation, at, role, text, answered, unanswered, "
                        "sources, redacted) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows, many=True)
    except Exception:
        log.exception("Could not save a chat message (the visitor still got the answer)")


def purge_old() -> int:
    """Delete messages older than CHAT_LOG_RETENTION_DAYS. Returns how many were deleted."""
    if not config.CHAT_LOG or config.CHAT_LOG_RETENTION_DAYS <= 0:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=config.CHAT_LOG_RETENTION_DAYS)
              ).isoformat(timespec="seconds")
    try:
        return store().execute("DELETE FROM messages WHERE at < ?", (cutoff,))
    except Exception:
        log.exception("Could not delete old chat messages")
        return 0


def messages_between(start: str, end: str) -> list[dict]:
    """Every saved message with start <= at < end (ISO times), oldest first."""
    rows = store().execute(
        "SELECT conversation, at, role, text, answered, unanswered, sources, redacted "
        "FROM messages WHERE at >= ? AND at < ? ORDER BY at, id", (start, end))
    keys = ("conversation", "at", "role", "text", "answered", "unanswered", "sources", "redacted")
    return [dict(zip(keys, r)) for r in rows]
