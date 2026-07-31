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
            }
            for r in data["results"]
        ],
    }


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
                {"url": r.url, "title": r.title, "excerpts": r.excerpts}
                for r in search.results
            ],
        }
    except Exception as exc:  # surface API failures to the agent as data
        return {"status": "error", "message": f"Parallel search failed: {exc}"}
