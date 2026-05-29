"""Tests for docforge.scripts.eval_search pure functions."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
import yaml

from docforge.scripts.eval_search import (
    QueryResult,
    _load_ground_truth,
    score_query,
    summarize,
)


class TestScoreQuery:
    def test_hits_at_rank_1(self):
        assert score_query(["HTTP error handling guidelines", "other"], "HTTP error") == 1

    def test_hits_at_rank_3(self):
        titles = ["other1", "other2", "HTTP error handling guidelines", "other3"]
        assert score_query(titles, "HTTP error") == 3

    def test_no_match_returns_none(self):
        assert score_query(["foo", "bar"], "baz") is None

    def test_case_insensitive_match(self):
        assert score_query(["HTTP ERROR HANDLING"], "http error") == 1

    def test_empty_title_list_returns_none(self):
        assert score_query([], "anything") is None

    def test_expected_substring_as_whole_word_substring(self):
        titles = ["Organization Lifecycle — team responsibilities"]
        assert score_query(titles, "Organization Lifecycle") == 1


def _qr(query: str, expected: str, match_rank: int | None) -> QueryResult:
    return QueryResult(
        query=query,
        expected_substring=expected,
        returned_titles=[],
        returned_scores=[],
        match_rank=match_rank,
    )


class TestSummarize:
    def test_empty_results_returns_zero_metrics(self):
        out = summarize([], k=5)
        assert out == {"queries": 0, "recall@1": 0.0, "recall@5": 0.0, "mrr": 0.0}

    def test_all_hits_at_rank_1(self):
        results = [_qr("q1", "x", 1), _qr("q2", "x", 1)]
        out = summarize(results, k=5)
        assert out["queries"] == 2
        assert out["recall@1"] == 1.0
        assert out["recall@5"] == 1.0
        assert out["mrr"] == pytest.approx(1.0)

    def test_mixed_ranks(self):
        # 4 queries: ranks 1, 3, None, 5. k=5.
        # recall@1 = 1/4, recall@5 = 3/4, mrr = (1/1 + 1/3 + 0 + 1/5) / 4
        results = [
            _qr("q1", "x", 1),
            _qr("q2", "x", 3),
            _qr("q3", "x", None),
            _qr("q4", "x", 5),
        ]
        out = summarize(results, k=5)
        assert out["queries"] == 4
        assert out["recall@1"] == pytest.approx(0.25)
        assert out["recall@5"] == pytest.approx(0.75)
        assert out["mrr"] == pytest.approx((1 + 1 / 3 + 0 + 1 / 5) / 4)

    def test_recall_key_uses_k(self):
        out = summarize([_qr("q", "x", 1)], k=10)
        assert "recall@10" in out
        assert "recall@5" not in out


class TestLoadGroundTruth:
    def test_valid_file(self, tmp_path: Path):
        p = tmp_path / "gt.yml"
        p.write_text(
            "queries:\n"
            "  - q: 'how do retries work'\n"
            "    expected_title_contains: 'HTTP error handling'\n",
            encoding="utf-8",
        )
        out = _load_ground_truth(p)
        assert len(out) == 1
        assert out[0]["q"] == "how do retries work"

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            _load_ground_truth(tmp_path / "nope.yml")

    def test_empty_queries_raises(self, tmp_path: Path):
        p = tmp_path / "gt.yml"
        p.write_text("queries: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing or empty"):
            _load_ground_truth(p)

    def test_missing_required_keys_raises(self, tmp_path: Path):
        p = tmp_path / "gt.yml"
        p.write_text("queries:\n  - q: 'only q key'\n", encoding="utf-8")
        with pytest.raises(ValueError, match="must have"):
            _load_ground_truth(p)


class TestDirectMode:
    def test_cli_rejects_both_api_url_and_direct(self):
        """--api-url and --direct are mutually exclusive."""
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "docforge.scripts.eval_search",
                "--api-url",
                "https://example.test",
                "--direct",
                "--ground-truth",
                "nonexistent.yml",
                "--user",
                "u",
                "--team",
                "t",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert (
            "mutually exclusive" in (result.stderr + result.stdout).lower()
            or "--direct" in result.stderr
        )

    def test_cli_rejects_neither_api_url_nor_direct(self):
        """At least one of --api-url or --direct must be given."""
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "docforge.scripts.eval_search",
                "--ground-truth",
                "nonexistent.yml",
                "--user",
                "u",
                "--team",
                "t",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert (
            "required" in (result.stderr + result.stdout).lower()
            or "--api-url" in result.stderr
            or "--direct" in result.stderr
        )


class TestDirectRequiresRemoteEmbedder:
    @pytest.mark.asyncio
    async def test_direct_mode_fails_fast_when_embedder_url_empty(self, monkeypatch):
        """--direct mode must not silently fall through to local Qwen-4B
        download. When embedder_url is unset, raise SystemExit with a
        message that tells the user how to fix it."""
        from types import SimpleNamespace

        from docforge.scripts.eval_search import run_queries_direct

        empty_url_settings = SimpleNamespace(
            embedder_url="",  # the bad state we're guarding against
            database_url="postgresql://fake",
            embedder_token=SimpleNamespace(get_secret_value=lambda: ""),
        )
        monkeypatch.setattr("docforge.config.Settings", lambda: empty_url_settings)

        with pytest.raises(SystemExit) as exc_info:
            await run_queries_direct(
                ground_truth=[{"q": "q", "expected_title_contains": "x"}],
                user_name="u",
                team_name="t",
                area_name="a",
                k=5,
                debug=False,
            )
        assert "EMBEDDER_URL" in str(exc_info.value)


class TestDirectVsHttpParity:
    @pytest.mark.asyncio
    async def test_direct_mode_matches_http_for_same_fixtures(self, monkeypatch):
        """Both code paths must produce identical QueryResults on the same
        row payload. After Task 4's refactor /search and run_queries_direct
        share perform_search; the only places they could diverge are in the
        row -> QueryResult adaptation logic on each side. This test catches
        any future drift between them by running both paths and asserting
        their QueryResult lists are equal."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        import httpx

        from docforge.scripts.eval_search import run_queries, run_queries_direct
        from tests.conftest import FakeEmbedder, fake_settings

        # Fixed payload that both paths must surface identically.
        row = {
            "text": "Markus is VP Engineering.",
            "section_title": "Engineering",
            "source_title": "Departments in Product Development",
            "source_url": "https://wiki/depts",
            "source_tags": ["org"],
            "similarity": 0.85,
            "dense_rank": 1,
            "sparse_rank": 1,
        }
        ground_truth = [
            {"q": "who is Markus Koelmans", "expected_title_contains": "Departments in Product"}
        ]

        # --- HTTP path setup: MockTransport returns the same row from /search ---
        def http_handler(request: httpx.Request) -> httpx.Response:
            # /search response envelope matches the FastAPI shape
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "text": row["text"],
                            "section_title": row["section_title"],
                            "source_title": row["source_title"],
                            "source_url": row["source_url"],
                            "source_tags": row["source_tags"],
                            "similarity": row["similarity"],
                        }
                    ],
                    "query": ground_truth[0]["q"],
                    "count": 1,
                },
            )

        mock_transport = httpx.MockTransport(http_handler)

        # run_queries constructs httpx.AsyncClient(timeout=30.0) without a transport
        # argument. Patch the constructor to inject our MockTransport for every
        # client built inside run_queries.
        original_async_client = httpx.AsyncClient

        def patched_async_client(*args, **kwargs):
            kwargs["transport"] = mock_transport
            return original_async_client(*args, **kwargs)

        monkeypatch.setattr("httpx.AsyncClient", patched_async_client)

        # --- Direct path setup: stub perform_search to return the same row ---
        async def fake_perform_search(*, req, settings, pool, embedder):
            return [row]

        monkeypatch.setattr("docforge.api.perform_search", fake_perform_search)

        # Settings/Pool/Embedder construction in run_queries_direct — patch the
        # source modules since run_queries_direct imports them lazily.
        def patched_settings():
            s = fake_settings()
            s.embedder_url = "https://embedder.example.test"
            s.embedder_token = SimpleNamespace(get_secret_value=lambda: "fake-token")
            return s

        monkeypatch.setattr("docforge.config.Settings", patched_settings)

        async def fake_create_pool(*args, **kwargs):
            return MagicMock(close=AsyncMock())

        monkeypatch.setattr("asyncpg.create_pool", fake_create_pool)
        monkeypatch.setattr(
            "docforge.processors.embedder.Embedder.from_settings",
            lambda settings: FakeEmbedder(),
        )

        # --- Run BOTH paths ---
        http_results = await run_queries(
            api_url="https://example.test",
            ground_truth=ground_truth,
            user_name="u",
            team_name="t",
            area_name="a",
            k=5,
            audience=None,
        )
        direct_results = await run_queries_direct(
            ground_truth=ground_truth,
            user_name="u",
            team_name="t",
            area_name="a",
            k=5,
            debug=False,
        )

        # --- Assert parity across the full QueryResult shape ---
        assert len(http_results) == len(direct_results) == 1
        h, d = http_results[0], direct_results[0]
        assert h.query == d.query
        assert h.expected_substring == d.expected_substring
        assert h.returned_titles == d.returned_titles
        assert h.returned_scores == d.returned_scores
        assert h.match_rank == d.match_rank
        # Sanity check: both produced the expected match at rank 1
        assert h.returned_titles == ["Departments in Product Development"]
        assert h.match_rank == 1


