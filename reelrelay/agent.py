"""ReelRelay — festival & distribution strategy agent pipeline.

Four LlmAgents run in sequence, passing work through session state:
intake → scout → strategist → pitch. `root_agent` is the entry point that
`adk run`, `adk web`, and cli.py all use.
"""

import os
from datetime import date

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext

from .strategy import build_plan, loads_loose
from .tools import parallel_extract, parallel_search

MODEL = os.environ.get("REELRELAY_MODEL", "gemini-2.5-flash")


def stamp_today(callback_context: CallbackContext) -> None:
    """Tell the scout what day it is.

    Nothing else in the pipeline did, so the model guessed submission years from
    its training priors -- and guessed differently on each run. Validation runs
    saw it search 2024/2025 cycles in August 2026, which surfaced as candidates
    rejected for deadlines that had expired a year or more earlier.
    """
    callback_context.state["today"] = date.today().isoformat()


def compute_plan(callback_context: CallbackContext) -> None:
    """Build the submission plan in Python before the strategist speaks.

    Budget math, tier balance, and premiere sequencing are decisions a model
    should not improvise. The strategist receives the finished plan as grounded
    facts and explains the reasoning behind it.
    """
    state = callback_context.state
    profile = loads_loose(state.get("film_profile")) or {}
    # The verify stage republishes the scout's list with fees confirmed off the
    # festivals' own pages; fall back to the raw list if it did not produce one.
    research = loads_loose(state.get("verified_research")) or loads_loose(
        state.get("festival_research")
    )

    if not isinstance(research, list) or not research:
        state["computed_plan"] = (
            "No machine-readable festival candidates were produced by the scout. "
            "Explain this to the filmmaker and recommend re-running the research "
            "with broader queries. Do not invent festivals."
        )
        return

    try:
        state["computed_plan"] = build_plan(profile, research).to_markdown()
    except Exception as exc:
        state["computed_plan"] = (
            f"The deterministic planner failed ({exc}). Tell the filmmaker the "
            "plan could not be computed rather than estimating one yourself."
        )

intake_agent = LlmAgent(
    name="intake",
    model=MODEL,
    description="Normalizes a filmmaker's raw description into a film profile.",
    instruction="""You are the intake coordinator for ReelRelay, a festival
strategy service for independent filmmakers.

The user message describes their film (possibly as JSON, possibly free text).
Produce a normalized FILM PROFILE as compact JSON with exactly these keys:
title, logline, genre, subgenres, runtime_minutes, premiere_status
(world/national/regional/none-remaining), completion_date, country,
languages, budget_for_submissions_usd, themes (list), comparable_films (list),
target_outcome (e.g. "sales agent", "streaming deal", "career visibility").

Infer conservatively; use null for anything truly unknown. Output ONLY the
JSON object, no commentary.""",
    output_key="film_profile",
)

scout_agent = LlmAgent(
    name="scout",
    model=MODEL,
    description="Researches currently-open festivals that fit the film, using live web search.",
    instruction="""You are a film-festival researcher. Today's date is {today}.

Festival cycles turn over every year. Work out the current and next cycle from
that date and put those years in your queries — do not guess a year from
memory, and do not research a cycle that has already closed. Every deadline you
report must fall on or after {today}.

Here is the film profile:

{film_profile}

Use the parallel_search tool 3-4 times, and spend those calls deliberately. A
submission slate lives or dies on mid-tier and niche festivals; famous names
are the smallest part of it and the part you already know without searching.

- AT MOST ONE call on top-tier festivals (Sundance, Cannes, TIFF, Berlin and
  peers). One is enough. Do not spend a second call here.
- AT LEAST ONE call on respected mid-tier festivals: regional, national and
  mid-size international ones — the festivals a film like this realistically
  plays. Search by region and country, by "regional film festival" and
  "short film festival" plus the film's territory, and by the festivals that
  programmed its comparable films.
- AT LEAST ONE call on niche, genre and theme festivals matching this film's
  subgenres and themes.

Aim to come back with at least 5 mid-tier and at least 4 niche candidates.
Returning ten famous festivals is a failed search, however well-sourced.

In every call, look for:
- currently open or upcoming submission windows and their deadlines/fees.
  Results carry a publish_date: prefer recent pages, and never carry a prior
  cycle's deadline forward as if it were this one's
- genre and theme fit (recent lineups, programmer interviews, festival focus)

Then output a JSON list of 12-20 festival candidates, each with: name, tier,
submission_deadline, fee_usd, fit_score, fit_reason (one sentence citing what
you found), premiere_requirement, source_url.

tier must be exactly one of "top", "mid" or "niche". Hedged values like
"mid-to-top" are silently downgraded by the planner, so commit to one.

fit_score is a 0.0-1.0 judgment of how well this film suits this festival, and
it is the only ranking signal the planner has — score honestly and spread the
range, because scoring everything alike reduces the plan to cheapest-first.

source_url must be a page you actually saw in the search results. Only include
festivals you found evidence for — never invent deadlines or fees. If a field
is unverified, set it to null. Output ONLY the JSON list.""",
    tools=[parallel_search],
    before_agent_callback=stamp_today,
    output_key="festival_research",
)

