"""Live-research validation harness -- the Week 2 go/no-go.

Runs the real pipeline against the real Parallel Search API for one or more
film profiles, then grades each run with reelrelay.audit. The question it
answers: does live web research yield enough festivals with *verifiable*
deadlines and fees to build a real submission slate? If not, the project falls
back to GigRelay, whose architecture is identical and whose data lives in a
different corner of the web.

    python -m reelrelay.validate --suite

Exit codes: 0 GO, 1 MARGINAL, 2 NO-GO, 3 could not validate.
"""

import argparse
import asyncio
import json
import pathlib
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

import os  # noqa: E402  (read after .env is loaded)

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from .agent import root_agent  # noqa: E402
from .audit import GO, MARGINAL, NO_GO, UNVALIDATED, audit_run, suite_verdict  # noqa: E402
from .strategy import loads_loose  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SUITE = [
    REPO_ROOT / "samples" / "sample_film.json",
    *sorted((REPO_ROOT / "samples" / "validation_profiles").glob("*.json")),
]
EXIT_CODES = {GO: 0, MARGINAL: 1, NO_GO: 2, UNVALIDATED: 3}


class RunCapture:
    """Everything one pipeline run tells us about its own research."""

    def __init__(self) -> None:
        self.parallel_calls = 0
        self.extract_calls = 0
        self.queries: list[str] = []
        self.search_urls: list[str] = []  # every URL Parallel actually retrieved
        self.result_count = 0
        self.errors: list[str] = []
        self.unreachable_pages = 0
        self.saw_fixture = False

    def note_call(self, name: str, args: dict) -> None:
        if name == "parallel_extract":
            self.extract_calls += 1
            return
        self.parallel_calls += 1
        for query in args.get("search_queries") or []:
            self.queries.append(str(query))

    def note_response(self, name: str, payload) -> None:
        # ADK passes dict returns through, but wraps other shapes in {"result": ...}.
        if isinstance(payload, dict) and "status" not in payload and "result" in payload:
            payload = payload["result"]
        if not isinstance(payload, dict):
            self.errors.append(f"unreadable tool response: {payload!r}")
            return
        if payload.get("offline_fixture"):
            self.saw_fixture = True
        if payload.get("status") != "ok":
            self.errors.append(str(payload.get("message", f"unknown {name} failure")))
            return
        # A festival page that 404s is a finding about that festival, not a
        # broken measurement -- it must not void the verdict the way a failed
        # API call does.
        self.unreachable_pages += len(payload.get("errors") or [])
        for result in payload.get("results") or []:
            if name != "parallel_extract":
                self.result_count += 1
            url = result.get("url") if isinstance(result, dict) else None
            if url:
                self.search_urls.append(str(url))


async def run_profile(profile_path: pathlib.Path, verbose: bool) -> tuple[dict, RunCapture]:
    """Run the shipping pipeline once and return (final state, captured research)."""
    profile_text = profile_path.read_text(encoding="utf-8")
    runner = InMemoryRunner(agent=root_agent, app_name="reelrelay-validate")
    session = await runner.session_service.create_session(
        app_name="reelrelay-validate", user_id="validate"
    )
    message = types.Content(role="user", parts=[types.Part(text=profile_text)])
    capture = RunCapture()

    async for event in runner.run_async(
        user_id="validate", session_id=session.id, new_message=message
    ):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            call = part.function_call
            if call and call.name in ("parallel_search", "parallel_extract"):
                capture.note_call(call.name, dict(call.args or {}))
                if verbose:
                    args = call.args or {}
                    if call.name == "parallel_extract":
                        urls = args.get("urls") or []
                        print(f"  [verify] extract: {len(urls)} page(s)")
                    else:
                        queries = args.get("search_queries") or []
                        print(f"  [scout] search: {'; '.join(str(q) for q in queries)}")
            response = part.function_response
            if response and response.name in ("parallel_search", "parallel_extract"):
                capture.note_response(response.name, response.response)

    final = await runner.session_service.get_session(
        app_name="reelrelay-validate", user_id="validate", session_id=session.id
    )
    return (dict(final.state) if final else {}), capture


# Values carried over unedited from .env.example. They are truthy enough to pass
# a naive check but earn a 401 from the provider, which the audit would record as
# a search error and grade NO-GO -- the worst verdict this harness could invent.
PLACEHOLDER_PREFIXES = ("your-", "your_", "<", "changeme", "replace-me", "xxx")


def configured(name: str) -> str | None:
    """Env var value, treating blanks and .env.example placeholders as unset."""
    value = (os.environ.get(name) or "").strip()
    if not value or value.lower().startswith(PLACEHOLDER_PREFIXES):
        return None
    return value


