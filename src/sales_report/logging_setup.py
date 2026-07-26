"""構造化ログ(処理件数・スキップ件数・所要時間)。

障害時に「いつ・どの入力で・何件処理し・何件スキップし・どれだけ時間が
かかったか」を後から追跡できるよう、実行結果のサマリをJSON1行として
標準エラー出力に書き出す。人間が読むログ(typer.echo)とは別に、
機械可読なログを両立させる狙い。
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass
from typing import TextIO


@dataclass(frozen=True, slots=True)
class RunSummary:
    """1回の実行結果のサマリ。"""

    input_path: str
    files_found: int
    valid_rows: int
    skipped_rows: int
    file_errors: int
    duration_seconds: float
    exit_code: int


def build_run_summary(
    *,
    input_path: str,
    files_found: int,
    valid_rows: int,
    skipped_rows: int,
    file_errors: int,
    started_at: float,
    exit_code: int,
) -> RunSummary:
    """started_at(time.monotonic()の開始時刻)から所要時間を算出してRunSummaryを組み立てる。"""
    duration = time.monotonic() - started_at
    return RunSummary(
        input_path=input_path,
        files_found=files_found,
        valid_rows=valid_rows,
        skipped_rows=skipped_rows,
        file_errors=file_errors,
        duration_seconds=round(duration, 6),
        exit_code=exit_code,
    )


def log_run_summary(summary: RunSummary, stream: TextIO | None = None) -> None:
    """構造化ログ(JSON Lines形式)を1行出力する。既定では標準エラー出力へ。"""
    target = stream if stream is not None else sys.stderr
    print(json.dumps(asdict(summary), ensure_ascii=False), file=target)
