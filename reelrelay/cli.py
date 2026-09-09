"""Scripted pipeline run: python -m reelrelay.cli --profile samples/sample_film.json"""

import argparse
import asyncio
import pathlib
import sys

from dotenv import load_dotenv

load_dotenv()

from google.adk.runners import InMemoryRunner  # noqa: E402  (needs env loaded first)
from google.genai import types  # noqa: E402

from .agent import root_agent  # noqa: E402


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


async def run_pipeline(profile_text: str) -> None:
    runner = InMemoryRunner(agent=root_agent, app_name="reelrelay")
    session = await runner.session_service.create_session(
        app_name="reelrelay", user_id="cli"
    )
    message = types.Content(role="user", parts=[types.Part(text=profile_text)])

    current_author = None
    async for event in runner.run_async(
        user_id="cli", session_id=session.id, new_message=message
    ):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if part.function_call:
                print(f"\n[{event.author}] → tool: {part.function_call.name}")
            elif part.text:
                if event.author != current_author:
                    current_author = event.author
                    print(f"\n{'=' * 60}\n[{current_author}]\n{'=' * 60}")
                print(part.text, end="", flush=True)
    print()


def main() -> None:
    use_utf8_console()
    parser = argparse.ArgumentParser(description="Run the ReelRelay pipeline once.")
    parser.add_argument(
        "--profile",
        default="samples/sample_film.json",
        help="Path to a film profile (JSON or free text).",
    )
    args = parser.parse_args()
    profile_text = pathlib.Path(args.profile).read_text(encoding="utf-8")
    asyncio.run(run_pipeline(profile_text))


if __name__ == "__main__":
    main()
