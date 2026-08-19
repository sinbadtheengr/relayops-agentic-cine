# ReelRelay 🎬

**A festival & distribution strategy agent for independent filmmakers** — built for the [Agentic Cinema: The Blockbuster Hackathon](https://agentic-cinema.devpost.com/) (Google Cloud · **Parallel partner track**).

Indie filmmakers face 3,000+ festivals with different genre fits, premiere rules, tiered deadlines, and $25–85 entry fees. A wrong strategy burns thousands of dollars, and human festival strategists charge $1,500–5,000 per film. ReelRelay does what a strategist does — researches, tiers, budgets, schedules, and pitches — as an agent pipeline grounded in **live web research**.

## How it works

A Gemini-powered ADK `SequentialAgent` with five stages, passing work through session state:

| Stage | Agent | What it does |
|---|---|---|
| 1 | `intake` | Normalizes the filmmaker's description into a structured film profile |
| 2 | `scout` | **Calls the Parallel Search API at runtime** to research currently-open festivals: deadlines, fees, recent lineups, programmer focus |
| 3 | `verify` | **Calls the Parallel Extract API** on candidates whose fee or deadline came back null, reading the festival's own submission page |
| 4 | `strategist` | Explains the plan computed by [`strategy.py`](reelrelay/strategy.py) — tier balance, budget, premiere sequencing |
| 5 | `pitch` | Drafts a personalized cover letter for the top-priority festival, grounded in the research |

Stage 3 exists because measurement said so, not because it seemed nice. The
[recorded baseline](docs/baseline-2026-08-16.json) — four films, four genres,
three countries — found 100% of candidates traceable to a real search result and
**every single unusable one rejected for a missing entry fee**: no stale
deadlines, no missing deadlines, nothing else. Fees live on the submission page,
not in a search snippet, so the pipeline goes and reads the page.

### The model researches; Python decides

Budget math, tier quotas, premiere sequencing, and deadline ordering are **not** left to the model. A `before_agent_callback` runs [`build_plan()`](reelrelay/strategy.py) before the strategist speaks, and the agent receives a finished plan to explain rather than numbers to improvise. That means the plan is deterministic, unit-tested, and free of arithmetic hallucination — the strategist is told explicitly that the numbers are authoritative.

The engine also refuses to guess: candidates without a verified deadline or fee are set aside with a stated reason rather than filled in, because a fabricated deadline costs a filmmaker a real entry fee. Leftover budget never justifies funding a poor-fit festival.

## Is the research actually good enough?

ReelRelay is only worth building if live web research yields festivals with
*verifiable* deadlines and fees. That is an empirical question, so it gets
measured rather than assumed:

```bash
python -m reelrelay.validate --suite
```

This runs the shipping pipeline against real Parallel search for four films
chosen to stress different corners of the data ([why these four](samples/validation_profiles/README.md)),
then grades each run in [`audit.py`](reelrelay/audit.py): candidate yield, how
many survive the parser and why the rest didn't, tier coverage against the
planner's minimums, plan viability — and **groundedness**, the share of
candidates whose `source_url` actually appears in what Parallel returned. The
scout is told never to invent festivals; this is where that is checked instead
of trusted.

Each profile earns GO / MARGINAL / NO-GO against published thresholds, and the
suite takes the worst of them. A run against the offline fixture is forced to
`UNVALIDATED` no matter how good the numbers look — a go/no-go answered with
fictional festivals is worse than no answer. Exit codes: `0` GO, `1` MARGINAL,
`2` NO-GO, `3` could not validate. A JSON report lands in `validation/`.

## Development without API keys

The scout falls back to a synthetic fixture, so the whole pipeline runs offline:

```bash
set REELRELAY_OFFLINE=1
```

The fixture (`samples/festival_research_fixture.json`) contains **fictional** festivals on `example.invalid` — it exists for deterministic tests and must never be presented as research.

```bash
.venv\Scripts\python -m pytest tests\ -q
```

## Quickstart

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows (source .venv/bin/activate on mac/linux)
pip install -r requirements.txt
copy .env.example .env        # then fill in GOOGLE_API_KEY and PARALLEL_API_KEY
```

Run the full pipeline against the sample film:

```bash
python -m reelrelay.cli --profile samples/sample_film.json
```

Or use the ADK dev UI (chat interface, event traces, state inspector):

```bash
adk web
```

## Keys

- **Gemini**: an [AI Studio](https://aistudio.google.com/) key for local dev, or Vertex AI project config for deployment (see `.env.example`).
- **Parallel**: from [platform.parallel.ai](https://platform.parallel.ai) — required; the scout stage is the heart of the product.

## Roadmap (hackathon)

- [x] Wk 1 — ADK pipeline + Parallel **Search** scout, deterministic strategy engine, offline fixture, 30 tests
- [ ] Wk 2 — live-research validation: harness + rubric + 4-profile suite built (78 tests); **awaiting live keys to produce the verdict**
  - [x] Baseline recorded — [docs/baseline-2026-08-16.json](docs/baseline-2026-08-16.json). 44 candidates, 25 usable, 100% grounded, and all 19 rejections are missing fees
  - [x] **Verify stage on Parallel's Extract API** built — the baseline earned it. The audit now reports `fees_recovered` / `deadlines_recovered` so the stage has to prove its keep
  - [ ] Re-run the suite for the measured before/after
  - [ ] Persistence (Firestore)
- [ ] Wk 3 — web dashboard (submission kanban, deadline calendar) on Cloud Run; migrate `SequentialAgent` → ADK `Workflow` graph, using conditional routing to re-scout when the research yields too few usable candidates
  - [ ] **Deadline watch on Parallel's Monitor API** — festival deadlines shift, extensions get announced, fee waivers appear. Watching each planned festival's submission page turns a one-shot plan into a living pipeline and gives the kanban something to react to. This is also the stage that ports back to RelayOps as follow-up triggers.
- [ ] Wk 4 — **multimodal trailer analysis — committed scope, not a stretch.** Gemini reads the trailer for tone and theme and feeds that into the scout's fit reasoning, so the plan reflects how the film actually plays rather than how its logline reads. It is also this project's only GenMedia surface: an *Agentic Cinema* entry that generates nothing invites the question, and this answers it. Then polish and demo data.
- [ ] Wk 5 — 3-min demo video, Devpost submission (due **Sept 9, 2026, 2:00 PM PDT**)

## License

[MIT](LICENSE)
