# notion-pm

Notion integration module for the `pm` agent.

## Final schema expected in Notion

- `Task Name` (Title)
- `Message` (Rich text)
- `Status` (Select: `New`, `In Progress`, `Done`)
- `Received At` (Date)
- `Dedup Key` (Rich text)
- `Priority` (Select: `High`, `Medium`, `Low`)

## Environment

Set these in `~/.openclaw/workspace-pm/.env`:

```env
NOTION_API_KEY=ntn_xxx
NOTION_DATABASE_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
NOTION_SOURCE=telegram
DEFAULT_STATUS=New
DEFAULT_PRIORITY=Medium
```

## Install (inside venv)

```bash
cd ~/.openclaw/workspace-pm
source .venv/bin/activate
pip install notion-client python-dotenv
```

## Smoke tests

### 1) Auth test

```bash
python skills/notion-pm/notion-client.py ping
```

### 2) Create from message

```bash
python skills/notion-pm/notion-client.py create \
  --message "Book dentist appointment next week" \
  --chat "-1001234567890" \
  --message-id "42" \
  --source "telegram"
```

### 3) Verify dedupe

Run the same `create` command again; it should return:

```text
{'ok': True, 'created': False, 'reason': 'duplicate', ...}
```

### 4) Find by dedupe key

```bash
python skills/notion-pm/notion-client.py find telegram:-1001234567890:42
```

### 5) Update status

```bash
python skills/notion-pm/notion-client.py update-status --page-id <PAGE_ID> --status "Done"
```

## How PM agent should call this

In your inbound message handling flow:

1. Build `dedup_key = <source>:<chat>:<message_id>`
2. Call `find_by_dedup_key`
3. If no row exists, call `create_task_from_message`
4. Later, call `update_task_status` when task progresses

This gives you reliable capture + dedupe + lifecycle updates.
