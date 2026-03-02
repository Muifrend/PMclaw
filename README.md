# Ghost PM Agent (OpenClaw)

Autonomous PM assistant for Telegram → Notion task capture with optional Tavily research enrichment.

## What it does
- Interprets task-like messages from a PM Telegram group
- Requires a due date (asks follow-up if missing)
- Parses natural dates (`tomorrow`, `in 3 days`, `next friday`, etc.)
- Writes clean task titles + raw message to Notion
- Deduplicates using `Dedup Key`
- Enriches research tasks via Tavily
- Optionally rewrites research into one coherent paragraph via OpenAI

## Project layout
- `skills/notion-pm/notion-client.py` — Notion CRUD + schema-aware writes
- `skills/notion-pm/pm_handler.py` — decision logic, date parsing, pending clarification flow
- `skills/notion-pm/run_ingest.py` — wrapper entrypoint for inbound messages
- `skills/notion-pm/research_client.py` — Tavily (+ optional OpenAI summarize)

## Setup
1. Create virtualenv and install deps:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install notion-client
   ```
2. Copy env template and fill values:
   ```bash
   cp .env.example .env
   ```
3. Share your Notion DB with your integration.

## Notion schema expected
Required properties:
- `Task Name` (Title)
- `Message` (Rich text)
- `Status` (Select: `New`, `In Progress`, `Done`)
- `Received At` (Date)
- `Due Date` (Date)
- `Dedup Key` (Rich text)
- `Priority` (Select: `High`, `Medium`, `Low`)

Optional properties for research enrichment:
- `Research Summary` (Rich text)
- `Research Links` (Rich text preferred)

## Quick tests
```bash
source .venv/bin/activate

# 1) Notion auth
python skills/notion-pm/notion-client.py ping

# 2) Research client
python skills/notion-pm/research_client.py "best AI tools for PM roadmap planning" --max-results 3

# 3) Ingest task with due date
python skills/notion-pm/run_ingest.py --message "task: ship onboarding copy by tomorrow high" --chat=-100123 --message-id=1 --source=telegram

# 4) Missing due date flow
python skills/notion-pm/run_ingest.py --message "task: research competitor pricing" --chat=-100123 --message-id=2 --source=telegram
python skills/notion-pm/run_ingest.py --message "next friday" --chat=-100123 --message-id=3 --source=telegram
```

## Notes
- Set `RESEARCH_CONFIDENCE_THRESHOLD` to control when research runs.
- If `OPENAI_API_KEY` is missing, summaries fall back to Tavily output.
