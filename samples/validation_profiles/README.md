# Validation profiles

Films chosen to stress different corners of the web's festival data, so the
Week 2 go/no-go isn't decided by whichever genre happened to research well.
Run them with `python -m reelrelay.validate --suite`.

The profile JSON files hold nothing but the film — every byte of them is fed to
the intake agent as a prompt, so the reasoning below lives here instead.

| Profile | What it stresses | Failure would mean |
|---|---|---|
| `../sample_film.json` — *Night Shift at the Lumière* | The baseline: English-language drama short, world premiere intact, mid budget. The easiest case on the circuit. | The idea is dead. If research fails here it fails everywhere. |
| `genre_horror_short.json` — *Vacancy, No Vacancy* | The genre circuit, plus the no-premiere-remaining path: every world-premiere-required festival must be filtered out. Small budget forces the planner to choose rather than fund everything. | Premiere rules can't be researched reliably — the single most expensive thing to get wrong for a filmmaker. |
| `feature_documentary.json` — *The Last Rewind* | Features rather than shorts: tiered early/regular/late deadlines and much higher fees. The larger budget means thin research shows up as tier gaps, not budget exhaustion. | Scope narrows to shorts. |
| `international_animation.json` — *La Casa de los Relojes Rotos* | The hardest case: a Spanish-language animated short from Mexico. Non-US submission details are often published only in the local language, behind FilmFreeway, or not at all. | Scope narrows to English-language / North American festivals — survivable, but say so in the demo rather than pretending otherwise. |

If only the last one fails, narrow the scope. If the baseline fails, fall back
to GigRelay — same architecture, different domain.
