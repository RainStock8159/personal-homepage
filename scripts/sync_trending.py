"""
sync_trending.py
Fetches trending AI/finance repos from GitHub and upserts them into Supabase.

Usage:
    python scripts/sync_trending.py

Required env vars (or .env file):
    SUPABASE_URL  - e.g. https://xxxx.supabase.co
    SUPABASE_KEY  - service-role secret key
    GH_TOKEN      - GitHub personal access token (raises rate limit to 5000/hr)
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL: str = os.environ["SUPABASE_URL"]
SUPABASE_KEY: str = os.environ["SUPABASE_KEY"]
GH_TOKEN: str = os.environ.get("GH_TOKEN", "")

# GitHub Search queries to run
QUERIES: list[str] = [
    "topic:finance topic:ai",
    "topic:llm topic:finance",
    "topic:fintech topic:llm",
    "topic:ai-tools",
]

MIN_STARS = 50
# Only repos pushed within the last 30 days
SINCE_DATE = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
PER_PAGE = 100  # GitHub max
TABLE = "ai_public_projects"


# ---------------------------------------------------------------------------
# Category / type inference
# ---------------------------------------------------------------------------

_CATEGORY_MAP: dict[str, str] = {
    "llm": "LLM",
    "large-language-model": "LLM",
    "finance": "Finance",
    "fintech": "FinTech",
    "ai": "AI",
    "machine-learning": "AI",
    "deep-learning": "AI",
    "ai-tools": "AI Tools",
    "trading": "Finance",
    "quant": "Finance",
}

_TYPE_MAP: dict[str, str] = {
    "framework": "Framework",
    "library": "Library",
    "tool": "Tool",
    "api": "API",
    "agent": "Agent",
    "dataset": "Dataset",
    "demo": "Demo",
    "tutorial": "Tutorial",
    "chatbot": "Chatbot",
    "app": "Application",
    "application": "Application",
    "platform": "Platform",
}


def _infer_category(topics: list[str]) -> str:
    for topic in topics:
        t = topic.lower()
        if t in _CATEGORY_MAP:
            return _CATEGORY_MAP[t]
    return "AI"


def _infer_type(topics: list[str], description: str) -> str:
    combined = " ".join(topics + [description or ""]).lower()
    for keyword, label in _TYPE_MAP.items():
        if keyword in combined:
            return label
    return "Library"


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def _gh_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    if GH_TOKEN:
        headers["Authorization"] = f"Bearer {GH_TOKEN}"
    return headers


def fetch_repos(query: str) -> list[dict]:
    """Return all repos matching *query* with MIN_STARS+ stars, updated since SINCE_DATE."""
    repos: list[dict] = []
    page = 1
    full_query = f"{query} stars:>={MIN_STARS} pushed:>={SINCE_DATE}"

    while True:
        url = "https://api.github.com/search/repositories"
        params = {
            "q": full_query,
            "sort": "stars",
            "order": "desc",
            "per_page": PER_PAGE,
            "page": page,
        }
        resp = requests.get(url, headers=_gh_headers(), params=params, timeout=30)

        # Respect secondary rate limits
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            reset_ts = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(reset_ts - int(time.time()), 1)
            print(f"  Rate limited — sleeping {wait}s")
            time.sleep(wait)
            continue

        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        repos.extend(items)

        # GitHub caps search results at 1000 items regardless of total_count
        if len(items) < PER_PAGE or len(repos) >= 1000:
            break

        page += 1
        # Be polite: stay well under the 30 req/min search rate limit
        time.sleep(2)

    print(f"  Query '{query}': fetched {len(repos)} repos")
    return repos


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize(repo: dict) -> dict:
    topics: list[str] = repo.get("topics") or []
    description: str = repo.get("description") or ""
    pushed_at: str = repo.get("pushed_at") or repo.get("updated_at") or ""
    date_str = pushed_at[:10] if pushed_at else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    return {
        "github_id":   repo["id"],
        "project":     repo["full_name"],
        "category":    _infer_category(topics),
        "type":        _infer_type(topics, description),
        "description": description[:500] if description else None,
        "creator":     repo["owner"]["login"],
        "date":        date_str,
        "source":      repo["html_url"],
        "stars":       repo.get("stargazers_count", 0),
        "topics":      topics,
        "language":    repo.get("language"),
        "synced_at":   datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Supabase upsert
# ---------------------------------------------------------------------------

def upsert_batch(sb: Client, rows: list[dict]) -> None:
    if not rows:
        return
    # on_conflict targets the unique column; Supabase upsert uses it for dedup
    sb.table(TABLE).upsert(rows, on_conflict="github_id").execute()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    seen_ids: set[int] = set()
    all_rows: list[dict] = []

    for query in QUERIES:
        print(f"\nFetching: {query}")
        repos = fetch_repos(query)
        for repo in repos:
            gid = repo["id"]
            if gid in seen_ids:
                continue
            seen_ids.add(gid)
            all_rows.append(normalize(repo))

    print(f"\nTotal unique repos to upsert: {len(all_rows)}")

    # Upsert in chunks of 500 to stay within Supabase request limits
    chunk_size = 500
    for i in range(0, len(all_rows), chunk_size):
        chunk = all_rows[i : i + chunk_size]
        upsert_batch(sb, chunk)
        print(f"  Upserted rows {i + 1}–{i + len(chunk)}")

    print("\nSync complete.")


if __name__ == "__main__":
    main()
