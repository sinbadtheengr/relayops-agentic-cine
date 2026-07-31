from datetime import date

import pytest

from reelrelay.strategy import (
    build_plan,
    format_cents,
    loads_loose,
    parse_candidates,
    parse_deadline,
    parse_money_cents,
)

TODAY = date(2026, 8, 1)


def fest(name, tier="mid", deadline="2026-10-01", fee=50, **kw):
    return {
        "name": name,
        "tier": tier,
        "submission_deadline": deadline,
        "fee_usd": fee,
        **kw,
    }


class TestParsing:
    @pytest.mark.parametrize(
        "raw,expected",
        [(45, 4500), (45.5, 4550), ("$45", 4500), ("45 USD", 4500), ("1,200", 120000)],
    )
    def test_money_forms(self, raw, expected):
        assert parse_money_cents(raw) == expected

    def test_money_unusable(self):
        assert parse_money_cents(None) is None
        assert parse_money_cents("waived") is None

    def test_deadline_formats(self):
        assert parse_deadline("2026-10-01") == date(2026, 10, 1)
        assert parse_deadline("October 1, 2026") == date(2026, 10, 1)
        assert parse_deadline("garbage") is None

    def test_loads_loose_handles_fenced_json(self):
        assert loads_loose('```json\n[{"a": 1}]\n```') == [{"a": 1}]
        assert loads_loose('Here you go: [{"a": 1}] hope that helps') == [{"a": 1}]
        assert loads_loose("not json at all") is None


class TestCandidateHygiene:
    """Unverified data must be skipped loudly — a fabricated deadline costs money."""

    def test_missing_fields_are_skipped_with_reasons(self):
        raw = [
            fest("Good Fest"),
            fest("No Deadline", deadline=None),
            fest("No Fee", fee=None),
            fest("Expired", deadline="2026-01-01"),
        ]
        festivals, skipped = parse_candidates(raw, TODAY)
        assert [f.name for f in festivals] == ["Good Fest"]
        reasons = dict(skipped)
        assert "no verified deadline" in reasons["No Deadline"]
        assert "no verified fee" in reasons["No Fee"]
        assert "deadline passed" in reasons["Expired"]

    def test_unknown_tier_defaults_to_target(self):
        festivals, _ = parse_candidates([fest("X", tier="wildcard")], TODAY)
        assert festivals[0].tier == "target"


class TestBudget:
    def test_never_exceeds_budget(self):
        profile = {"budget_for_submissions_usd": 200, "premiere_status": "none"}
        candidates = [fest(f"Fest {i}", fee=75) for i in range(10)]
        plan = build_plan(profile, candidates, TODAY)
        assert plan.committed_cents <= 20000
        assert plan.remaining_cents >= 0

    def test_zero_budget_plans_nothing(self):
        plan = build_plan(
            {"budget_for_submissions_usd": 0, "premiere_status": "none"},
            [fest("Fest", fee=50)],
            TODAY,
        )
        assert plan.submissions == []
        assert "No fundable submissions" in plan.to_markdown()

    def test_unaffordable_candidates_are_reported(self):
        plan = build_plan(
            {"budget_for_submissions_usd": 60, "premiere_status": "none"},
            [fest("Cheap", fee=50), fest("Expensive", fee=500)],
            TODAY,
        )
        assert dict(plan.excluded)["Expensive"] == "over budget"


class TestTiering:
    def test_builds_a_balanced_slate(self):
        profile = {"budget_for_submissions_usd": 2000, "premiere_status": "none"}
        candidates = (
            [fest(f"Top {i}", tier="top", fee=60) for i in range(5)]
            + [fest(f"Mid {i}", tier="mid", fee=45) for i in range(8)]
            + [fest(f"Niche {i}", tier="niche", fee=25) for i in range(6)]
        )
        counts = build_plan(profile, candidates, TODAY).tier_counts()
        assert 2 <= counts["reach"] <= 3
        assert 4 <= counts["target"] <= 6
        assert 3 <= counts["safe"] <= 4

    def test_cheap_but_poor_fit_is_not_funded_with_leftover_budget(self):
        """Money left over is not a reason to enter a festival the film doesn't suit."""
        profile = {"budget_for_submissions_usd": 5000, "premiere_status": "none"}
        candidates = [fest(f"Mid {i}", tier="mid", fee=45, fit_score=0.8) for i in range(4)]
        candidates += [fest(f"Safe {i}", tier="niche", fee=25, fit_score=0.7) for i in range(3)]
        candidates.append(fest("Wrong Genre", tier="niche", fee=5, fit_score=0.2))
        plan = build_plan(profile, candidates, TODAY)
        assert "Wrong Genre" not in [s.festival.name for s in plan.submissions]
        assert "fit too weak" in dict(plan.excluded)["Wrong Genre"]
        assert plan.remaining_cents > 0  # budget was available; fit was the blocker

    def test_higher_fit_score_wins_within_tier(self):
        profile = {"budget_for_submissions_usd": 100, "premiere_status": "none"}
        candidates = [
            fest("Weak", tier="mid", fee=45, fit_score=0.1),
            fest("Strong", tier="mid", fee=45, fit_score=0.9),
        ]
        names = [s.festival.name for s in build_plan(profile, candidates, TODAY).submissions]
        assert names[0] == "Strong"


class TestPremiereRules:
    def test_only_one_festival_gets_the_world_premiere(self):
        profile = {"budget_for_submissions_usd": 1000, "premiere_status": "world"}
        candidates = [
            fest("Sundance-like", tier="top", fee=65, premiere_requirement="world premiere"),
            fest("Berlin-like", tier="top", fee=60, premiere_requirement="world premiere"),
        ]
        plan = build_plan(profile, candidates, TODAY)
        assert plan.premiere_target is not None
        contingent = [s for s in plan.submissions if s.note and "contingent" in s.note]
        assert len(contingent) == 1

    def test_films_without_a_premiere_skip_premiere_gated_festivals(self):
        profile = {"budget_for_submissions_usd": 1000, "premiere_status": "none-remaining"}
        candidates = [
            fest("Gated", tier="top", fee=65, premiere_requirement="world premiere"),
            fest("Open", tier="mid", fee=45),
        ]
        plan = build_plan(profile, candidates, TODAY)
        assert [s.festival.name for s in plan.submissions] == ["Open"]
        assert "world premiere" in dict(plan.excluded)["Gated"]


class TestOutput:
    def test_plan_is_deadline_ordered_and_flags_urgency(self):
        profile = {"budget_for_submissions_usd": 500, "premiere_status": "none"}
        candidates = [
            fest("Later", deadline="2026-12-01", fee=45),
            fest("Imminent", deadline="2026-08-10", fee=45),
        ]
        plan = build_plan(profile, candidates, TODAY)
        assert [s.festival.name for s in plan.submissions] == ["Imminent", "Later"]
        assert plan.submissions[0].urgent is True
        assert plan.submissions[1].urgent is False

    def test_markdown_reports_budget_math(self):
        plan = build_plan(
            {"budget_for_submissions_usd": 600, "premiere_status": "none"},
            [fest("Fest", fee=45)],
            TODAY,
        )
        md = plan.to_markdown()
        assert format_cents(plan.committed_cents) in md
        assert "| Fest |" in md
