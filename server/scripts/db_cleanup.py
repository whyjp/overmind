#!/usr/bin/env python3
"""Overmind SQLite store management utility.

Usage:
    python scripts/db_cleanup.py status                      # Show store stats
    python scripts/db_cleanup.py ttl [--days 14]             # Remove events older than N days
    python scripts/db_cleanup.py purge-repo <repo_id>        # Delete all data for a repo
    python scripts/db_cleanup.py purge-user <repo_id> <user> # Delete all events by a user in a repo
    python scripts/db_cleanup.py purge-all                   # Delete database file
    python scripts/db_cleanup.py vacuum                      # Reclaim disk space
    python scripts/db_cleanup.py export <repo_id> [--out FILE] # Export repo events as JSONL
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "overmind.db"


def _get_db_path(args: argparse.Namespace) -> Path:
    return Path(args.db) if args.db else DEFAULT_DB


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def cmd_status(args: argparse.Namespace) -> None:
    db_path = _get_db_path(args)
    if not db_path.exists():
        print("No database found.")
        return

    conn = _connect(db_path)
    print(f"Database: {db_path} ({db_path.stat().st_size / 1024:.1f} KB)\n")

    cursor = conn.execute(
        """SELECT repo_id, COUNT(*) as cnt, COUNT(DISTINCT user) as users,
                  MIN(ts) as oldest, MAX(ts) as newest
           FROM events GROUP BY repo_id ORDER BY repo_id"""
    )
    total_events = 0
    for row in cursor:
        cnt = row["cnt"]
        total_events += cnt
        print(f"  repo: {row['repo_id']}")
        print(f"    events: {cnt}  users: {row['users']}")
        if row["oldest"]:
            print(f"    range: {row['oldest'][:19]} ~ {row['newest'][:19]}")
        print()

    pull_count = conn.execute("SELECT COUNT(*) FROM pull_log").fetchone()[0]
    print(f"Total: {total_events} events, {pull_count} pull log entries")
    conn.close()


def cmd_ttl(args: argparse.Namespace) -> None:
    db_path = _get_db_path(args)
    conn = _connect(db_path)

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    cutoff_iso = cutoff.isoformat()

    count_before = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.execute("DELETE FROM events WHERE ts < ?", (cutoff_iso,))
    conn.commit()
    count_after = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    removed = count_before - count_after
    print(f"TTL cleanup (>{args.days} days): removed {removed}, kept {count_after}")
    conn.close()


def cmd_purge_repo(args: argparse.Namespace) -> None:
    db_path = _get_db_path(args)
    conn = _connect(db_path)

    count = conn.execute(
        "SELECT COUNT(*) FROM events WHERE repo_id = ?", (args.repo_id,)
    ).fetchone()[0]

    if count == 0:
        print(f"Repo not found: {args.repo_id}")
        conn.close()
        return

    conn.execute("DELETE FROM events WHERE repo_id = ?", (args.repo_id,))
    conn.execute("DELETE FROM pull_log WHERE repo_id = ?", (args.repo_id,))
    conn.execute("DELETE FROM feedback WHERE repo_id = ?", (args.repo_id,))
    conn.commit()
    print(f"Purged repo '{args.repo_id}': {count} events deleted")
    conn.close()


def cmd_purge_user(args: argparse.Namespace) -> None:
    db_path = _get_db_path(args)
    conn = _connect(db_path)

    count = conn.execute(
        "SELECT COUNT(*) FROM events WHERE repo_id = ? AND user = ?",
        (args.repo_id, args.user),
    ).fetchone()[0]

    if count == 0:
        print(f"User '{args.user}' not found in repo '{args.repo_id}'")
        conn.close()
        return

    conn.execute(
        "DELETE FROM events WHERE repo_id = ? AND user = ?",
        (args.repo_id, args.user),
    )
    conn.commit()
    print(f"Purged user '{args.user}' from repo '{args.repo_id}': {count} events deleted")
    conn.close()


def cmd_purge_all(args: argparse.Namespace) -> None:
    db_path = _get_db_path(args)
    if not db_path.exists():
        print("No database found.")
        return

    if not args.yes:
        confirm = input("This will delete the entire Overmind database. Type 'yes' to confirm: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            return

    db_path.unlink()
    print("Database deleted.")


def cmd_vacuum(args: argparse.Namespace) -> None:
    db_path = _get_db_path(args)
    conn = _connect(db_path)

    size_before = db_path.stat().st_size
    conn.execute("VACUUM")
    conn.close()
    size_after = db_path.stat().st_size

    saved = size_before - size_after
    print(f"Vacuum complete: {size_before / 1024:.1f} KB → {size_after / 1024:.1f} KB (saved {saved / 1024:.1f} KB)")


def cmd_export(args: argparse.Namespace) -> None:
    db_path = _get_db_path(args)
    conn = _connect(db_path)

    cursor = conn.execute(
        "SELECT * FROM events WHERE repo_id = ? ORDER BY ts",
        (args.repo_id,),
    )
    rows = cursor.fetchall()

    if not rows:
        print(f"Repo not found: {args.repo_id}", file=sys.stderr)
        conn.close()
        sys.exit(1)

    out = sys.stdout
    if args.out:
        out = open(args.out, "w", encoding="utf-8")

    for row in rows:
        event = {
            "id": row["id"],
            "repo_id": row["repo_id"],
            "user": row["user"],
            "ts": row["ts"],
            "type": row["type"],
            "result": row["result"],
            "prompt": row["prompt"],
            "files": json.loads(row["files"]) if row["files"] else [],
            "process": json.loads(row["process"]) if row["process"] else [],
            "priority": row["priority"],
            "scope": row["scope"],
            "summary": row["summary"],
            "prevented_count": row["prevented_count"],
        }
        out.write(json.dumps(event, ensure_ascii=False) + "\n")

    if args.out:
        out.close()
        print(f"Exported {len(rows)} events to {args.out}", file=sys.stderr)
    else:
        print(f"# {len(rows)} events exported", file=sys.stderr)

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Overmind SQLite store management utility")
    parser.add_argument("--db", help=f"Database path (default: {DEFAULT_DB})")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show store stats")

    p_ttl = sub.add_parser("ttl", help="Remove events older than N days")
    p_ttl.add_argument("--days", type=int, default=14, help="TTL in days (default: 14)")

    p_repo = sub.add_parser("purge-repo", help="Delete all data for a repo")
    p_repo.add_argument("repo_id", help="e.g. github.com/user/project")

    p_user = sub.add_parser("purge-user", help="Delete all events by a user in a repo")
    p_user.add_argument("repo_id")
    p_user.add_argument("user")

    p_all = sub.add_parser("purge-all", help="Delete database file")
    p_all.add_argument("--yes", action="store_true", help="Skip confirmation")

    sub.add_parser("vacuum", help="Reclaim disk space (SQLite VACUUM)")

    p_export = sub.add_parser("export", help="Export repo events as JSONL")
    p_export.add_argument("repo_id")
    p_export.add_argument("--out", help="Output file (default: stdout)")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "status": cmd_status,
        "ttl": cmd_ttl,
        "purge-repo": cmd_purge_repo,
        "purge-user": cmd_purge_user,
        "purge-all": cmd_purge_all,
        "vacuum": cmd_vacuum,
        "export": cmd_export,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