class TestFormatReportDebug:
    def test_debug_ranks_appear_in_report(self):
        from docforge.scripts.eval_search import QueryResult, format_report, summarize

        results = [
            QueryResult(
                query="who is in cloudcl",
                expected_substring="Team Cloud Customer Lifecycle",
                returned_titles=[
                    "Application Catalog - Team CloudCL",
                    "Team Cloud Customer Lifecycle ♻",
                ],
                returned_scores=[0.04, 0.038],
                match_rank=2,
                returned_dense_ranks=[1, 4],
                returned_sparse_ranks=[3, 1],
            )
        ]
        report = format_report(results, summarize(results, k=5), k=5)
        assert "d#1 s#3" in report
        assert "d#4 s#1" in report


def test_main_rejects_empty_audience(monkeypatch, tmp_path, capsys):
    """Empty --audience triggers argparse type-callable rejection (SystemExit code 2)."""
    gt = tmp_path / "gt.yml"
    gt.write_text("queries: []\n")
    monkeypatch.setattr(
        "sys.argv",
        [
            "eval_search",
            "--api-url",
            "https://example.com",
            "--audience",
            "",
            "--ground-truth",
            str(gt),
            "--user",
            "alice",
            "--team",
            "ccl",
        ],
    )
    from docforge.scripts import eval_search

    with pytest.raises(SystemExit) as exc_info:
        eval_search.main()
    assert exc_info.value.code == 2, f"argparse error exits 2; got {exc_info.value.code}"


