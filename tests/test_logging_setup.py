"""logging_setup.py のテスト。"""

from __future__ import annotations

import io
import json
import time

from sales_report.logging_setup import build_run_summary, log_run_summary


def test_build_run_summary_fields() -> None:
    started_at = time.monotonic()
    summary = build_run_summary(
        input_path="./data",
        files_found=2,
        valid_rows=10,
        skipped_rows=3,
        file_errors=1,
        started_at=started_at,
        exit_code=0,
    )
    assert summary.input_path == "./data"
    assert summary.files_found == 2
    assert summary.valid_rows == 10
    assert summary.skipped_rows == 3
    assert summary.file_errors == 1
    assert summary.exit_code == 0
    assert summary.duration_seconds >= 0.0


def test_log_run_summary_writes_valid_json_line() -> None:
    started_at = time.monotonic()
    summary = build_run_summary(
        input_path="./data",
        files_found=1,
        valid_rows=5,
        skipped_rows=0,
        file_errors=0,
        started_at=started_at,
        exit_code=0,
    )
    stream = io.StringIO()
    log_run_summary(summary, stream=stream)

    line = stream.getvalue().strip()
    parsed = json.loads(line)
    assert parsed["valid_rows"] == 5
    assert parsed["exit_code"] == 0


def test_log_run_summary_defaults_to_stderr(capsys) -> None:  # type: ignore[no-untyped-def]
    started_at = time.monotonic()
    summary = build_run_summary(
        input_path="./data",
        files_found=0,
        valid_rows=0,
        skipped_rows=0,
        file_errors=0,
        started_at=started_at,
        exit_code=1,
    )
    log_run_summary(summary)
    captured = capsys.readouterr()
    assert captured.out == ""
    parsed = json.loads(captured.err.strip())
    assert parsed["exit_code"] == 1
