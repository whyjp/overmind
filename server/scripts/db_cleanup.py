#!/usr/bin/env python3
"""Overmind JSONL store cleanup utility.

Usage:
    python scripts/db_cleanup.py status                     # Show store stats
    python scripts/db_cleanup.py ttl [--days 14]            # Remove events older than N days
    python scripts/db_cleanup.py purge-repo <repo_id>       # Delete all data for a repo
    python scripts/db_cleanup.py purge-user <repo_id> <user> # Delete all events by a user in a repo
    python scripts/db_cleanup.py purge-all                  # Wipe entire data directory
    python scripts/db_cleanup.py compact                    # Remove empty files and rebuild
    python scripts/db_cleanup.py export <repo_id> [--out FILE] # Export repo events as JSONL
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _safe_repo_id(repo_id: str) -> str:
    return repo_id.replace("/", "_").replace(":", "_")


def _repo_dir(repo_id: str) -> Path:
    return DATA_DIR / "repos" / _safe_repo_id(repo_id)


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _iter_jsonl_files(base: Path):
    """Yield all .jsonl files under base."""
    if not base.exists():
        return
    yield from base.rglob("*.jsonl")


def _read_events(jsonl_file: Path) -> list[dict]:
    events = []
    for line in jsonl_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _write_events(jsonl_file: Path, events: list[dict]) -> None:
    if not events:
        jsonl_file.unlink(missing_ok=True)
        return
    jsonl_file.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
        encoding="utf-8",
    )


# ── Commands ──────────────────────────────────────────────────────────


def cmd_status(args: argparse.Namespace) -> None:
    repos_dir = DATA_DIR / "repos"
    if not repos_dir.exists():
        print("No data found.")
        return

    total_events = 0
    total_files = 0
    total_bytes = 0

    for repo_dir in sorted(repos_dir.iterdir()):
        if not repo_dir.is_dir():
            continue
        repo_events = 0
        repo_bytes = 0
        repo_files = 0
        users = set()
        oldest_ts = None
        newest_ts = None

        for f in _iter_jsonl_files(repo_dir / "events"):
            repo_files += 1
            repo_bytes += f.stat().st_size
            # extract user from path: events/{user}/YYYY-MM-DD.jsonl
            users.add(f.parent.name)
            for evt in _read_events(f):
                repo_events += 1
                ts = evt.get("ts", "")
                if ts:
                    if oldest_ts is None or ts < oldest_ts:
                        oldest_ts = ts
                    if newest_ts is None or ts > newest_ts:
                        newest_ts = ts

        total_events += repo_events
        total_files += repo_files
        total_bytes += repo_bytes

        print(f"  repo: {repo_dir.name}")
        print(f"    events: {repo_events}  files: {repo_files}  size: {repo_bytes / 1024:.1f} KB")
        print(f"    users: {', '.join(sorted(users)) or '(none)'}")
        if oldest_ts:
            print(f"    range: {oldest_ts[:19]} ~ {newest_ts[:19]}")
        print()

    print(f"Total: {total_events} events, {total_files} files, {total_bytes / 1024:.1f} KB")


def cmd_ttl(args: argparse.Namespace) -> None:
    days = args.days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    removed = 0
    kept = 0

    repos_dir = DATA_DIR / "repos"
    if not repos_dir.exists():
        print("No data found.")
        return

    for f in _iter_jsonl_files(repos_dir):
        events = _read_events(f)
        before = len(events)
        events = [e for e in events if _parse_ts(e["ts"]) >= cutoff]
        after = len(events)
        removed += before - after
        kept += after
        _write_events(f, events)

    print(f"TTL cleanup (>{days} days): removed {removed}, kept {kept}")


def cmd_purge_repo(args: argparse.Namespace) -> None:
    repo_id = args.repo_id
    rd = _repo_dir(repo_id)
    if not rd.exists():
        print(f"Repo not found: {repo_id}")
        return

    # count before delete
    count = sum(len(_read_events(f)) for f in _iter_jsonl_files(rd / "events"))
    shutil.rmtree(rd)
    print(f"Purged repo '{repo_id}': {count} events deleted")


def cmd_purge_user(args: argparse.Namespace) -> None:
    repo_id = args.repo_id
    user = args.user
    user_dir = _repo_dir(repo_id) / "events" / user
    if not user_dir.exists():
        print(f"User '{user}' not found in repo '{repo_id}'")
        return

    count = sum(len(_read_events(f)) for f in _iter_jsonl_files(user_dir))
    shutil.rmtree(user_dir)
    print(f"Purged user '{user}' from repo '{repo_id}': {count} events deleted")


def cmd_purge_all(args: argparse.Namespace) -> None:
    if not args.yes:
        confirm = input("This will delete ALL Overmind data. Type 'yes' to confirm: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            return

    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
        DATA_DIR.mkdir(parents=True)
        print("All data purged.")
    else:
        print("No data found.")


def cmd_compact(args: argparse.Namespace) -> None:
    repos_dir = DATA_DIR / "repos"
    if not repos_dir.exists():
        print("No data found.")
        return

    removed_files = 0
    removed_dirs = 0
    deduped = 0

    for f in list(_iter_jsonl_files(repos_dir)):
        events = _read_events(f)
        if not events:
            f.unlink()
            removed_files += 1
            continue

        # deduplicate by id
        seen = set()
        unique = []
        for e in events:
            eid = e.get("id", "")
            if eid not in seen:
                seen.add(eid)
                unique.append(e)
            else:
                deduped += 1
        _write_events(f, unique)

    # remove empty directories
    for d in sorted(repos_dir.rglob("*"), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            removed_dirs += 1

    print(f"Compact: removed {removed_files} empty files, {removed_dirs} empty dirs, deduped {deduped} events")


def cmd_export(args: argparse.Namespace) -> None:
    repo_id = args.repo_id
    rd = _repo_dir(repo_id)
    if not rd.exists():
        print(f"Repo not found: {repo_id}", file=sys.stderr)
        sys.exit(1)

    events = []
    for f in _iter_jsonl_files(rd / "events"):
        events.extend(_read_events(f))

    events.sort(key=lambda e: e.get("ts", ""))

    out = sys.stdout
    if args.out:
        out = open(args.out, "w", encoding="utf-8")

    for e in events:
        out.write(json.dumps(e, ensure_ascii=False) + "\n")

    if args.out:
        out.close()
        print(f"Exported {len(events)} events to {args.out}", file=sys.stderr)
    else:
        print(f"# {len(events)} events exported", file=sys.stderr)


# ── CLI ───────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Overmind JSONL store cleanup utility")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show store stats")

    p_ttl = sub.add_parser("ttl", help="Remove events older than N days")
    p_ttl.add_argument("--days", type=int, default=14, help="TTL in days (default: 14)")

    p_repo = sub.add_parser("purge-repo", help="Delete all data for a repo")
    p_repo.add_argument("repo_id", help="e.g. github.com/user/project")

    p_user = sub.add_parser("purge-user", help="Delete all events by a user in a repo")
    p_user.add_argument("repo_id")
    p_user.add_argument("user")

    p_all = sub.add_parser("purge-all", help="Wipe entire data directory")
    p_all.add_argument("--yes", action="store_true", help="Skip confirmation")

    sub.add_parser("compact", help="Remove empty files, deduplicate events")

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
        "compact": cmd_compact,
        "export": cmd_export,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
