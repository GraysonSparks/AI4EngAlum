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
python test_chatlog.py           # checks redaction and the saved-chat database (45 checks)
python test_recap.py             # checks the monthly recap, its storage and email (22 checks)
python test_priority.py          # checks that primary sources are matched first (10 checks)
python recap.py --print          # last month's recap on screen (nothing stored or sent)
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

**Source priority.** Not all sources are equal. The content document is what Advancement approved,
so its sections and example answers are **primary**; the scraped staff directory and department
pages are **secondary**. `retrieve()` takes the 12 nearest chunks (`CANDIDATES`), ranks each
secondary chunk as if it were `SECONDARY_PENALTY` (0.05) farther away, and keeps the best
`TOP_K` (4). So a primary chunk is matched first unless a secondary one is clearly closer, and the
model sees primary chunks first in its context. Real distances still decide `MAX_DISTANCE` and
citations.

| To | Do this |
|---|---|
| Make one content-document section secondary (or primary) | Add a line `Priority: secondary` (or `primary`) to that section, then `python ingest.py`. |
| Treat a whole kind as primary | `PRIMARY_KINDS=curated,example,staff` (kinds: `curated`, `example`, `staff`, `department`), then `python ingest.py`. |
| Always use every relevant primary chunk before any secondary one | `SECONDARY_PENALTY=1` |
| Turn priority off | `SECONDARY_PENALTY=0` |

`python content.py` shows each chunk's tier; `python test_priority.py` runs 10 checks without the
models.

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
The email has only the question text, with sensitive numbers removed: no address or other turns.

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
Each new message and its answer is saved with sensitive numbers removed (see "Saved chats" below).
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

**Redaction.** Visitors are not asked for sensitive data, but some type it anyway. Before a row is
saved (and before an unanswered question is emailed), `redact.py` replaces sensitive numbers with a
label. **Phone numbers and email addresses are kept**, so a visitor who types "call me at
334-555-0123" in the chat can be contacted; the monthly recap lists those messages.
`REDACT_CONTACT_DETAILS=1` removes them too (`[PHONE]`, `[EMAIL]`).

People type the same number in many ways, so it is checked in this order:

| Step | Found | Saved as | Examples caught |
|---|---|---|---|
| 1 | Email address | kept | `jdoe1985@gmail.com` (set aside first, so its digits are never read as a number) |
| 2 | A number after a word that names it | `[SSN]`, `[ACCOUNT NUMBER]`, `[ROUTING NUMBER]`, `[CARD NUMBER]`, `[SECURITY CODE]`, `[PIN]`, `[ID NUMBER]` | `SSN 123456789`, `last four of my social 6789`, `account # 0012-3456-78`, `my account number is 3345550123`, `routing 062000019`, `visa ending in 1234`, `cvv 123`, `PIN 4321`, `driver's license 1234567`, `student id 903123456` |
| 2 | A password | `[PASSWORD]` | `password: hunter2` |
| 3 | Social Security number | `[SSN]` | `123-45-6789`, `123 45 6789`, `123.45.6789` |
| 4 | Card number | `[CARD NUMBER]` (Luhn-valid) or `[NUMBER]` | `4111 1111 1111 1111`, `4111111111111111`, Amex `3782 822463 10005` |
| 5 | Phone number | kept | `(334) 555-0123`, `334.555.0123`, `+1 334 555 0123`, `3345550123`, `555-0123`, `1-800-555-0199 ext. 12`, `+44 20 7946 0958` |
| 6 | Any other long number | `[NUMBER]` | 8+ digits in a row (`123456789`), or digit groups of 9+ digits in total (`0012 3456 7890`) |

Step 2 comes before step 5, so an account number shaped like a phone number is still removed when
the visitor names it. Each word needs a minimum number of digits after it (4 for most, 9 for a
routing number), so "card 25" or "the 2026 social" are left alone.

Short numbers stay, because they are useful and not personal: gift amounts (`$5,000`,
`$1000000`), class years, course numbers (`ELEC 3810`), dates (`12/31/2026`), year ranges and
percentages. Removing *every* number would destroy those and also the phone numbers we want, so the
patterns above are used instead.

Not caught: numbers written as words ("one two three"), names, street addresses and dates of birth.
`python redact.py "<text>"` shows what a message would be saved as; `python test_chatlog.py` runs
45 checks.

## Monthly recap (`recap.py`)

Once a month, the saved chats are summed up for Advancement: conversation and question counts,
the share answered from approved content, the questions it couldn't answer (most frequent first),
the most-asked questions, the most-cited pages, follow-up form requests, and how much redaction
removed. The recap is:

- **emailed** to `RECAP_TO` (default `NOTIFY_TO`, which is Ed) on `NOTIFY_CHANNEL`, with every
  message of the month attached as a CSV (already redacted). A webhook gets the summary as JSON,
  without the CSV. With `NOTIFY_CHANNEL=none` nothing is sent;
- **stored** in the `recaps` table of the chat database, one row per month. With `DATABASE_URL`
  that table is on the PostgreSQL server, so the recaps are kept off the web server. Recaps hold
  no names or contact details and are kept after old chats are deleted.

With `RECAP_AUTO=1` (default) the server makes last month's recap by itself: it checks at
start-up and every 6 hours and runs once if the month is missing from `recaps`. If more than one
server process runs, or you prefer a scheduler, set `RECAP_AUTO=0` and run it on the 1st:

```bash
# cron, 6:00 AM on the 1st of each month
0 6 1 * *  cd /opt/ai4engalum/rag && /opt/ai4engalum/venv/bin/python recap.py
```

On Windows, a Task Scheduler task that runs `python recap.py` in `rag\` does the same.
`python recap.py --month 2026-10` redoes a month (it replaces that month's row and emails again);
`--no-email` stores without sending; `--print` only prints.
