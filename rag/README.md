# AI4EngAlum RAG backend

Local RAG chat assistant for eng.auburn.edu/giving: Ollama `qwen3.5:9b` for answers (thinking off),
`nomic-embed-text` for embeddings, embedded ChromaDB for the index, FastAPI for `/chat`.

## Setup (once)

On the Windows laptop, use the scripts in `../windows/` instead (see its README).

```bash
ollama pull qwen3.5:9b
ollama pull nomic-embed-text
uv venv --python 3.12 ~/.local/share/venvs/ai4engalum-rag   # kept outside the project folder
VIRTUAL_ENV=~/.local/share/venvs/ai4engalum-rag uv pip install -r requirements.txt
source ~/.local/share/venvs/ai4engalum-rag/bin/activate
```

## Run

```bash
python ingest.py                 # rebuild the index; re-run after editing the doc or scraped pages
uvicorn app:app --port 8000      # test site + chat at http://localhost:8000/
python run_test_prompts.py       # runs the doc's "Suggested Initial Test Prompts"
python content.py                # print every chunk exactly as it will be embedded (reads ../content/)
python eval_models.py qwen3.5:9b gemma4:12b   # scored comparison of chat models (63 cases)
python routing.py                # print the staff routing table built from the directory
python test_contact.py           # checks the follow-up form, spam protection and /unanswered (18 checks)
python test_notify.py            # checks notifications and unanswered emails with fake SMTP/webhook (13 checks)
python test_chatlog.py           # checks redaction and the saved-chat database (28 checks)
```

`POST /reload-rules` picks up edits to the doc's Response Rules without restarting the server
(chunk edits need `python ingest.py` + a restart).

## What gets indexed (56 chunks)

| Source | Chunks | Notes |
|---|---|---|
| `AI4EngAlum Giving Content for RAG` (.odt or .docx, whichever was saved last) | 16 | One per `GIVING-XXX-01` section. Question + answer embedded; `Source:` URLs stored as metadata. |
| Same doc, "Example Questions and Grounded Answers" | 15 | One per numbered Q&A. Examples that only describe bot behavior ("The chatbot should...") are skipped; the response rules cover them. An example without its own URL takes the source of the curated chunk it overlaps with most (run `python content.py` to see the matches). |
| Staff directory (`scraped_pages/eng_auburn_edu_admin_development_index_html.txt`) | 15 | One per person, role description first. |
| Department campaign pages (`scraped_pages/give_auburn_edu_campaigns_*.txt`) | 10 | Only the department-specific paragraphs; shared boilerplate dropped. The department's advancement liaison (parsed from the directory) is appended. |

The doc's **Recommended Response Rules** become the core of the system prompt. `rag.py` adds
fixed instructions for grounding, the tax/legal refusal, prompt-injection handling, and the fallback contact.

**Main contact.** Advancement chose Ed Collari (Executive Director of Development) as the main point of
contact instead of the general giving office. Every dead end, and every "can someone contact me?",
gives his details first and then offers to have him reach out (the follow-up form) as the second
option. He also receives every notification. His details are `FALLBACK_*` in `config.py`; `python routing.py` warns if
they stop matching his staff directory entry. Answers taken from the content doc still give whatever
contact the doc lists (for example the giving office for bank drafts).

## Guardrails outside the prompt

- If no chunk is within cosine distance `MAX_DISTANCE` (0.5), the fixed fallback reply is returned without calling the model.
- Any URL in the answer that isn't one of the retrieved chunks' sources is replaced with the best source URL.
- Cited `sources` include only chunks within 0.08 of the best match.

Settings (models, top-k, threshold, paths) live in `config.py` and can be overridden with env vars.

## Staff routing

Retrieval finds the right person when a question uses the directory's wording, but it missed
questions such as "I live in Atlanta, who can I meet with?" or "who helps a student org with
fundraising?". `routing.py` adds a table of 30 routes (9 department liaisons, 12 programs, 9 regions)
that is matched against any question asking for a person:

- The table holds topics and the phrase that identifies the owner in the staff directory, never a
  name, email, or phone number. Contact details come from `scraped_pages/` at startup, so
  re-scraping the directory updates the routes. `python routing.py` flags a route whose phrase no
  longer matches anyone.
- A matched contact is placed first in the model's context. If the model still declines, the backend
  states the contact itself, so a routed question never ends in a bare decline.
- `/chat` returns the routed staff in `contacts`, and the widget shows each as a card with their
  email, phone, and an "Ask <name> to contact me" button.