@pytest.mark.parametrize("empty_flag", ["--user", "--team"])
def test_main_rejects_empty_required_identity(monkeypatch, tmp_path, empty_flag):
    """Empty --user or --team triggers argparse type-callable rejection (SystemExit code 2)."""
    gt = tmp_path / "gt.yml"
    gt.write_text("queries: []\n")
    base_argv = [
        "eval_search",
        "--api-url",
        "https://example.com",
        "--ground-truth",
        str(gt),
        "--user",
        "alice",
        "--team",
        "ccl",
    ]
    argv = list(base_argv)
    idx = argv.index(empty_flag)
    argv[idx + 1] = ""
    monkeypatch.setattr("sys.argv", argv)
    from docforge.scripts import eval_search

    with pytest.raises(SystemExit) as exc_info:
        eval_search.main()
    assert exc_info.value.code == 2, f"{empty_flag}='' should exit 2; got {exc_info.value.code}"


def _run_with_timeout(target, args=(), kwargs=None, timeout=45):
    """Run `target(*args, **kwargs)` on a daemon thread; fail the test if it doesn't
    finish within `timeout` seconds. Cross-platform substitute for `pytest.mark.timeout`
    (pytest-timeout isn't in dev deps; signal.alarm is Unix-only).

    Returns whatever the target returns. Raises pytest.fail on timeout.
    """
    import threading

    kwargs = kwargs or {}
    box: dict[str, object] = {}

    def runner() -> None:
        try:
            box["rc"] = target(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - re-raise via box
            box["exc"] = exc

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        pytest.fail(f"target did not return within {timeout}s — pathological loopback wait")
    if "exc" in box:
        raise box["exc"]  # type: ignore[misc]
    return box.get("rc")


def test_main_returns_nonzero_when_all_queries_miss(monkeypatch, tmp_path, capsys):
    """If every query reports MISS (e.g., all 401 due to wrong audience),
    main() must return non-zero.

    Use --api-url pointing at an unreachable port; the HTTP layer will fail and every
    query records as MISS. The current contract returns 0 even then — this test should
    FAIL until the zero-hits exit-code fix is applied.

    Wrapped in a 45s watchdog (`_run_with_timeout`) so pathological loopback waits
    (e.g. on platforms where connect() to 127.0.0.1:1 hangs instead of fast-failing)
    can't stall CI. This stands in for `pytest.mark.timeout(45)` since pytest-timeout
    is not in the dev extras.
    """
    gt = tmp_path / "gt.yml"
    # Loader requires 'q' (not 'query') + 'expected_title_contains' on each entry.
    gt.write_text(
        "queries:\n"
        '  - q: "never-matches-anything-xyz"\n'
        '    expected_title_contains: "impossible-target-zzz"\n'
    )
    # NOTE: this test assumes a single-query ground truth so the 45s timeout
    # budget (httpx default connect_timeout=30s) doesn't blow on pathological
    # firewall behavior. If you expand the fixture, bump the timeout.
    with open(gt) as f:
        assert len(yaml.safe_load(f)["queries"]) == 1
    monkeypatch.setattr(
        "sys.argv",
        [
            "eval_search",
            "--api-url",
            "http://127.0.0.1:1",  # unreachable
            "--ground-truth",
            str(gt),
            "--user",
            "alice",
            "--team",
            "ccl",
            "--k",
            "5",
        ],
    )
    from docforge.scripts import eval_search

    rc = _run_with_timeout(eval_search.main, timeout=45)
    assert rc == 1, f"All-MISS eval must return exit code 1; got {rc}"
    captured = capsys.readouterr()
    assert "queries hit" in captured.err, (
        f"Expected 'queries hit' in stderr message; got: {captured.err!r}"
    )
    assert "10%" in captured.err, "Stderr should mention the 10% threshold from the new guard"


@pytest.mark.parametrize("placeholder", ["<you>", "<your-team>", "<your-area>", "<api-audience>"])
def test_main_rejects_angle_bracket_placeholder(monkeypatch, tmp_path, placeholder):
    """Each placeholder literal triggers argparse rejection independently."""
    gt = tmp_path / "gt.yml"
    gt.write_text("queries: []\n")
    monkeypatch.setattr(
        "sys.argv",
        [
            "eval_search",
            "--api-url",
            "https://example.com",
            "--ground-truth",
            str(gt),
            "--user",
            placeholder,
            "--team",
            "ccl",
        ],
    )
    from docforge.scripts import eval_search

    with pytest.raises(SystemExit) as exc_info:
        eval_search.main()
    assert exc_info.value.code == 2, f"placeholder {placeholder!r} should exit 2"


def test_non_empty_str_strips_whitespace():
    """_non_empty_str returns the trimmed value (not the original with surrounding whitespace)."""
    from docforge.scripts.eval_search import _non_empty_str

    assert _non_empty_str("  alice  ") == "alice"
    assert _non_empty_str("\talice\n") == "alice"
    assert _non_empty_str("alice") == "alice"  # no-op on already-clean input


def test_non_empty_str_rejects_none():
    """_non_empty_str rejects None explicitly — defensive for any non-argparse caller."""
    from docforge.scripts.eval_search import _non_empty_str

    with pytest.raises(argparse.ArgumentTypeError, match="must not be None"):
        _non_empty_str(None)  # type: ignore[arg-type]


def test_main_rejects_empty_area(monkeypatch, tmp_path):
    """Empty --area triggers argparse rejection.

    Closes the asymmetry vs --user / --team / --audience.
    """
    gt = tmp_path / "gt.yml"
    gt.write_text("queries: []\n")
    monkeypatch.setattr(
        "sys.argv",
        [
            "eval_search",
            "--api-url",
            "https://example.com",
            "--ground-truth",
            str(gt),
            "--user",
            "alice",
            "--team",
            "ccl",
            "--area",
            "",
        ],
    )
    from docforge.scripts import eval_search

    with pytest.raises(SystemExit) as exc_info:
        eval_search.main()
    assert exc_info.value.code == 2
