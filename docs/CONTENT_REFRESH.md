# Keeping the assistant's information current

On October 20 Ed asked how heavy a lift it is to change the assistant's information. **Light:** no
code changes are needed. Most updates take 10–15 minutes including the checks. The assistant knows only
two sources, and each one has its own way to update.

| What changed | Where it lives | What to do | Time |
|---|---|---|---|
| A giving answer, a policy, an amount, a program description | `content/AI4EngAlum Giving Content for RAG` (.odt or .docx) | Edit the document, then rebuild (below) | Edit + 5 min |
| How the assistant should behave (tone, what to decline) | Same document, "Recommended Response Rules" section | Edit, then `POST /reload-rules`, no restart | Edit + 1 min |
| Staff joined, left, or changed role, phone, liaison departments or territory | The official staff directory page | Re-scrape, then rebuild | 10 min |
| A department's giving page text | give.auburn.edu campaign pages | Re-scrape, then rebuild | 10 min |
| The main point of contact (now Ed Collari) | `FALLBACK_*` settings + `MAIN_CONTACT` in `chat-widget.js` | Change both, restart | 5 min |

Staff routing ("who do I talk to about Aerospace?") is built from the staff directory each time the
server starts, so a re-scrape updates it with no other change.

## Editing the content document

Keep the structure the code reads:

- Each answer is a section headed `GIVING-<TOPIC>-01 — <Question>`, with the answer below and a
  `Source:` line holding the official URL. A section without a Source URL stops the rebuild with an
  error naming it. That is deliberate: every answer must be traceable to an official page.
- Section headings ("Recommended Response Rules", "Proposed RAG Chunks", "Example Questions and
  Grounded Answers", …) must keep their exact wording.
- Either the .odt or the .docx can be edited. The assistant uses whichever was saved last.
- Sections in this document are **primary** sources: when a question matches both a section here
  and a scraped page about equally, the section here is used first. To make a section count less
  (for example, a general overview that should not outrank a specific department page), add a line
  `Priority: secondary` to it. `Priority: primary` does the opposite. Rebuild after the change.

Check what will be indexed: `python content.py` prints every chunk exactly as the assistant sees it.

## Re-scraping the official pages

```bash
cd scraper && python scrape_giving_pages.py     # about 2 minutes; rewrites ../scraped_pages/
git diff --stat ../scraped_pages                # see which pages changed
cd ../rag && python routing.py                  # routes; warns if a route or the main contact went stale
```

To add a page, add its URL to `URLS` at the top of `scrape_giving_pages.py`.

## Rebuild and check

```bash
cd rag
python ingest.py                     # about 1 minute
# restart the server (or Stop/Start on Windows)
python eval_models.py qwen3.5:9b     # 63 scored questions, about 2 minutes; all should pass
```

If an eval case fails after a content change, either the content now says something different (update
the case in `eval_models.py` to the new correct answer) or the change broke an answer (fix the
document).

## Suggested schedule

- **When something changes** (a staff move, a new program): update that day.
- **Each semester:** re-scrape and look at `git diff` even if nobody reported a change. The first
  re-scrape, on October 29, 2026, found two staff directory changes that had happened since September:
  a development officer (Chris Harris) now listed as liaison to Electrical and Computer and to Civil
  and Environmental Engineering, and a new development coordinator (Avery Storm).
- **Monthly:** read the unanswered-question emails (sent to the main contact). Questions that come
  up repeatedly are the best guide to what to add to the content document.

## Who does it

Editing the document needs no technical skills. Re-scraping and rebuilding are four commands on the
server and suit whoever hosts the assistant (the Engineering web team). On the Windows laptop,
`Setup.bat` rebuilds the index and runs all the checks in one step.
