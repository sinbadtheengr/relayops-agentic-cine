"""ADK function tools for ReelRelay.

The Parallel Search API call here satisfies the hackathon's Parallel-track
requirement: it must run at runtime, not just appear in documentation.
"""

import json
import os
import pathlib

from parallel import Parallel

FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "samples"
    / "festival_research_fixture.json"
)


def _offline_results() -> dict:
    """Synthetic fixture so the pipeline is runnable and demoable without a key."""
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return {
        "status": "ok",
        "offline_fixture": True,
        "warning": "SYNTHETIC FIXTURE DATA — fictional festivals. Never present as real research.",
        "results": [
            {
                "url": r["source_url"],
                "title": r["name"],
                "excerpts": [json.dumps(r)],
                "publish_date": None,  # shape parity with live results
            }
            for r in data["results"]
        ],
    }


def _offline_extract(urls: list[str]) -> dict:
    """Fixture counterpart to parallel_extract, keyed by the fixture's own URLs."""
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    wanted = {str(u).strip() for u in urls or []}
    return {
        "status": "ok",
        "offline_fixture": True,
        "warning": "SYNTHETIC FIXTURE DATA — fictional festivals. Never present as real research.",
        "results": [
            {
                "url": r["source_url"],
                "title": r["name"],
                "excerpts": [json.dumps(r)],
                "publish_date": None,
            }
            for r in data["results"]
            if r["source_url"] in wanted
        ],
        "errors": [],
    }


def parallel_extract(urls: list[str], objective: str) -> dict:
    """Read festival pages directly to confirm what a search snippet omitted.

    Search returns excerpts, and a festival's entry fee usually lives on the
    submission page rather than in the snippet. Baseline validation found this
    was the only reason candidates were unusable, so this is the stage that
    turns a set-aside candidate into a fundable one.

    Args:
        urls: 1-10 page URLs to read, normally the source_url of candidates
            whose fee or deadline came back null.
        objective: What to find on those pages, e.g. "the short film submission
            fee in USD and the regular submission deadline".

    Returns:
        dict with status, results (url, title, excerpts, publish_date) and
        per-URL errors, or an error message if the key is missing or the call
        fails.
    """
    if os.environ.get("REELRELAY_OFFLINE") == "1":
        return _offline_extract(urls)

    api_key = os.environ.get("PARALLEL_API_KEY")
    if not api_key:
        return {
            "status": "error",
            "message": "PARALLEL_API_KEY is not set. Copy .env.example to .env "
            "and add your key from https://platform.parallel.ai, or set "
            "REELRELAY_OFFLINE=1 to run against the synthetic fixture.",
        }

    try:
        client = Parallel(api_key=api_key)
        extracted = client.extract(urls=list(urls or []), objective=objective)
        return {
            "status": "ok",
            "results": [
                {
                    "url": r.url,
                    "title": r.title,
                    "excerpts": r.excerpts,
                    "publish_date": r.publish_date,
                }
                for r in extracted.results
            ],
            # Unreachable pages are data the agent should see, not a failure:
            # a dead submission page is itself a reason to distrust the listing.
            "errors": [
                {
                    "url": e.url,
                    "error_type": e.error_type,
                    "http_status_code": e.http_status_code,
                }
                for e in (extracted.errors or [])
            ],
        }
    except Exception as exc:  # surface API failures to the agent as data
        return {"status": "error", "message": f"Parallel extract failed: {exc}"}


def parallel_search(objective: str, search_queries: list[str]) -> dict:
    """Run live web research via the Parallel Search API.

    Args:
        objective: Natural-language description of what the research should
            accomplish, e.g. "Find 2026 submission deadlines, fees, and genre
            focus for mid-tier North American short-film festivals".
        search_queries: 2-5 concrete search queries supporting the objective.

    Returns:
        dict with status and a list of results (url, title, excerpts), or an
        error message if the API key is missing or the call fails.
    """
    if os.environ.get("REELRELAY_OFFLINE") == "1":
        return _offline_results()

    api_key = os.environ.get("PARALLEL_API_KEY")
    if not api_key:
        return {
            "status": "error",
            "message": "PARALLEL_API_KEY is not set. Copy .env.example to .env "
            "and add your key from https://platform.parallel.ai, or set "
            "REELRELAY_OFFLINE=1 to run against the synthetic fixture.",
        }

    try:
        client = Parallel(api_key=api_key)
        search = client.search(
            objective=objective,
            search_queries=search_queries,
        )
        return {
            "status": "ok",
            "results": [
                {
                    "url": r.url,
                    "title": r.title,
                    "excerpts": r.excerpts,
                    # Festival pages go stale between cycles; the scout needs to
                    # see age to avoid citing last year's deadline as this year's.
                    "publish_date": r.publish_date,
                }
                for r in search.results
            ],
        }
    except Exception as exc:  # surface API failures to the agent as data
        return {"status": "error", "message": f"Parallel search failed: {exc}"}