- Materials Engineering has no liaison in the directory, so it has no route and no card.

## Follow-up requests

A visitor can leave their details for a staff member to follow up:

- **When the form appears:** from the button on a contact card, or when the visitor asks to be
  contacted ("can someone call me?"). That request gets a fixed reply with Ed's details first, then
  the form (`offer_contact: true`), and no model call.
- **When the assistant can't answer:** whether the model declines or no content is close enough to
  ask it, the reply gives Ed's details, and `/chat` returns `offer_followup: true` with his contact
  card, whose "Ask Ed to contact me" button opens the form. This applies to every dead end,
  off-topic ones included. The model's own "contact the giving team" sentences are removed, so Ed
  is the only contact given.
- **Which dead ends are reported to Ed:** a second, short model call (only on dead ends) decides
  whether the question is about giving to Engineering at all. Only those are emailed as unanswered
  questions (`report_unanswered`), so off-topic questions, private-data requests and injection
  attempts stay out of his inbox. Retrieval
  distance couldn't make that call: "Can I donate to Auburn football?" is closer to the giving
  content than most real giving questions. `eval_models.py` checks the offer on every decline case.
- **What is collected:** first name, last name, email, optional phone, optional message, and the
  routed staff member if there is one. The consent box must be ticked; `POST /contact` rejects a
  request without it.
- **Where it goes:** one line per request in `rag/data/contact_requests.jsonl` (gitignored; override
  with `CONTACT_REQUESTS_FILE`). The conversation, IP address, and browser details are not attached.
  Card, Social Security and other long numbers are removed from the free-text message (the email
  and phone fields stay, because the visitor gave them to be contacted).
  All writes go through `leads.save_request()`, the one place to change when Advancement decides
  where requests should live.
- **Spam protection:**
  - A hidden "Website" field that people never see. Bots fill in every field.
  - The form reports how long it was open. A submission faster than `FORM_MIN_SECONDS` (3 s), or
    with no timer at all (posted straight to the API), is treated as a bot.
  - Bots get the same `{"ok": true}` as a person, so they can't tell they were caught, and nothing
    is stored or sent.
  - Each address gets `RATE_LIMIT` (5) requests per `RATE_WINDOW_SECONDS` (10 min) to `/contact`
    and to `/unanswered`, then `429`. Addresses are held in memory only for that window, never
    written. Behind the web team's proxy, set `TRUST_FORWARDED_FOR=1` so the limit applies per
    visitor instead of to the proxy.
  - A CAPTCHA can be added if spam gets past these.

## Unanswered-question emails

Advancement wanted to see which donor questions the assistant can't answer. When a giving question hits a dead end, `/chat` returns it in `unanswered` with an HMAC signature. The widget keeps those in page
memory and posts them to `POST /unanswered` once the visitor is done: on closing or clearing the
chat, leaving the page, or after 10 minutes without a new one. The server checks each signature,
so only questions the assistant really failed on are sent, then emails them to `NOTIFY_TO` (Ed).
The email has only the question text, with personal numbers and emails removed: no name, address
or other turns.

A weekly digest would mean keeping question text on the server until it is sent. Say so if
Advancement prefers that; it's a small change in `notify.py`.

## Staff notifications

After a request is stored, `notify.py` tells staff about it in a background thread, so the visitor
never waits on it and a failed notification never loses a request (it is logged; the request is
already in the file). The channel depends on hosting, so it is set by env var:

