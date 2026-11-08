# AI4EngAlum — Auburn Engineering Giving Assistant (Team 21)

A local RAG chat assistant for eng.auburn.edu/giving. Setup, running, testing, and design notes are in
[`rag/README.md`](rag/README.md).

- `rag/`: FastAPI backend, ingestion, evaluation, and a test website with the drop-in chat widget
- `content/`: hand-curated giving Q&A doc (the primary knowledge source)
- `scraped_pages/`: cleaned text of the official giving pages (staff directory, department pages)
- `scraper/`: the script that produced `scraped_pages/`
- `docs/`: [what every file does](docs/FILE_GUIDE.md) (and which ones hosting needs), [user guide for Engineering Advancement](docs/USER_GUIDE.md), [hosting guide for the
  Engineering web team](docs/WEB_TEAM_HANDOFF.md) and [how to keep the content current](docs/CONTENT_REFRESH.md)
- `windows/`: double-click setup and start/stop scripts for a Windows machine