def check_environment(allow_offline: bool) -> str | None:
    """Return an error message if this run cannot produce an honest verdict."""
    offline = os.environ.get("REELRELAY_OFFLINE") == "1"
    if offline and not allow_offline:
        return (
            "REELRELAY_OFFLINE=1 is set. The fixture contains fictional festivals, "
            "so it cannot answer the go/no-go. Unset it, or pass --allow-offline to "
            "smoke-test the harness (the verdict will be UNVALIDATED)."
        )
    if not offline and not configured("PARALLEL_API_KEY"):
        return (
            "PARALLEL_API_KEY is not set (or still holds the .env.example "
            "placeholder). Copy .env.example to .env and add a real key from "
            "https://platform.parallel.ai, then re-run."
        )
    if not (configured("GOOGLE_API_KEY") or configured("GOOGLE_CLOUD_PROJECT")):
        return (
            "No Gemini credentials found. Set GOOGLE_API_KEY (AI Studio) or "
            "GOOGLE_CLOUD_PROJECT with GOOGLE_GENAI_USE_VERTEXAI=TRUE in .env. "
            "The agents cannot run without a model, offline fixture or not."
        )
    return None


def use_utf8_console() -> None:
    """Print festival names without dying on the Windows console.

    The default Windows code page is cp1252, which cannot encode the arrow in
    the tool-call line -- so the run died with UnicodeEncodeError at the exact
    moment the scout first called Parallel, and international festival names
    ("Lumiere", "Clermont-Ferrand") came out as mojibake. errors="replace"
    means a console that still cannot render a glyph degrades instead of
    taking the pipeline down with it.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


async def main_async(args: argparse.Namespace) -> int:
    problem = check_environment(args.allow_offline)
    if problem:
        print(f"Cannot validate: {problem}", file=sys.stderr)
        return EXIT_CODES[UNVALIDATED]

    profiles = SUITE if (args.suite or not args.profile) else [
        pathlib.Path(p) for p in args.profile
    ]
    missing = [p for p in profiles if not p.exists()]
    if missing:
        print(f"Missing profile(s): {', '.join(str(p) for p in missing)}", file=sys.stderr)
        return EXIT_CODES[UNVALIDATED]

    audits = []
    for path in profiles:
        print(f"\n=== {path.name} ===")
        try:
            state, capture = await run_profile(path, args.verbose)
        except Exception as exc:  # a crashed run is data, not a stack trace
            print(f"  run failed: {exc}", file=sys.stderr)
            audits.append(
                audit_run(
                    {"title": path.stem},
                    [],
                    [],
                    search_errors=[f"run failed: {exc}"],
                    aborted=True,
                )
            )
            continue

        profile = loads_loose(state.get("film_profile")) or {}
        if not profile.get("title"):
            profile["title"] = path.stem
        raw = loads_loose(state.get("festival_research"))
        raw = raw if isinstance(raw, list) else None
        # Grade the verified list; fall back to the scout's raw one if the
        # verify stage produced nothing usable.
        candidates = loads_loose(state.get("verified_research"))
        if not isinstance(candidates, list) or not candidates:
            candidates = raw or []
        if not candidates:
            capture.errors.append(
                "the scout produced no machine-readable JSON candidate list"
            )

        audit = audit_run(
            profile,
            candidates,
            capture.search_urls,
            parallel_calls=capture.parallel_calls,
            parallel_results=capture.result_count,
            extract_calls=capture.extract_calls,
            raw_candidates=raw,
            search_errors=capture.errors,
            synthetic=capture.saw_fixture,
        )
        audits.append(audit)
        print(audit.to_markdown())

    verdict, notes = suite_verdict(audits)
    print("\n" + "=" * 60)
    print(f"SUITE VERDICT: {verdict}")
    print("=" * 60)
    for note in notes:
        print(f"  {note}")
    print(
        "\nThis verdict is input to a decision, not the decision. Read the "
        "per-profile detail above before choosing to continue or fall back."
    )

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = args.out / f"research-validation-{stamp}.json"
    report_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "suite_verdict": verdict,
                "profiles": [a.to_dict() for a in audits],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nReport written to {report_path}")
    return EXIT_CODES[verdict]


def main() -> None:
    use_utf8_console()
    parser = argparse.ArgumentParser(
        description="Grade live festival research quality (Week 2 go/no-go)."
    )
    parser.add_argument(
        "--profile",
        action="append",
        help="Film profile JSON to validate (repeatable). Default: the full suite.",
    )
    parser.add_argument(
        "--suite",
        action="store_true",
        help="Run the full validation suite (the default when no --profile is given).",
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=REPO_ROOT / "validation",
        help="Directory for the JSON report (default: validation/).",
    )
    parser.add_argument(
        "--allow-offline",
        action="store_true",
        help="Permit a fixture run to smoke-test the harness; forces UNVALIDATED.",
    )
    parser.add_argument("--verbose", action="store_true", help="Print each search query.")
    sys.exit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
