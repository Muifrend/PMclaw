# TOOLS.md

Local notes for PM workflows:
- Product repos
- Analytics sources
- Issue tracker links
- Release calendars

## Notion PM integration (active)

Environment
- `.env` (workspace root) must define:
  - `NOTION_API_KEY`
  - `NOTION_DATABASE_ID`
  - `NOTION_SOURCE=telegram`
  - `DEFAULT_STATUS=New`
  - `DEFAULT_PRIORITY=Medium`

Python runtime
- Use the workspace venv for all Notion commands:
  - `./.venv/bin/python`

Core scripts
- Notion client CRUD: `skills/notion-pm/notion-client.py`
- Autonomous decision handler: `skills/notion-pm/pm_handler.py`
- Ingest wrapper (entrypoint): `skills/notion-pm/run_ingest.py`

Schema expectations (required)
- `Task Name` (Title)
- `Message` (Rich text)
- `Status` (Select: `New`, `In Progress`, `Done`)
- `Received At` (Date)
- `Due Date` (Date)  ← required for creation
- `Dedup Key` (Rich text)
- `Priority` (Select: `High`, `Medium`, `Low`)

Due date policy
- Task-like messages without a parseable due date must return `needs_due_date` and ask:
  - `Got it — what’s the due date? (YYYY-MM-DD or 'tomorrow')`
- No Notion write should occur until due date is known.

Supported due date inputs
- `YYYY-MM-DD`
- `today`, `tomorrow`
- `in N days` (e.g. `in 3 days`)
- `this friday`, `next monday`
- bare weekday: `monday`, `friday`
- month name forms: `march 15`, `mar 15`, `march 15 2027`

Pending clarification state
- Stored at: `skills/notion-pm/.state/pending.json`
- Keyed by chat id
- Used to complete task creation when user sends follow-up date

Statuses returned by `run_ingest.py`
- `created` → task stored in Notion
- `duplicate` → dedupe hit (already stored)
- `needs_due_date` → ask user for date
- `ignored` → no task action
- `error` → processing failure

Smoke tests
- Auth:
  - `./.venv/bin/python skills/notion-pm/notion-client.py ping`
- Due-date-required path:
  - `./.venv/bin/python skills/notion-pm/run_ingest.py --message "task: prep roadmap" --chat=-100123 --message-id=900 --source=telegram`
  - `./.venv/bin/python skills/notion-pm/run_ingest.py --message "tomorrow" --chat=-100123 --message-id=901 --source=telegram --dry-run`
- Natural date parse:
  - `./.venv/bin/python skills/notion-pm/pm_handler.py decide --message "task: submit report in 3 days"`
  - `./.venv/bin/python skills/notion-pm/pm_handler.py decide --message "task: review deck next friday"`

## Tavily research enrichment (active)

Environment
- `.env` must include:
  - `TAVILY_API_KEY`

Behavior
- Tasks classified as `researchable` trigger Tavily search before Notion write.
- Current triggers include terms like: `research`, `compare`, `best`, `options`, `benchmark`, `evaluate`.
- If due date is missing, agent asks for due date first; research runs after due date is resolved.

Optional Notion fields (if present, auto-filled)
- `Research Summary` (Rich text)
- `Research Links` (Rich text)

Smoke tests
- `./.venv/bin/python skills/notion-pm/research_client.py "best kanban tools" --max-results 2`
- `./.venv/bin/python skills/notion-pm/run_ingest.py --message "task: research competitor pricing by tomorrow" --chat=-100123 --message-id=9991 --source=telegram`

## LLM paragraph summarization for research

When a task is `researchable`, Tavily runs first. If `OPENAI_API_KEY` is set, research summary is rewritten into one coherent paragraph.

Env vars
- `OPENAI_API_KEY` (required for LLM paragraph summarization)
- `OPENAI_MODEL` (optional, default: `gpt-4o-mini`)
- `RESEARCH_CONFIDENCE_THRESHOLD` (optional, default: `0.8`)

Behavior
- LLM summary runs only when:
  - task_type is `researchable`
  - confidence >= `RESEARCH_CONFIDENCE_THRESHOLD`
- If LLM fails or key missing, system falls back to Tavily answer/title summary.
- Debug fields in runtime result:
  - `llm_used` (true/false)
  - `llm_model`
  - `llm_error`
