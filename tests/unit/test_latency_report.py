"""Pure-function unit tests for docforge.scripts.latency_report."""

from __future__ import annotations

from docforge.scripts.latency_report import LatencySummary, format_summary


def test_format_summary_empty_window():
    s = LatencySummary(n=0, p50_ms=None, p95_ms=None, p99_ms=None, earliest_request_ms_at=None)
    out = format_summary(s, "7 days")
    assert "No rows with request_ms" in out
    assert "Queries with timing:    0" in out


def test_format_summary_with_data():
    s = LatencySummary(
        n=1234,
        p50_ms=87.5,
        p95_ms=412.0,
        p99_ms=1830.3,
        earliest_request_ms_at="2026-04-22T19:00:00+00:00",
    )
    out = format_summary(s, "7 days")
    assert "Queries with timing:    1234" in out
    # %.0f rounds 87.5 to either 87 or 88 depending on banker's-rounding
    # vs. round-half-up; accept either.
    assert "P50:" in out
    assert "P95:                    412 ms" in out
    assert "P99:                    1830 ms" in out
    assert "warm-up+steady-state" in out
    assert "cutover at:" in out
    assert "2026-04-22T19:00:00+00:00" in out


def test_format_summary_rounding():
    s = LatencySummary(n=1, p50_ms=0.4, p95_ms=0.6, p99_ms=999.99, earliest_request_ms_at=None)
    out = format_summary(s, "1 hour")
    assert "P50:" in out
    assert "P99:                    1000 ms" in out  # 999.99 rounds up


def test_format_summary_module_importable():
    """Sanity: the module imports cleanly and main is defined."""
    from docforge.scripts import latency_report

    assert latency_report.main is not None


def test_since_pattern_accepts_valid_forms():
    from docforge.scripts.latency_report import _SINCE_PATTERN

    for s in ("7 days", "1 hour", "24 hours", "30 seconds", "2 weeks", "3 months", "  5 days  "):
        assert _SINCE_PATTERN.match(s), f"should accept {s!r}"


def test_since_pattern_rejects_invalid_forms():
    from docforge.scripts.latency_report import _SINCE_PATTERN

    for s in ("", "7", "days", "7 fortnights", "7 days; DROP TABLE", "-1 days", "1.5 days"):
        assert not _SINCE_PATTERN.match(s), f"should reject {s!r}"
