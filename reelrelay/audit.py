"""Research-quality rubric behind the Week 2 go/no-go decision.

ReelRelay is only viable if live web research actually yields festivals with
verifiable deadlines and fees. This module turns one pipeline run into a scored
audit so that decision rests on measurements instead of impressions.

Nothing here touches the network or a model: it takes what the scout emitted
and what Parallel returned, and grades one against the other.
"""

from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlsplit

from .strategy import TIER_MAP, TIER_MIN, build_plan, parse_candidates

# --- Thresholds for a GO -----------------------------------------------------
# TIER_MIN sums to 9, so fewer than 9 usable candidates cannot fill a balanced
# slate no matter how good they are. The rest are set where a human strategist
# would still call the research worth paying for.
MIN_CANDIDATES = 12
MIN_USABLE = sum(TIER_MIN.values())
MIN_USABLE_RATE = 0.60
MIN_GROUNDEDNESS = 0.80
MIN_PLAN_SIZE = 6

# --- Floors below which the domain itself looks unworkable -------------------
FLOOR_USABLE = 6
FLOOR_GROUNDEDNESS = 0.50

GO = "GO"
MARGINAL = "MARGINAL"
NO_GO = "NO-GO"
UNVALIDATED = "UNVALIDATED"

# Worst-first, so min() over a suite picks the most cautious verdict.
VERDICT_RANK = {UNVALIDATED: 0, NO_GO: 1, MARGINAL: 2, GO: 3}

# parse_candidates() emits exactly these three rejection reasons; anything else
# would be a strategy.py change this rubric has not been taught about.
REASON_BUCKETS = (
    ("no verified deadline", "missing_deadline"),
    ("no verified fee", "missing_fee"),
    ("deadline passed", "deadline_passed"),
)


def bucket_reason(reason: str) -> str:
    text = str(reason).lower()
    for needle, bucket in REASON_BUCKETS:
        if needle in text:
            return bucket
    return "other"


def host_of(url) -> str | None:
    """Registrable-ish host for grounding comparisons ('www.' stripped)."""
    if not url:
        return None
    text = str(url).strip()
    if not text:
        return None
    if "//" not in text:
        text = "//" + text
    host = urlsplit(text).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


