#!/usr/bin/env python3
"""
Mastodon filter sync script.
Reads filter definitions from the filters/ directory and syncs them to a Mastodon account via the v2 Filters API.

Usage:
    python sync.py [--prune] [--dry-run]

    --prune    Delete Mastodon filters that have no matching file
    --dry-run  Print planned changes without making any API calls

Environment variables:
    MASTODON_BASE_URL      e.g. https://mastodon.social
    MASTODON_ACCESS_TOKEN  OAuth token with read:filters + write:filters scope
"""

import os
import sys
import argparse
from pathlib import Path

import yaml
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("MASTODON_BASE_URL", "").rstrip("/")
ACCESS_TOKEN = os.environ.get("MASTODON_ACCESS_TOKEN", "")
FILTERS_DIR = Path(__file__).parent / "filters"

# Mastodon v2 accepts these context values
VALID_CONTEXTS = {"home", "notifications", "public", "thread", "account"}

# Friendly aliases accepted in filter files
CONTEXT_ALIASES = {
    "lists": "home", # home feed includes lists
    "conversations": "thread",
    "profiles": "account",
    "direct": "thread",
}

VALID_ACTIONS = {"warn", "hide"}


# ---------------------------------------------------------------------------
# File parsing
# ---------------------------------------------------------------------------

def parse_filter_file(path: Path) -> dict:
    """
    Parse a filter .md file with YAML frontmatter.

    Frontmatter keys:
        name        (required) Display name of the filter
        contexts    List of: home, notifications, public, thread/conversations,
                    account/profiles  (default: [home])
        action      warn | hide  (default: warn)
        whole_word  true | false — default for all keywords (default: false)

    Body:
        One keyword per line.
        Append  [w]  to force whole_word ON  for that line.
        Append  [!w] to force whole_word OFF for that line.
        Lines starting with # are comments and are ignored.
    """
    text = path.read_text(encoding="utf-8")

    if not text.startswith("---"):
        raise ValueError(f"{path.name}: file must start with a YAML frontmatter block (---)")

    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{path.name}: could not find closing --- for frontmatter")

    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"{path.name}: invalid YAML frontmatter — {e}")

    if "name" not in fm:
        raise ValueError(f"{path.name}: frontmatter must include 'name'")

    # Resolve contexts
    raw_contexts = fm.get("contexts", ["home"])
    if isinstance(raw_contexts, str):
        raw_contexts = [raw_contexts]
    contexts = []
    for ctx in raw_contexts:
        ctx = str(ctx).lower().strip()
        ctx = CONTEXT_ALIASES.get(ctx, ctx)
        if ctx not in VALID_CONTEXTS:
            print(f"  WARNING {path.name}: unknown context '{ctx}', skipping")
            continue
        if ctx not in contexts:
            contexts.append(ctx)
    if not contexts:
        contexts = ["home"]

    # Resolve action
    action = str(fm.get("action", "warn")).lower().strip()
    if action not in VALID_ACTIONS:
        print(f"  WARNING {path.name}: unknown action '{action}', defaulting to 'warn'")
        action = "warn"

    # Default whole_word for this filter
    default_whole_word = bool(fm.get("whole_word", False))

    # Parse keywords from the body
    keywords = []
    for line in parts[2].splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        whole_word = default_whole_word

        if line.endswith(" [w]"):
            line = line[:-4].strip()
            whole_word = True
        elif line.endswith(" [!w]"):
            line = line[:-5].strip()
            whole_word = False

        if line:
            keywords.append({"keyword": line, "whole_word": whole_word})

    return {
        "title": fm["name"],
        "context": contexts,
        "filter_action": action,
        "keywords": keywords,
        "_source": path.name,
    }


def load_all_filters() -> list[dict]:
    filters = []
    for path in sorted(FILTERS_DIR.glob("*.md")):
        try:
            f = parse_filter_file(path)
            filters.append(f)
            print(f"  Loaded: {path.name}  ({f['title']}, {len(f['keywords'])} keyword(s))")
        except ValueError as e:
            print(f"  ERROR loading {path.name}: {e}")
            sys.exit(1)
    return filters


# ---------------------------------------------------------------------------
# Mastodon API helpers
# ---------------------------------------------------------------------------

def _headers() -> dict:
    return {"Authorization": f"Bearer {ACCESS_TOKEN}"}


def api_get(path: str) -> list | dict:
    r = requests.get(f"{BASE_URL}{path}", headers=_headers(), timeout=15)
    r.raise_for_status()
    return r.json()


def api_post(path: str, data: list[tuple]) -> dict:
    r = requests.post(f"{BASE_URL}{path}", headers=_headers(), data=data, timeout=15)
    r.raise_for_status()
    return r.json()


