"""Guards on the seams between the agents, the callback, and the fixture."""

import json

from reelrelay.agent import compute_plan, root_agent
from reelrelay.strategy import loads_loose
from reelrelay.tools import FIXTURE_PATH, _offline_results


class FakeCallbackContext:
    """Stands in for ADK's CallbackContext, which only needs .state here."""

    def __init__(self, state):
        self.state = state


PROFILE = json.dumps(
    {"budget_for_submissions_usd": 600, "premiere_status": "world", "title": "Test Film"}
)


def fixture_candidates():
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return data["results"]


class TestPipelineShape:
    def test_four_stages_in_order(self):
        assert [a.name for a in root_agent.sub_agents] == [
            "intake",
            "scout",
            "strategist",
            "pitch",
        ]

    def test_each_stage_publishes_state_the_next_one_reads(self):
        keys = {a.name: a.output_key for a in root_agent.sub_agents}
        assert keys == {
            "intake": "film_profile",
            "scout": "festival_research",
            "strategist": "submission_plan",
            "pitch": "sample_pitch",
        }

    def test_scout_owns_the_parallel_tool(self):
        scout = next(a for a in root_agent.sub_agents if a.name == "scout")
        assert any(
            getattr(t, "__name__", getattr(t, "name", "")) == "parallel_search"
            for t in scout.tools
        )


class TestComputePlanCallback:
    def test_populates_computed_plan_from_fenced_json(self):
        state = {
            "film_profile": f"```json\n{PROFILE}\n```",
            "festival_research": "```json\n" + json.dumps(fixture_candidates()) + "\n```",
        }
        compute_plan(FakeCallbackContext(state))
        assert "Computed submission plan" in state["computed_plan"]
        assert "world-premiere target" in state["computed_plan"].lower()

    def test_always_sets_the_key_even_when_research_is_garbage(self):
        """The strategist's instruction interpolates {computed_plan}; it must exist."""
        for research in (None, "the model rambled instead of emitting JSON", "[]"):
            state = {"film_profile": PROFILE, "festival_research": research}
            compute_plan(FakeCallbackContext(state))
            assert state["computed_plan"]
            assert "Do not invent festivals." in state["computed_plan"]

    def test_survives_a_malformed_profile(self):
        state = {
            "film_profile": "not json",
            "festival_research": json.dumps(fixture_candidates()),
        }
        compute_plan(FakeCallbackContext(state))
        assert state["computed_plan"]


class TestOfflineFixture:
    def test_offline_mode_returns_usable_candidates(self, monkeypatch):
        monkeypatch.setenv("REELRELAY_OFFLINE", "1")
        from reelrelay.tools import parallel_search

        out = parallel_search("objective", ["query"])
        assert out["status"] == "ok"
        assert out["offline_fixture"] is True
        assert len(out["results"]) >= 10

    def test_fixture_is_labelled_synthetic(self):
        """Fictional deadlines must never be mistakable for real research."""
        out = _offline_results()
        assert "SYNTHETIC" in out["warning"]
        raw = FIXTURE_PATH.read_text(encoding="utf-8")
        assert "SYNTHETIC TEST DATA" in raw
        assert "example.invalid" in raw  # reserved TLD, cannot resolve

    def test_fixture_exercises_the_engine_edge_cases(self):
        candidates = fixture_candidates()
        assert any(c["submission_deadline"] is None for c in candidates)
        assert any(c["submission_deadline"] == "2026-03-15" for c in candidates)
        assert any(c["premiere_requirement"] for c in candidates)

    def test_excerpts_round_trip_back_into_candidates(self):
        """The scout reads excerpts; they must parse back into planner input."""
        out = _offline_results()
        parsed = loads_loose(out["results"][0]["excerpts"][0])
        assert parsed["name"] and parsed["fee_usd"]