@dataclass
class ResearchAudit:
    """One pipeline run, graded."""

    profile_title: str = ""
    synthetic: bool = False

    parallel_calls: int = 0
    parallel_results: int = 0
    search_errors: list[str] = field(default_factory=list)

    candidate_count: int = 0
    usable_count: int = 0
    set_aside: list[tuple[str, str]] = field(default_factory=list)
    reason_counts: dict[str, int] = field(default_factory=dict)

    tier_counts: dict[str, int] = field(default_factory=dict)
    unmapped_tiers: list[str] = field(default_factory=list)
    duplicate_names: list[str] = field(default_factory=list)
    missing_fit_scores: int = 0

    grounded_count: int = 0
    exact_url_matches: int = 0
    ungrounded: list[str] = field(default_factory=list)
    missing_source_url: int = 0

    plan_size: int = 0
    budget_cents: int = 0
    committed_cents: int = 0

    verdict: str = UNVALIDATED
    reasons: list[str] = field(default_factory=list)

    @property
    def usable_rate(self) -> float:
        return self.usable_count / self.candidate_count if self.candidate_count else 0.0

    @property
    def groundedness_rate(self) -> float:
        return self.grounded_count / self.candidate_count if self.candidate_count else 0.0

    @property
    def tier_minimums_met(self) -> bool:
        return all(self.tier_counts.get(t, 0) >= n for t, n in TIER_MIN.items())

    def to_dict(self) -> dict:
        return {
            "profile_title": self.profile_title,
            "synthetic": self.synthetic,
            "verdict": self.verdict,
            "reasons": self.reasons,
            "parallel": {
                "calls": self.parallel_calls,
                "results": self.parallel_results,
                "errors": self.search_errors,
            },
            "candidates": {
                "emitted": self.candidate_count,
                "usable": self.usable_count,
                "usable_rate": round(self.usable_rate, 3),
                "set_aside_reasons": self.reason_counts,
                "set_aside": [{"name": n, "reason": r} for n, r in self.set_aside],
                "duplicate_names": self.duplicate_names,
                "unmapped_tiers": self.unmapped_tiers,
                "missing_fit_scores": self.missing_fit_scores,
            },
            "tiers": {"usable": self.tier_counts, "minimums": TIER_MIN,
                      "minimums_met": self.tier_minimums_met},
            "grounding": {
                "grounded": self.grounded_count,
                "rate": round(self.groundedness_rate, 3),
                "exact_url_matches": self.exact_url_matches,
                "missing_source_url": self.missing_source_url,
                "ungrounded": self.ungrounded,
            },
            "plan": {
                "submissions": self.plan_size,
                "budget_usd": self.budget_cents / 100,
                "committed_usd": self.committed_cents / 100,
            },
        }

    def to_markdown(self) -> str:
        # Plain ASCII: this prints to Windows cp1252 consoles.
        tiers = " / ".join(
            f"{t} {self.tier_counts.get(t, 0)}of{n}" for t, n in TIER_MIN.items()
        )
        lines = [
            f"### {self.profile_title or 'untitled'} -- {self.verdict}",
            "",
            f"- Parallel: {self.parallel_calls} call(s), "
            f"{self.parallel_results} result(s)"
            + (f", {len(self.search_errors)} error(s)" if self.search_errors else ""),
            f"- Candidates: {self.candidate_count} emitted, "
            f"{self.usable_count} usable ({self.usable_rate:.0%})",
            f"- Tier coverage (usable): {tiers}"
            + ("" if self.tier_minimums_met else "  <-- minimums NOT met"),
            f"- Grounded in search results: {self.grounded_count}/{self.candidate_count}"
            f" ({self.groundedness_rate:.0%}), {self.exact_url_matches} exact URL match(es)",
            f"- Plan: {self.plan_size} submission(s), "
            f"${self.committed_cents / 100:,.2f} of ${self.budget_cents / 100:,.2f}",
        ]
        if self.reason_counts:
            counts = ", ".join(f"{k}={v}" for k, v in sorted(self.reason_counts.items()))
            lines.append(f"- Set aside by the parser: {counts}")
        if self.missing_fit_scores:
            lines.append(
                f"- {self.missing_fit_scores} candidate(s) had no fit_score "
                "(planner falls back to 0.5, ranking degenerates to cheapest-first)"
            )
        if self.duplicate_names:
            lines.append(f"- Duplicate names: {', '.join(self.duplicate_names)}")
        if self.unmapped_tiers:
            lines.append(
                f"- Unrecognized tier labels (silently treated as 'target'): "
                f"{', '.join(self.unmapped_tiers)}"
            )
        if self.ungrounded:
            shown = ", ".join(self.ungrounded[:6])
            more = f" (+{len(self.ungrounded) - 6} more)" if len(self.ungrounded) > 6 else ""
            lines.append(f"- NOT grounded in any search result: {shown}{more}")
        if self.search_errors:
            lines += ["", "Search errors:"] + [f"  - {e}" for e in self.search_errors]
        if self.reasons:
            lines += ["", "Verdict reasons:"] + [f"  - {r}" for r in self.reasons]
        return "\n".join(lines)


def audit_run(
    profile: dict,
    candidates: list,
    search_urls: list,
    *,
    parallel_calls: int = 0,
    parallel_results: int = 0,
    search_errors: list | None = None,
    synthetic: bool = False,
    today: date | None = None,
) -> ResearchAudit:
    """Grade one run of the pipeline.

    `search_urls` is every URL Parallel actually returned. A candidate whose
    source_url host never appears there is treated as ungrounded -- the scout is
    told not to invent festivals, and this is where that instruction is checked
    rather than trusted.

    `synthetic=True` (fixture data) forces the UNVALIDATED verdict no matter how
    the numbers look: a go/no-go must never be answered with invented festivals.
    """
    today = today or date.today()
    profile = profile if isinstance(profile, dict) else {}
    candidates = [c for c in (candidates or []) if isinstance(c, dict)]

    audit = ResearchAudit(
        profile_title=str(profile.get("title") or "untitled"),
        synthetic=synthetic,
        parallel_calls=parallel_calls,
        parallel_results=parallel_results,
        search_errors=list(search_errors or []),
        candidate_count=len(candidates),
    )

    usable, skipped = parse_candidates(candidates, today)
    audit.usable_count = len(usable)
    audit.set_aside = list(skipped)
    for _, reason in skipped:
        bucket = bucket_reason(reason)
        audit.reason_counts[bucket] = audit.reason_counts.get(bucket, 0) + 1

    audit.tier_counts = {t: 0 for t in TIER_MIN}
    for festival in usable:
        audit.tier_counts[festival.tier] = audit.tier_counts.get(festival.tier, 0) + 1

    seen: set[str] = set()
    for candidate in candidates:
        raw_tier = str(candidate.get("tier", "")).strip().lower()
        if raw_tier and raw_tier not in TIER_MAP and raw_tier not in audit.unmapped_tiers:
            audit.unmapped_tiers.append(raw_tier)

        name = str(candidate.get("name") or "Unnamed festival").strip()
        key = name.lower()
        if key in seen and name not in audit.duplicate_names:
            audit.duplicate_names.append(name)
        seen.add(key)

        if candidate.get("fit_score") is None:
            audit.missing_fit_scores += 1

    search_url_set = {str(u).strip() for u in (search_urls or []) if u}
    search_hosts = {h for h in (host_of(u) for u in search_url_set) if h}
    for candidate in candidates:
        name = str(candidate.get("name") or "Unnamed festival").strip()
        source = candidate.get("source_url")
        if not source:
            audit.missing_source_url += 1
            audit.ungrounded.append(name)
            continue
        if str(source).strip() in search_url_set:
            audit.exact_url_matches += 1
        if host_of(source) in search_hosts:
            audit.grounded_count += 1
        else:
            audit.ungrounded.append(name)

    plan = build_plan(profile, candidates, today)
    audit.plan_size = len(plan.submissions)
    audit.budget_cents = plan.budget_cents
    audit.committed_cents = plan.committed_cents

    audit.verdict, audit.reasons = _score(audit)
    return audit