def api_put(path: str, data: list[tuple]) -> dict:
    r = requests.put(f"{BASE_URL}{path}", headers=_headers(), data=data, timeout=15)
    r.raise_for_status()
    return r.json()


def api_delete(path: str) -> None:
    r = requests.delete(f"{BASE_URL}{path}", headers=_headers(), timeout=15)
    r.raise_for_status()


def filter_payload(f: dict) -> list[tuple]:
    """Build the form-encoded payload for create/update filter calls."""
    data = [
        ("title", f["title"]),
        ("filter_action", f["filter_action"]),
    ]
    for ctx in f["context"]:
        data.append(("context[]", ctx))
    # Omitting expires_in → never expires
    return data


def keyword_payload(kw: dict) -> list[tuple]:
    return [
        ("keyword", kw["keyword"]),
        ("whole_word", "true" if kw["whole_word"] else "false"),
    ]


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------

def sync_keywords(filter_id: str, desired: list[dict], dry_run: bool) -> None:
    existing = api_get(f"/api/v2/filters/{filter_id}/keywords")
    # Build lookup: keyword text → {id, whole_word}
    existing_map = {kw["keyword"]: kw for kw in existing}
    desired_map = {kw["keyword"]: kw for kw in desired}

    # Add or update
    for text, kw in desired_map.items():
        if text not in existing_map:
            print(f"      + keyword: '{text}' (whole_word={kw['whole_word']})")
            if not dry_run:
                api_post(f"/api/v2/filters/{filter_id}/keywords", keyword_payload(kw))
        else:
            existing_kw = existing_map[text]
            if existing_kw["whole_word"] != kw["whole_word"]:
                print(f"      ~ keyword: '{text}' whole_word {existing_kw['whole_word']} → {kw['whole_word']}")
                if not dry_run:
                    api_put(f"/api/v2/filters/keywords/{existing_kw['id']}", keyword_payload(kw))

    # Remove keywords no longer in the file
    for text, existing_kw in existing_map.items():
        if text not in desired_map:
            print(f"      - keyword: '{text}'")
            if not dry_run:
                api_delete(f"/api/v2/filters/keywords/{existing_kw['id']}")


def sync_filters(desired: list[dict], prune: bool, dry_run: bool) -> None:
    existing = api_get("/api/v2/filters")
    # Build lookup: title → filter object
    existing_map = {f["title"]: f for f in existing}
    desired_titles = {f["title"] for f in desired}

    for f in desired:
        title = f["title"]
        if title in existing_map:
            ex = existing_map[title]
            # Check if the filter-level fields need updating
            needs_update = (
                set(ex["context"]) != set(f["context"])
                or ex["filter_action"] != f["filter_action"]
            )
            if needs_update:
                print(f"  ~ Update filter: '{title}'")
                if not dry_run:
                    api_put(f"/api/v2/filters/{ex['id']}", filter_payload(f))
            else:
                print(f"  = Filter up to date: '{title}'")
            print(f"    Syncing keywords...")
            sync_keywords(ex["id"], f["keywords"], dry_run)
        else:
            print(f"  + Create filter: '{title}'")
            if not dry_run:
                created = api_post("/api/v2/filters", filter_payload(f))
                print(f"    Syncing keywords...")
                sync_keywords(created["id"], f["keywords"], dry_run)
            else:
                for kw in f["keywords"]:
                    print(f"      + keyword: '{kw['keyword']}' (whole_word={kw['whole_word']})")

    if prune:
        for title, ex in existing_map.items():
            if title not in desired_titles:
                print(f"  - Prune filter: '{title}' (no matching file)")
                if not dry_run:
                    api_delete(f"/api/v2/filters/{ex['id']}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Sync Mastodon filters from files")
    parser.add_argument("--prune", action="store_true",
                        help="Delete Mastodon filters with no matching file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print changes without calling the API")
    args = parser.parse_args()

    if not BASE_URL:
        print("ERROR: MASTODON_BASE_URL is not set")
        sys.exit(1)
    if not ACCESS_TOKEN:
        print("ERROR: MASTODON_ACCESS_TOKEN is not set")
        sys.exit(1)
    if not FILTERS_DIR.is_dir():
        print(f"ERROR: filters directory not found at {FILTERS_DIR}")
        sys.exit(1)

    if args.dry_run:
        print("=== DRY RUN — no changes will be made ===\n")

    print("Loading filter files...")
    desired = load_all_filters()
    if not desired:
        print("No filter files found, nothing to do.")
        sys.exit(0)

    print(f"\nSyncing {len(desired)} filter(s) to {BASE_URL}...\n")
    sync_filters(desired, prune=args.prune, dry_run=args.dry_run)

    print("\nDone.")


if __name__ == "__main__":
    main()