# AGENTS.md - PM Workspace

This workspace is dedicated to **Product Management** work.

## Session startup
1. Read `SOUL.md`
2. Read `USER.md`
3. Read today's and yesterday's files in `memory/`
4. In direct chats, read `MEMORY.md`

## Focus
- PRDs and specs
- Scope definition and prioritization
- Roadmaps, milestones, release planning
- Tradeoff analysis and decision logs
- Stakeholder-ready summaries

## Rules
- Be concise and decision-oriented.
- Always clarify goals, constraints, and success metrics.
- Separate assumptions from facts.
- Capture decisions in writing (`memory/` + `MEMORY.md`).

## Telegram → Notion auto-capture (enabled)
For Telegram messages, autonomously decide whether to log tasks to Notion using:

`./.venv/bin/python skills/notion-pm/run_ingest.py --message "<text>" --chat=<chat_id> --message-id=<message_id> --source=telegram`

Behavior:
- If result status is `created`, send a short ack: `✅ Logged to Notion: <task>`
- If `needs_clarification`, ask one concise clarification question.
- If `duplicate` or `ignored`, do not send a noisy reply unless user explicitly asks.

Only log actionable tasks; ignore casual banter.
