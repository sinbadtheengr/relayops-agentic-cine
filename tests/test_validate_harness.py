"""The plumbing between an ADK run and the rubric.

The harness itself can't be exercised end-to-end without live keys, so the two
parts that would otherwise stay untested until then -- reading tool responses
off the event stream, and refusing to grade a run that can't be graded honestly
-- are pinned here.
"""

import json

from reelrelay.validate import SUITE, RunCapture, check_environment

KEYS = {"PARALLEL_API_KEY": "pk-test", "GOOGLE_API_KEY": "gk-test"}


def set_keys(monkeypatch, **overrides):
    env = {**KEYS, **overrides}
    for name, value in env.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    monkeypatch.delenv("REELRELAY_OFFLINE", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)


class TestRunCapture:
    def test_collects_urls_from_a_successful_search(self):
        capture = RunCapture()
        capture.note_response(
            {
                "status": "ok",
                "results": [
                    {"url": "https://a.example/submit", "title": "A"},
                    {"url": "https://b.example/rules", "title": "B"},
                ],
            }
        )
        assert capture.search_urls == ["https://a.example/submit", "https://b.example/rules"]
        assert capture.result_count == 2
        assert not capture.errors

    def test_unwraps_adk_result_envelopes(self):
        """ADK passes dict returns through but wraps other shapes in {'result': ...}."""
        capture = RunCapture()
        capture.note_response({"result": {"status": "ok", "results": [{"url": "https://x.example"}]}})
        assert capture.search_urls == ["https://x.example"]
        assert not capture.errors

    def test_search_failures_are_recorded_not_raised(self):
        capture = RunCapture()
        capture.note_response({"status": "error", "message": "401 unauthorized"})
        assert capture.errors == ["401 unauthorized"]
        assert capture.result_count == 0

    def test_fixture_responses_are_flagged_so_the_verdict_can_be_voided(self):
        capture = RunCapture()
        capture.note_response(
            {"status": "ok", "offline_fixture": True, "results": [{"url": "https://x.invalid"}]}
        )
        assert capture.saw_fixture is True

    def test_an_unreadable_response_becomes_an_error(self):
        capture = RunCapture()
        capture.note_response("the tool returned prose")
        assert capture.errors and "unreadable" in capture.errors[0]

    def test_calls_and_queries_are_counted(self):
        capture = RunCapture()
        capture.note_call({"search_queries": ["horror shorts 2026 deadline", "genre fests"]})
        capture.note_call({"search_queries": ["animation festival Mexico"]})
        assert capture.parallel_calls == 2
        assert len(capture.queries) == 3

    def test_results_without_urls_still_count(self):
        capture = RunCapture()
        capture.note_response({"status": "ok", "results": [{"title": "no url here"}]})
        assert capture.result_count == 1
        assert capture.search_urls == []


class TestEnvironmentGuard:
    def test_live_keys_pass(self, monkeypatch):
        set_keys(monkeypatch)
        assert check_environment(allow_offline=False) is None

    def test_offline_mode_is_refused_by_default(self, monkeypatch):
        set_keys(monkeypatch)
        monkeypatch.setenv("REELRELAY_OFFLINE", "1")
        message = check_environment(allow_offline=False)
        assert message and "fictional" in message

    def test_offline_mode_is_allowed_when_asked_for(self, monkeypatch):
        set_keys(monkeypatch)
        monkeypatch.setenv("REELRELAY_OFFLINE", "1")
        assert check_environment(allow_offline=True) is None

    def test_missing_parallel_key_blocks_the_run(self, monkeypatch):
        set_keys(monkeypatch, PARALLEL_API_KEY=None)
        message = check_environment(allow_offline=False)
        assert message and "PARALLEL_API_KEY" in message

    def test_missing_gemini_credentials_block_even_offline(self, monkeypatch):
        """The fixture replaces search, not the model."""
        set_keys(monkeypatch, GOOGLE_API_KEY=None)
        monkeypatch.setenv("REELRELAY_OFFLINE", "1")
        message = check_environment(allow_offline=True)
        assert message and "Gemini" in message

    def test_vertex_project_counts_as_gemini_credentials(self, monkeypatch):
        set_keys(monkeypatch, GOOGLE_API_KEY=None)
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "reelrelay-demo")
        assert check_environment(allow_offline=False) is None


class TestSuite:
    def test_every_suite_profile_exists_and_is_readable_json(self):
        assert len(SUITE) >= 4
        for path in SUITE:
            assert path.exists(), path
            json.loads(path.read_text(encoding="utf-8"))

    def test_profiles_carry_no_commentary_into_the_intake_prompt(self):
        """Whole files are fed to the model; keep them film, not notes."""
        for path in SUITE:
            profile = json.loads(path.read_text(encoding="utf-8"))
            assert not [k for k in profile if k.startswith("_")], path