verify_agent = LlmAgent(
    name="verify",
    model=MODEL,
    description="Reads festival pages directly to confirm fees and deadlines the search snippets omitted.",
    instruction="""You verify festival details before a filmmaker spends money
on them. Today is {today}. Here is the scout's candidate list:

{festival_research}

A candidate with a null fee_usd or null submission_deadline is discarded
unfunded by the planner, however good its fit — and baseline validation showed
this is the single biggest source of loss, because entry fees live on the
submission page rather than in a search snippet.

1. Collect the source_url of every candidate whose fee_usd or
   submission_deadline is null.
2. Call parallel_extract on them, batching up to 10 URLs per call, with an
   objective naming exactly what you need — for example: "the short film
   submission fee in USD and the regular submission deadline for the current
   cycle".
3. Read what comes back and fill in ONLY what the page actually states.

Then output the COMPLETE candidate list as a JSON list — every candidate the
scout gave you, verified or not, with the same keys.

Rules that matter more than completeness:
- If the page does not state a fee or deadline, leave it null. A fabricated fee
  costs a filmmaker real money, and a wrong deadline costs them the festival.
- If a page states a deadline earlier than {today}, that cycle has closed;
  record what the page says rather than adjusting it to look current.
- If a URL fails to extract, leave that candidate untouched.
- Change nothing else — no new candidates, no re-tiering, no edited fit scores.

Output ONLY the JSON list.""",
    tools=[parallel_extract],
    before_agent_callback=stamp_today,
    output_key="verified_research",
)

strategist_agent = LlmAgent(
    name="strategist",
    model=MODEL,
    description="Explains the computed, budget-bounded submission plan to the filmmaker.",
    instruction="""You are a festival strategist (the kind filmmakers pay
$1,500-5,000). Film profile:

{film_profile}

A deterministic planner has already selected the slate — tier balance, budget
math, premiere sequencing, and deadline ordering are settled:

{computed_plan}

Present this plan to the filmmaker:
1. Open with 5-8 sentences of strategy rationale they can act on — why this
   shape of slate, what the premiere sequencing protects, what the urgent
   deadlines demand this month.
2. Reproduce the plan table EXACTLY as computed. Never add, drop, reprice, or
   re-date a festival, and never recalculate the budget totals.
3. Explain what was set aside and what they should manually verify.

The numbers are authoritative; your job is judgment and clarity, not
arithmetic.""",
    before_agent_callback=compute_plan,
    output_key="submission_plan",
)

pitch_agent = LlmAgent(
    name="pitch",
    model=MODEL,
    description="Drafts a personalized cover letter for the top-priority festival.",
    instruction="""You draft festival cover letters that programmers actually
read. Film profile:

{film_profile}

Submission plan:

{submission_plan}

Write the cover letter for the SINGLE highest-priority upcoming submission in
the plan: 150-220 words, specific to that festival (reference its focus or
past programming from the research — no generic flattery), professional but
warm, ending with a clear thank-you. Ground every claim in the film profile;
invent nothing. Label it clearly with the festival name.""",
    output_key="sample_pitch",
)

root_agent = SequentialAgent(
    name="reelrelay",
    description="ReelRelay: intake → live festival research → fee/deadline verification → tiered submission strategy → sample pitch.",
    sub_agents=[intake_agent, scout_agent, verify_agent, strategist_agent, pitch_agent],
)