| `NOTIFY_CHANNEL` | What happens | Settings |
|---|---|---|
| `none` (default) | Nothing is sent; requests are only stored. Stays the default until hosting is decided, so local testing never emails anyone. | |
| `email` (Advancement's choice) | Email to `NOTIFY_TO` (default: Ed Collari) with the visitor's name, email, phone, message and routed staff member. Reply-To is the visitor. | `NOTIFY_TO` (comma-separated), `NOTIFY_FROM`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_STARTTLS=1`, `SMTP_USER`, `SMTP_PASSWORD` |
| `webhook` | POST `{"title", "text", "request"}` to a Teams, Slack or Power Automate webhook. | `NOTIFY_WEBHOOK_URL` |

Advancement decided Ed gets every alert. By default only `NOTIFY_TO` does;
`NOTIFY_ROUTED_STAFF=1` also emails the staff member the visitor asked for, using the address from
the scraped directory. The chat conversation is never included.

## Test site (`static/site/`)

A local mock of the eng.auburn.edu/giving pages for testing the assistant in context: giving home,
Ways to Give, EAGLE Society, and the staff directory. It uses the live site's colors and text, and all
Give/Visit buttons link to the real Auburn pages. A banner marks it as a Team 21 test mock, so keep it
local and don't host it publicly.

The widget is labeled as AI: an "AI" tag in the header, "AI assistant" under the name, the
greeting, the "Giving Assistant (AI)" label on each reply, and the footer note.

The chat is a single drop-in file, `chat-widget.js`, loaded with
`<script src="chat-widget.js" defer></script>`. It posts to `/chat` on whatever server it was loaded
from (override with `data-endpoint="..."`). Its CSS is scoped under `#aug-chat`, and the conversation
persists across pages for the browser session. To embed it on a page served from another origin,
start the backend with `CORS_ORIGINS=<that origin>`.

## Conversation memory

The assistant follows up within a conversation ("Who is the liaison for *that* department?").
Each new message and its answer is saved with personal data removed (see "Saved chats" below).
(The follow-up form above is separate: it stores only what the visitor submits in it.)

- **Browser:** the widget keeps the conversation in page memory only. Nothing goes to localStorage,
  sessionStorage, or cookies. The one exception is a yes/no "pop-up dismissed" flag in sessionStorage,
  which holds no conversation content. A reload, page change, tab close, or **Clear** ends the conversation.
- **Server:** each `/chat` request carries the last 6 messages (`HISTORY_MESSAGES` in `config.py`).
  The server uses them for that one answer and discards them; only the new message and its answer
  are saved, redacted (next section). uvicorn's access log records only `POST /chat` and the status
  code. Responses are sent with `Cache-Control: no-store`.
- **Follow-ups:** when there's history, the model first rewrites the latest message as a standalone
  question for the search ("that department" → "the Computer Science and Software Engineering
  Department"). The answer step sees both the visitor's wording and the resolved question.
- **Ollama** keeps the most recent prompt in GPU memory while the model is loaded (default 5 minutes
  after the last request) to speed up the next one. That memory is overwritten by later requests and
  never written to disk.

`eval_models.py` includes 7 multi-turn cases: follow-ups, a topic switch, and an injection attempt
inside a follow-up.

## Saved chats (`chatlog.py`, `redact.py`)

Every `/chat` request saves two rows: the visitor's message and the assistant's answer. Each row has
the text, a random conversation ID from the widget (new on each **Clear**), the time, whether the
question was answered, whether it was reported as unanswered, the cited sources, and how many items
were redacted. No IP address, browser details or name is saved. The widget footer tells visitors
that chats are saved.

| Setting | Default | What it does |
|---|---|---|
| `CHAT_LOG` | `1` | `0` saves nothing. Then also set `SAVE_NOTICE` in `chat-widget.js` to `''`. |
| `CHAT_LOG_DB` | `rag/data/chats.sqlite3` | The SQLite file (gitignored). |
| `DATABASE_URL` | empty | `postgresql://user:pass@host/db` saves to a PostgreSQL server instead, for example one the web team runs on another machine. Needs `pip install "psycopg[binary]"`. |
| `CHAT_LOG_RETENTION_DAYS` | `400` | Older rows are deleted at start-up. `0` keeps everything. |

A failed save is logged and never stops the answer.

**Redaction.** Visitors are not asked for personal data, but some type it anyway. Before a row is
saved (and before an unanswered question is emailed), `redact.py` replaces:

| Found | Saved as | Pattern |
|---|---|---|
| Email address | `[EMAIL]` | `name@domain.tld` |
| Social Security number | `[SSN]` | `123-45-6789` or `123 45 6789` |
| Card number | `[CARD NUMBER]` | 13 to 19 digits, with or without spaces or dashes |
| Phone number | `[PHONE]` | US formats: `334-555-0123`, `(334) 555-0123`, `+1 334.555.0123` |
| Any other long number | `[NUMBER]` | 7 or more digits in a row: account, routing and ID numbers |

Short numbers stay, because they are useful and not personal: gift amounts (`$5,000`), class years,
course numbers, dates and percentages. Removing *every* number would destroy those, and an email
like `jdoe1985@...` would still be half there, so the patterns above are used instead. Emails and
phone numbers that are already public in the approved content (Ed, the giving office, staff in the
directory) are kept, so saved answers stay readable. A visitor who wants to be contacted uses the
follow-up form, which keeps their email and phone with consent.

Not caught: names, street addresses and dates of birth (no reliable pattern, and removing names
would also remove the staff names the assistant gives). `python redact.py "<text>"` shows what a
message would be saved as; `python test_chatlog.py` runs 28 checks.
