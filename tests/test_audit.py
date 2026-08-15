"""The rubric that decides whether ReelRelay survives Week 2.

These tests pin the grading logic, not the research: they feed known-good and
known-bad candidate lists through audit_run() and assert the verdict it earns.
"""

import json
from datetime import date

import pytest

from reelrelay.audit import (
    GO,
    MARGINAL,
    NO_GO,
    UNVALIDATED,
    audit_run,
    bucket_reason,
    host_of,
    suite_verdict,
)
from reelrelay.strategy import parse_candidates
from reelrelay.tools import FIXTURE_PATH

# The fixture's deadlines are fictional but fixed; pin today so the suite does
# not start failing when real time drifts past them.
TODAY = date(2026, 8, 12)
PROFILE = {
    "title": "Night Shift at the Lumiere",
    "budget_for_submissions_usd": 600,
    "premiere_status": "world",
}


def fixture_candidates():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["results"]


def fixture_urls():
    return [c["source_url"] for c in fixture_candidates()]


def audit_fixture(**overrides):
    kwargs = {
        "parallel_calls": 3,
        "parallel_results": 12,
        "synthetic": False,
        "today": TODAY,
    }
    kwargs.update(overrides)
    return audit_run(PROFILE, fixture_candidates(), fixture_urls(), **kwargs)


class TestHealthyRun:
    def test_well_formed_research_earns_a_go(self):
        audit = audit_fixture()
        assert audit.verdict == GO
        assert audit.candidate_count == 12
        assert audit.usable_count == 10
        assert audit.tier_minimums_met
        assert audit.plan_size >= 6

    def test_unusable_candidates_are_attributed_to_a_cause(self):
        audit = audit_fixture()
        assert audit.reason_counts["missing_deadline"] == 1
        assert audit.reason_counts["deadline_passed"] == 1
        assert "other" not in audit.reason_counts

    def test_report_renders_without_non_ascii(self):
        """Reports print to Windows cp1252 consoles."""
        audit = audit_fixture()
        audit.to_markdown().encode("cp1252")
        json.dumps(audit.to_dict())


class TestSyntheticDataCannotPass:
    def test_fixture_run_is_unvalidated_however_good_the_numbers(self):
        audit = audit_fixture(synthetic=True)
        assert audit.verdict == UNVALIDATED
        assert "fixture" in " ".join(audit.reasons).lower()

    def test_the_underlying_metrics_are_still_reported(self):
        """UNVALIDATED must not mean unmeasured -- the harness is still testable."""
        audit = audit_fixture(synthetic=True)
        assert audit.usable_count == 10
        assert audit.tier_minimums_met


class TestFabricationDetection:
    def test_a_source_url_absent_from_search_results_is_ungrounded(self):
        candidates = fixture_candidates()
        candidates[0]["source_url"] = "https://invented-festival.example.com/submit"
        audit = audit_run(PROFILE, candidates, fixture_urls(), parallel_calls=3, today=TODAY)
        assert candidates[0]["name"] in audit.ungrounded
        assert audit.grounded_count == 11

    def test_a_missing_source_url_counts_against_grounding(self):
        candidates = fixture_candidates()
        candidates[0]["source_url"] = None
        audit = audit_run(PROFILE, candidates, fixture_urls(), parallel_calls=3, today=TODAY)
        assert audit.missing_source_url == 1
        assert candidates[0]["name"] in audit.ungrounded

    def test_mostly_invented_research_is_a_no_go_even_with_a_full_plan(self):
        candidates = fixture_candidates()
        for candidate in candidates:
            candidate["source_url"] = f"https://made-up.example.com/{candidate['name']}"
        audit = audit_run(PROFILE, candidates, fixture_urls(), parallel_calls=3, today=TODAY)
        assert audit.plan_size > 0  # the plan looks fine; the sourcing is not
        assert audit.verdict == NO_GO
        assert any("inventing" in r for r in audit.reasons)

    def test_grounding_ignores_www_and_case(self):
        assert host_of("https://WWW.Festival.org/submit") == "festival.org"
        assert host_of("festival.org/x") == "festival.org"
        assert host_of(None) is None
        assert host_of("") is None