def _score(audit: ResearchAudit) -> tuple[str, list[str]]:
    if audit.synthetic:
        return UNVALIDATED, [
            "Run used the synthetic offline fixture; it cannot answer the "
            "go/no-go. Re-run with live PARALLEL_API_KEY and GOOGLE_API_KEY."
        ]

    failures: list[str] = []
    blockers: list[str] = []

    if audit.search_errors:
        blockers.append(f"Parallel search returned {len(audit.search_errors)} error(s)")
    if audit.parallel_calls == 0:
        blockers.append("the scout never called parallel_search (track requirement unmet)")
    if audit.plan_size == 0:
        blockers.append("the planner could fund no submissions at all")
    if audit.usable_count < FLOOR_USABLE:
        blockers.append(
            f"only {audit.usable_count} usable candidate(s); below the "
            f"{FLOOR_USABLE} floor for any workable slate"
        )
    if audit.candidate_count and audit.groundedness_rate < FLOOR_GROUNDEDNESS:
        blockers.append(
            f"only {audit.groundedness_rate:.0%} of candidates trace back to a "
            "search result -- the scout is likely inventing festivals"
        )

    if audit.candidate_count < MIN_CANDIDATES:
        failures.append(
            f"{audit.candidate_count} candidates emitted, wanted >= {MIN_CANDIDATES}"
        )
    if audit.usable_count < MIN_USABLE:
        failures.append(
            f"{audit.usable_count} usable, wanted >= {MIN_USABLE} to fill tier minimums"
        )
    if audit.usable_rate < MIN_USABLE_RATE:
        failures.append(
            f"usable rate {audit.usable_rate:.0%}, wanted >= {MIN_USABLE_RATE:.0%}"
        )
    if audit.groundedness_rate < MIN_GROUNDEDNESS:
        failures.append(
            f"groundedness {audit.groundedness_rate:.0%}, wanted >= {MIN_GROUNDEDNESS:.0%}"
        )
    if not audit.tier_minimums_met:
        failures.append("usable candidates cannot fill the reach/target/safe minimums")
    if audit.plan_size < MIN_PLAN_SIZE:
        failures.append(f"plan has {audit.plan_size} submissions, wanted >= {MIN_PLAN_SIZE}")

    if blockers:
        return NO_GO, blockers + failures
    if failures:
        return MARGINAL, failures
    return GO, ["All thresholds met."]


def suite_verdict(audits: list[ResearchAudit]) -> tuple[str, list[str]]:
    """Worst verdict across profiles -- deliberately conservative.

    A five-week bet should not rest on the one genre where research happened to
    go well, so a single NO-GO profile drags the suite down. The per-profile
    detail is printed alongside so a human can overrule with reasons.
    """
    if not audits:
        return UNVALIDATED, ["No profiles were run."]
    worst = min(audits, key=lambda a: VERDICT_RANK[a.verdict])
    notes = [f"{a.profile_title}: {a.verdict}" for a in audits]
    return worst.verdict, notes
