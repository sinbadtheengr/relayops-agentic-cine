# ReelRelay 🎬

**A festival & distribution strategy agent for independent filmmakers** — built for the [Agentic Cinema: The Blockbuster Hackathon](https://agentic-cinema.devpost.com/) (Google Cloud · **Parallel partner track**).

Indie filmmakers face 3,000+ festivals with different genre fits, premiere rules, tiered deadlines, and $25–85 entry fees. A wrong strategy burns thousands of dollars, and human festival strategists charge $1,500–5,000 per film. ReelRelay does what a strategist does — researches, tiers, budgets, schedules, and pitches — as an agent pipeline grounded in **live web research**.

## How it works

A Gemini-powered ADK `SequentialAgent` with four stages, passing work through session state:

| Stage | Agent | What it does |
|---|---|---|
| 1 | `intake` | Normalizes the filmmaker's description into a structured film profile |
| 2 | `scout` | **Calls the Parallel Search API at runtime** to research currently-open festivals: deadlines, fees, recent lineups, programmer focus |
| 3 | `strategist` | Explains the plan computed by [`strategy.py`](reelrelay/strategy.py) — tier balance, budget, premiere sequencing |
| 4 | `pitch` | Drafts a personalized cover letter for the top-priority festival, grounded in the research |

### The model researches; Python decides

Budget math, tier quotas, premiere sequencing, and deadline ordering are **not** left to the model. A `before_agent_callback` runs [`build_plan()`](reelrelay/strategy.py) before the strategist speaks, and the agent receives a finished plan to explain rather than numbers to improvise. That means the plan is deterministic, unit-tested, and free of arithmetic hallucination — the strategist is told explicitly that the numbers are authoritative.

The engine also refuses to guess: candidates without a verified deadline or fee are set aside with a stated reason rather than filled in, because a fabricated deadline costs a filmmaker a real entry fee. Leftover budget never justifies funding a poor-fit festival.

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

- [x] Wk 1 — ADK pipeline + Parallel scout, deterministic strategy engine, offline fixture, 30 tests
- [ ] Wk 2 — live-research validation (go/no-go on festival data quality), persistence (Firestore)
- [ ] Wk 3 — web dashboard (submission kanban, deadline calendar) on Cloud Run; migrate `SequentialAgent` → ADK `Workflow` graph, using conditional routing to re-scout when the research yields too few usable candidates
- [ ] Wk 4 — multimodal trailer analysis, polish, demo data
- [ ] Wk 5 — 3-min demo video, Devpost submission (due Sept 7, 2026)

## License

[MIT](LICENSE)
