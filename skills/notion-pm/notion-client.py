#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import os
from typing import Any, Dict, Optional

from notion_client import Client

try:
    from dotenv import load_dotenv

    WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    load_dotenv(os.path.join(WORKSPACE_ROOT, ".env"))
except Exception:
    WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    env_path = os.path.join(WORKSPACE_ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_SOURCE = os.getenv("NOTION_SOURCE", "telegram")
NOTION_DATA_SOURCE_ID = os.getenv("NOTION_DATA_SOURCE_ID")
DEFAULT_STATUS = os.getenv("DEFAULT_STATUS", "New")
DEFAULT_PRIORITY = os.getenv("DEFAULT_PRIORITY", "Medium")

VALID_STATUS = {"New", "In Progress", "Done"}
VALID_PRIORITY = {"High", "Medium", "Low"}

if not NOTION_API_KEY:
    raise RuntimeError("Missing NOTION_API_KEY")
if not NOTION_DATABASE_ID:
    raise RuntimeError("Missing NOTION_DATABASE_ID")

notion = Client(auth=NOTION_API_KEY)


def today_iso() -> str:
    return dt.datetime.now(dt.UTC).date().isoformat()


def truncate_title(text: str, max_len: int = 80) -> str:
    clean = (text or "").strip().replace("\n", " ")
    return clean[:max_len] if clean else "(no message)"


def make_dedup_key(source: str, chat_or_thread: str, message_id: str) -> str:
    return f"{source}:{chat_or_thread}:{message_id}"


def resolve_data_source_id() -> str:
    if NOTION_DATA_SOURCE_ID:
        return NOTION_DATA_SOURCE_ID

    db = notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
    linked = db.get("data_sources") or []
    if linked and isinstance(linked, list) and linked[0].get("id"):
        return linked[0]["id"]

    return NOTION_DATABASE_ID


def get_database_properties() -> Dict[str, Any]:
    # Notion 2025 API exposes schema on data_sources
    try:
        ds = notion.data_sources.retrieve(data_source_id=resolve_data_source_id())
        return ds.get("properties") or {}
    except Exception:
        db = notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
        return db.get("properties") or {}


def notion_filter_by_dedup_key(dedup_key: str) -> Dict[str, Any]:
    return {"property": "Dedup Key", "rich_text": {"equals": dedup_key}}


def find_by_dedup_key(dedup_key: str) -> Optional[Dict[str, Any]]:
    resp = notion.data_sources.query(
        data_source_id=resolve_data_source_id(),
        filter=notion_filter_by_dedup_key(dedup_key),
        page_size=1,
    )
    results = resp.get("results", [])
    return results[0] if results else None


def create_task_from_message(
    *,
    message: str,
    dedup_key: str,
    due_date: str,
    task_name: Optional[str] = None,
    research_summary: Optional[str] = None,
    research_links: Optional[str] = None,
    received_at: Optional[str] = None,
    status: str = DEFAULT_STATUS,
    priority: str = DEFAULT_PRIORITY,
) -> Dict[str, Any]:
    if status not in VALID_STATUS:
        raise ValueError(f"Invalid status: {status}")
    if priority not in VALID_PRIORITY:
        raise ValueError(f"Invalid priority: {priority}")
    if not due_date:
        raise ValueError("Missing required due_date")

    # validate ISO date
    try:
        dt.date.fromisoformat(due_date[:10])
    except Exception as e:
        raise ValueError(f"Invalid due_date (expected YYYY-MM-DD): {due_date}") from e

    if find_by_dedup_key(dedup_key):
        return {"ok": True, "created": False, "reason": "duplicate"}

    title = truncate_title(task_name or message)
    date_value = (received_at or today_iso())[:10]

    properties = {
        "Task Name": {"title": [{"text": {"content": title}}]},
        "Message": {"rich_text": [{"text": {"content": message}}]},
        "Status": {"select": {"name": status}},
        "Received At": {"date": {"start": date_value}},
        "Due Date": {"date": {"start": due_date[:10]}},
        "Dedup Key": {"rich_text": [{"text": {"content": dedup_key}}]},
        "Priority": {"select": {"name": priority}},
    }

    # Optional research fields with schema-aware types
    try:
        prop_schema = get_database_properties()
    except Exception:
        prop_schema = {}

    if research_summary and "Research Summary" in prop_schema:
        ptype = (prop_schema.get("Research Summary") or {}).get("type")
        if ptype == "rich_text":
            properties["Research Summary"] = {"rich_text": [{"text": {"content": research_summary[:1800]}}]}
        elif ptype == "url":
            first_url = research_summary.splitlines()[0].strip()
            properties["Research Summary"] = {"url": first_url[:2000]}

    if research_links and "Research Links" in prop_schema:
        ptype = (prop_schema.get("Research Links") or {}).get("type")
        if ptype == "rich_text":
            properties["Research Links"] = {"rich_text": [{"text": {"content": research_links[:1800]}}]}
        elif ptype == "url":
            first = next((ln.strip() for ln in research_links.splitlines() if ln.strip()), None)
            if first:
                properties["Research Links"] = {"url": first[:2000]}

    page = notion.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties=properties,
    )
    return {"ok": True, "created": True, "page_id": page["id"]}


def update_task_status(page_id: str, status: str) -> Dict[str, Any]:
    if status not in VALID_STATUS:
        raise ValueError(f"Invalid status: {status}")

    notion.pages.update(page_id=page_id, properties={"Status": {"select": {"name": status}}})
    return {"ok": True, "updated": True, "page_id": page_id, "status": status}


def ping() -> Dict[str, Any]:
    resp = notion.search(page_size=1)
    return {"ok": True, "search_results": len(resp.get("results", []))}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Notion PM connector")
    sp = p.add_subparsers(dest="cmd", required=True)

    sp.add_parser("ping", help="Verify Notion auth works")

    f = sp.add_parser("find", help="Find a row by Dedup Key")
    f.add_argument("dedup_key")

    c = sp.add_parser("create", help="Create row from message")
    c.add_argument("--message", required=True)
    c.add_argument("--source", default=NOTION_SOURCE)
    c.add_argument("--chat", required=True)
    c.add_argument("--message-id", required=True)
    c.add_argument("--due-date", required=True)
    c.add_argument("--task-name")
    c.add_argument("--research-summary")
    c.add_argument("--research-links")
    c.add_argument("--priority", default=DEFAULT_PRIORITY)
    c.add_argument("--status", default=DEFAULT_STATUS)
    c.add_argument("--received-at", default=today_iso())

    u = sp.add_parser("update-status", help="Update Status by page id")
    u.add_argument("--page-id", required=True)
    u.add_argument("--status", required=True)

    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.cmd == "ping":
        print(ping())
        return

    if args.cmd == "find":
        row = find_by_dedup_key(args.dedup_key)
        print({"found": bool(row), "page_id": row["id"] if row else None})
        return

    if args.cmd == "create":
        dedup_key = make_dedup_key(args.source, args.chat, args.message_id)
        out = create_task_from_message(
            message=args.message,
            dedup_key=dedup_key,
            due_date=args.due_date,
            task_name=args.task_name,
            research_summary=args.research_summary,
            research_links=args.research_links,
            received_at=args.received_at,
            priority=args.priority,
            status=args.status,
        )
        out["dedup_key"] = dedup_key
        print(out)
        return

    if args.cmd == "update-status":
        print(update_task_status(args.page_id, args.status))
        return


if __name__ == "__main__":
    main()