class TestFailureModes:
    def test_unverifiable_deadlines_are_a_no_go(self):
        candidates = fixture_candidates()
        for candidate in candidates:
            candidate["submission_deadline"] = None
        audit = audit_run(PROFILE, candidates, fixture_urls(), parallel_calls=3, today=TODAY)
        assert audit.verdict == NO_GO
        assert audit.reason_counts["missing_deadline"] == len(candidates)
        assert audit.usable_count == 0

    def test_a_scout_that_never_searched_fails_the_track_requirement(self):
        audit = audit_fixture(parallel_calls=0)
        assert audit.verdict == NO_GO
        assert any("never called parallel_search" in r for r in audit.reasons)

    def test_search_errors_void_the_verdict_rather_than_condemning_the_data(self):
        """A partial measurement must not be graded NO-GO."""
        audit = audit_fixture(search_errors=["Parallel search failed: 401"])
        assert audit.verdict == UNVALIDATED
        assert "incomplete" in " ".join(audit.reasons)

    def test_a_crashed_run_is_unvalidated_not_a_no_go(self):
        """A dropped network is not evidence about the festival circuit."""
        audit = audit_run(
            {"title": "Whatever"},
            [],
            [],
            search_errors=["run failed: getaddrinfo failed"],
            aborted=True,
            today=TODAY,
        )
        assert audit.verdict == UNVALIDATED
        assert "did not complete" in " ".join(audit.reasons)

    def test_thin_but_workable_research_is_marginal_not_fatal(self):
        """Nine usable candidates fill the tier minimums but miss the yield bar."""
        candidates = [c for c in fixture_candidates() if c["submission_deadline"]]
        urls = [c["source_url"] for c in candidates]
        audit = audit_run(PROFILE, candidates, urls, parallel_calls=3, today=TODAY)
        assert audit.verdict == MARGINAL
        assert any("candidates emitted" in r for r in audit.reasons)

    def test_empty_research_is_a_no_go_without_crashing(self):
        audit = audit_run(PROFILE, [], [], parallel_calls=2, today=TODAY)
        assert audit.verdict == NO_GO
        assert audit.candidate_count == 0
        assert audit.usable_rate == 0.0
        assert audit.groundedness_rate == 0.0


class TestScoutOutputHygiene:
    def test_absent_fit_scores_are_counted(self):
        """Without fit_score the planner's ranking silently becomes cheapest-first."""
        candidates = fixture_candidates()
        for candidate in candidates:
            candidate.pop("fit_score")
        audit = audit_run(PROFILE, candidates, fixture_urls(), parallel_calls=3, today=TODAY)
        assert audit.missing_fit_scores == len(candidates)

    def test_duplicate_festivals_are_flagged(self):
        candidates = fixture_candidates()
        candidates.append(dict(candidates[0]))
        audit = audit_run(PROFILE, candidates, fixture_urls(), parallel_calls=3, today=TODAY)
        assert candidates[0]["name"] in audit.duplicate_names

    def test_unrecognized_tier_labels_are_surfaced(self):
        """TIER_MAP silently treats unknown tiers as 'target'; say so out loud."""
        candidates = fixture_candidates()
        candidates[0]["tier"] = "A-list"
        audit = audit_run(PROFILE, candidates, fixture_urls(), parallel_calls=3, today=TODAY)
        assert "a-list" in audit.unmapped_tiers


class TestReasonBuckets:
    @pytest.mark.parametrize(
        "candidate",
        [
            {"name": "No deadline", "fee_usd": 40},
            {"name": "No fee", "submission_deadline": "2026-09-01"},
            {"name": "Closed", "submission_deadline": "2020-01-01", "fee_usd": 40},
        ],
    )
    def test_every_parser_rejection_maps_to_a_named_bucket(self, candidate):
        """Guards the coupling: a new reason in strategy.py must be taught here."""
        _, skipped = parse_candidates([candidate], TODAY)
        assert skipped, "expected this candidate to be rejected"
        assert bucket_reason(skipped[0][1]) != "other"


class TestSuiteVerdict:
    def test_the_worst_profile_sets_the_suite_verdict(self):
        good = audit_fixture()
        bad = audit_fixture(parallel_calls=0)
        verdict, notes = suite_verdict([good, bad])
        assert verdict == NO_GO
        assert len(notes) == 2

    def test_all_go_means_go(self):
        verdict, _ = suite_verdict([audit_fixture(), audit_fixture()])
        assert verdict == GO

    def test_no_profiles_is_unvalidated(self):
        verdict, _ = suite_verdict([])
        assert verdict == UNVALIDATED
