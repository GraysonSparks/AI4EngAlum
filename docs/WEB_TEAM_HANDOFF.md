# Hosting the Giving Assistant on eng.auburn.edu/giving — guide for the Engineering web team

Team 21 (AI4EngAlum), Auburn COMP 4710, Fall 2026. Sponsor: Ed Collari, Executive Director of
Development, Engineering Advancement.

This guide covers what you need to host the assistant and put it on the giving pages. The code is
in this repository; setup commands are in [`../rag/README.md`](../rag/README.md). [`FILE_GUIDE.md`](FILE_GUIDE.md) lists every
file and marks which ones a deployment needs.

## What it is

- A **chat widget** (`rag/static/site/chat-widget.js`, one file, no dependencies) that sits at the
  bottom left of a page, level with the site's "back to top" button (`TOP_BUTTON_MID` in the file).
- A **Python backend** (FastAPI) that answers giving questions using only approved content: the
  curated content document in `content/` and text copies of the official giving pages in
  `scraped_pages/`.
- A **local language model** run by [Ollama](https://ollama.com): `qwen3.5:9b` for answers and
  `nomic-embed-text` for search. No question is sent to OpenAI or any other outside service.

It has **no connection to OAK or any donor record**. It saves each question and answer with
personal numbers and emails removed (`CHAT_LOG`, details in [`../rag/README.md`](../rag/README.md#saved-chats-chatlogpy-redactpy)).

## Adding it to a page

One tag, anywhere in the page:

```html
<script src="https://<backend-host>/chat-widget.js" defer></script>
```

The widget sends questions to the server it was loaded from. If the backend lives at a different
path, point it there:

```html
<script src="https://<cdn-or-backend>/chat-widget.js"
        data-endpoint="https://<backend-host>/chat" defer></script>
```

`/contact` and `/unanswered` are found next to `data-endpoint`, or can be set separately with
`data-contact-endpoint` and `data-unanswered-endpoint`.

All widget styles are scoped under `#aug-chat`, so they won't affect the page's CSS. The only thing
it writes to the browser is one sessionStorage flag: whether the visitor closed the greeting bubble.

## What the server needs

| | Minimum | Tested on |
|---|---|---|
| GPU | NVIDIA, 8 GB VRAM (both models fit together) | RTX 5070 Laptop 8 GB (Windows 11); Linux desktop GPU |
| RAM | 16 GB | |
| Disk | About 10 GB (models 7 GB, Python packages, index) | |
| Software | Python 3.12, Ollama 0.40+ | Python 3.12.14, Ollama 0.40.6 |
| OS | Linux or Windows | Arch Linux, Windows 11 |

It runs without a GPU, but each answer takes several seconds longer. On the Linux desktop the average
answer took 1.3 seconds in the October 29 test run.

Only port 8000 (the FastAPI app) needs to be reachable through your proxy. Ollama listens on
`localhost:11434` and should **not** be exposed.

## Running it

```bash
ollama pull qwen3.5:9b && ollama pull nomic-embed-text
python -m venv /opt/ai4engalum/venv && /opt/ai4engalum/venv/bin/pip install -r rag/requirements.txt
cd rag
python ingest.py                                   # builds the search index (about 1 minute)
uvicorn app:app --host 127.0.0.1 --port 8000       # put your reverse proxy in front of this
```

`GET /health` returns the chunk count and model names, which is useful for a monitor.

For a service, run `uvicorn` under systemd (Linux) or as a scheduled task / service wrapper
(Windows). Windows double-click scripts for a single machine are in [`../windows/`](../windows/).

## Settings for production

All settings are environment variables (defaults in `rag/config.py`):

| Variable | Set to | Why |
|---|---|---|
| `CORS_ORIGINS` | `https://eng.auburn.edu` | Only if the widget is loaded from a different host than the backend. |
| `TRUST_FORWARDED_FOR` | `1` | **Only behind a proxy that sets `X-Forwarded-For`.** Otherwise every visitor looks like the proxy and shares one spam limit. |
| `CHROMA_DIR` | e.g. `/var/lib/ai4engalum/chroma_db` | Search index location, rebuilt by `ingest.py`. |
| `CONTACT_REQUESTS_FILE` | e.g. `/var/lib/ai4engalum/contact_requests.jsonl` | Where follow-up form submissions are saved (**personal data**: restrict who can read it). |
| `CHAT_LOG_DB` | e.g. `/var/lib/ai4engalum/chats.sqlite3` | Saved chats (redacted). Or set `DATABASE_URL=postgresql://...` to use a PostgreSQL server. `CHAT_LOG=0` turns saving off. |
| `CHAT_LOG_RETENTION_DAYS` | 400 (default) | Saved chats older than this are deleted. |
| `RECAP_AUTO` | `1` (default), or `0` | `1`: the server emails and stores last month's recap by itself. Set `0` if several uvicorn workers run, and schedule `python recap.py` on the 1st instead. |
| `RECAP_TO` | empty (default) | Recap recipients; empty means `NOTIFY_TO`. |
| `UNANSWERED_SECRET` | a long random string | Signs unanswered questions. If unset, a new one is made each start, which is fine. |
| `NOTIFY_CHANNEL` | `email` | Advancement chose email. Default `none` sends nothing. |
| `NOTIFY_TO` | `elc0042@auburn.edu` (default) | Comma-separated recipients. |
| `NOTIFY_FROM` | an address your mail relay accepts | Default `giving-assistant@eng.auburn.edu`. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_STARTTLS`, `SMTP_USER`, `SMTP_PASSWORD` | your relay | `SMTP_USER` empty = no login. |
| `NOTIFY_ROUTED_STAFF` | `1` (optional) | Also email the staff member the visitor picked. |
| `RATE_LIMIT`, `RATE_WINDOW_SECONDS` | 5 / 600 (default) | Form and report submissions per address. |

Check email delivery once after setup by submitting the follow-up form on the test page
(`https://<backend-host>/`). The request is saved even if email fails, and failures are logged.

## Endpoints

| Method + path | Used by | What it does |
|---|---|---|
| `POST /chat` | widget | `{"message", "history", "conversation_id"}` → answer, source links, contact cards. The message and answer are saved, redacted. |
| `POST /contact` | widget's follow-up form | Saves name, email, optional phone and message (only with consent), then notifies. |
| `POST /unanswered` | widget, when a chat ends | Emails the giving questions the assistant couldn't answer, redacted. Only signed questions from `/chat` are accepted. |
| `GET /health` | monitoring | Index size and model names. |
| `POST /reload-rules` | staff | Re-reads the response rules from the content document. **Block this at the proxy** or limit it to campus addresses. |
| `GET /` | testing | A copy of the giving pages with the widget, for trying it out. Can be blocked in production. |

## Security and privacy summary

- No donor data. Each question and answer is saved with emails, phone, Social Security, card and
  other long numbers removed, under a random conversation ID; no IP address or browser details.
  Restrict who can read the database. The last few turns sent with each request are used for that
  one answer and dropped.
- The only stored contact details are from a follow-up form the visitor chose to submit with consent.
- Spam protection on the form and the unanswered report: per-address rate limit (held in memory),
  a hidden honeypot field, and a minimum time the form must be open.
- Every answer is checked in code: links that are not from the approved sources are replaced, and a
  declined question always ends with Ed's contact details instead of anything the model suggested.
- Responses set `Cache-Control: no-store`.

## Keeping it up to date

See [`CONTENT_REFRESH.md`](CONTENT_REFRESH.md). In short: edit the content document or re-run the
scraper, run `python ingest.py`, restart. If Advancement changes its main contact, update the
`FALLBACK_*` variables **and** `MAIN_CONTACT` near the top of `chat-widget.js` (the widget shows
it when the backend can't be reached).

## Tests to run after any change

```bash
cd rag
python test_contact.py               # 18 checks: form, consent, spam limits, /unanswered
python test_notify.py                # 13 checks: email and webhook with a fake server
python test_chatlog.py               # 28 checks: redaction and the saved-chat database
python test_recap.py                 # 20 checks: the monthly recap
python eval_models.py qwen3.5:9b     # 63 scored questions against the real model
```

## Contacts

Team: Grayson Sparks, Hongyi Wang. Sponsor: Ed Collari (elc0042@auburn.edu).
