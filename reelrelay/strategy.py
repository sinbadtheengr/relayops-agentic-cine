"""Deterministic submission-plan engine.

Gemini researches and narrates; this module decides. Tiering, budget math, and
premiere sequencing live in plain Python so the plan is reproducible, testable,
and never a hallucinated arithmetic error. The strategist agent receives the
computed plan as grounded facts and explains it.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime

# Scout emits top/mid/niche; strategy thinks in college-application terms.
TIER_MAP = {
    "top": "reach",
    "mid": "target",
    "niche": "safe",
    "reach": "reach",
    "target": "target",
    "safe": "safe",
}
TIER_MIN = {"reach": 2, "target": 4, "safe": 3}
TIER_MAX = {"reach": 3, "target": 6, "safe": 4}
FILL_ORDER = ("target", "reach", "safe")
URGENT_DAYS = 14
# Leftover budget is not a reason to enter a festival the film doesn't suit.
MIN_OPPORTUNISTIC_FIT = 0.5


def parse_money_cents(value) -> int | None:
    """Accept 45, 45.0, '$45', '45 USD' -> 4500 cents. None if unusable."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value) * 100)
    match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    return round(float(match.group()) * 100) if match else None


def format_cents(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def parse_deadline(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def loads_loose(value):
    """Parse JSON that may arrive fenced or wrapped in model prose."""
    if value is None or isinstance(value, (list, dict)):
        return value
    text = str(value).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("[", "]"), ("{", "}")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


@dataclass
class Festival:
    name: str
    tier: str
    deadline: date
    fee_cents: int
    fit_score: float = 0.5
    fit_reason: str = ""
    premiere_requirement: str | None = None
    source_url: str | None = None

    @property
    def requires_world_premiere(self) -> bool:
        return "world" in (self.premiere_requirement or "").lower()

    def days_until(self, today: date) -> int:
        return (self.deadline - today).days

    def value_per_dollar(self) -> float:
        return self.fit_score / max(self.fee_cents, 1) * 100


@dataclass
class PlannedSubmission:
    festival: Festival
    days_until_deadline: int
    urgent: bool
    note: str | None = None


@dataclass
class SubmissionPlan:
    submissions: list[PlannedSubmission] = field(default_factory=list)
    excluded: list[tuple[str, str]] = field(default_factory=list)
    budget_cents: int = 0
    premiere_target: str | None = None
    today: date = field(default_factory=date.today)

    @property
    def committed_cents(self) -> int:
        return sum(s.festival.fee_cents for s in self.submissions)

    @property
    def remaining_cents(self) -> int:
        return self.budget_cents - self.committed_cents

    def tier_counts(self) -> dict[str, int]:
        counts = {"reach": 0, "target": 0, "safe": 0}
        for s in self.submissions:
            counts[s.festival.tier] += 1
        return counts

    def to_markdown(self) -> str:
        if not self.submissions:
            lines = ["**No fundable submissions could be planned.**", ""]
            if self.excluded:
                lines.append("Candidates set aside:")
                lines += [f"- {n} — {r}" for n, r in self.excluded]
            return "\n".join(lines)

        counts = self.tier_counts()
        lines = [
            "### Computed submission plan (deterministic — do not recalculate)",
            "",
            f"Budget {format_cents(self.budget_cents)} · "
            f"committed {format_cents(self.committed_cents)} · "
            f"unspent {format_cents(self.remaining_cents)}",
            f"Mix: {counts['reach']} reach · {counts['target']} target · {counts['safe']} safe",
        ]
        if self.premiere_target:
            lines.append(f"World-premiere target: **{self.premiere_target}**")
        lines += [
            "",
            "| # | Festival | Tier | Deadline | Days left | Fee | Note |",
            "|---|---|---|---|---|---|---|",
        ]
        for i, s in enumerate(self.submissions, 1):
            # Plain ASCII: this string prints to Windows cp1252 consoles.
            flag = " (urgent)" if s.urgent else ""
            lines.append(
                f"| {i} | {s.festival.name} | {s.festival.tier} | "
                f"{s.festival.deadline.isoformat()} | {s.days_until_deadline}{flag} | "
                f"{format_cents(s.festival.fee_cents)} | {s.note or s.festival.fit_reason} |"
            )
        if self.excluded:
            lines += ["", "**Set aside:**"]
            lines += [f"- {n} — {r}" for n, r in self.excluded]
        return "\n".join(lines)


def parse_candidates(
    raw: list[dict], today: date
) -> tuple[list[Festival], list[tuple[str, str]]]:
    """Convert scout output into Festivals, reporting what was unusable and why.

    Unverified data is skipped loudly rather than guessed at — a fabricated
    deadline costs a filmmaker a real entry fee.
    """
    festivals: list[Festival] = []
    skipped: list[tuple[str, str]] = []

    for item in raw or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "Unnamed festival").strip()
        deadline = parse_deadline(item.get("submission_deadline") or item.get("deadline"))
        fee_cents = parse_money_cents(item.get("fee_usd", item.get("fee")))

        if deadline is None:
            skipped.append((name, "no verified deadline — confirm manually"))
            continue
        if fee_cents is None:
            skipped.append((name, "no verified fee — confirm manually"))
            continue
        if deadline < today:
            skipped.append((name, f"deadline passed ({deadline.isoformat()})"))
            continue

        tier = TIER_MAP.get(str(item.get("tier", "")).strip().lower(), "target")
        try:
            fit_score = float(item.get("fit_score", 0.5))
        except (TypeError, ValueError):
            fit_score = 0.5

        festivals.append(
            Festival(
                name=name,
                tier=tier,
                deadline=deadline,
                fee_cents=fee_cents,
                fit_score=min(max(fit_score, 0.0), 1.0),
                fit_reason=str(item.get("fit_reason", "")).strip(),
                premiere_requirement=item.get("premiere_requirement"),
                source_url=item.get("source_url"),
            )
        )
    return festivals, skipped


def build_plan(
    profile: dict, candidates: list[dict], today: date | None = None
) -> SubmissionPlan:
    """Select a tiered, budget-bounded, premiere-safe slate of submissions."""
    today = today or date.today()
    budget_cents = parse_money_cents(profile.get("budget_for_submissions_usd")) or 0
    festivals, skipped = parse_candidates(candidates, today)

    has_world_premiere = "world" in str(profile.get("premiere_status", "")).lower()
    if not has_world_premiere:
        kept = []
        for f in festivals:
            if f.requires_world_premiere:
                skipped.append((f.name, "requires a world premiere; none remaining"))
            else:
                kept.append(f)
        festivals = kept

    by_tier: dict[str, list[Festival]] = {"reach": [], "target": [], "safe": []}
    for f in festivals:
        by_tier[f.tier].append(f)
    for group in by_tier.values():
        group.sort(key=lambda f: (-f.fit_score, f.deadline))

    chosen: list[Festival] = []
    spent = 0

    def affordable(f: Festival) -> bool:
        return spent + f.fee_cents <= budget_cents

    # Pass 1: guarantee a balanced slate before optimizing.
    for tier in FILL_ORDER:
        for f in by_tier[tier]:
            if sum(1 for c in chosen if c.tier == tier) >= TIER_MIN[tier]:
                break
            if affordable(f):
                chosen.append(f)
                spent += f.fee_cents

    # Pass 2: spend what's left on the best fit-per-dollar, respecting caps.
    leftovers = sorted(
        (f for f in festivals if f not in chosen),
        key=lambda f: -f.value_per_dollar(),
    )
    for f in leftovers:
        if f.fit_score < MIN_OPPORTUNISTIC_FIT:
            continue
        if sum(1 for c in chosen if c.tier == f.tier) >= TIER_MAX[f.tier]:
            continue
        if affordable(f):
            chosen.append(f)
            spent += f.fee_cents

    for f in festivals:
        if f not in chosen:
            if f.fit_score < MIN_OPPORTUNISTIC_FIT:
                reason = f"fit too weak to fund ({f.fit_score:.2f})"
            elif spent + f.fee_cents > budget_cents:
                reason = "over budget"
            else:
                reason = f"{f.tier} tier already full"
            skipped.append((f.name, reason))

    chosen.sort(key=lambda f: f.deadline)

    # Only one festival can host the world premiere; the rest are contingent.
    premiere_target = None
    if has_world_premiere:
        contenders = [f for f in chosen if f.requires_world_premiere]
        if contenders:
            rank = {"reach": 0, "target": 1, "safe": 2}
            contenders.sort(key=lambda f: (rank[f.tier], f.deadline))
            premiere_target = contenders[0].name

    submissions = []
    for f in chosen:
        note = None
        if premiere_target and f.requires_world_premiere and f.name != premiere_target:
            note = f"contingent — only if {premiere_target} declines (premiere conflict)"
        elif f.name == premiere_target:
            note = "world-premiere target — screen nowhere before this"
        days = f.days_until(today)
        submissions.append(
            PlannedSubmission(
                festival=f, days_until_deadline=days, urgent=days <= URGENT_DAYS, note=note
            )
        )

    return SubmissionPlan(
        submissions=submissions,
        excluded=skipped,
        budget_cents=budget_cents,
        premiere_target=premiere_target,
        today=today,
    )
