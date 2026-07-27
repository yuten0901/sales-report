"""ゴールデン(スナップショット)テスト。

固定の集計結果を毎回同じ形式でレンダリングできるかを、リポジトリに
チェックインした期待出力ファイル(data/golden/)と比較して検証する。
出力フォーマットの意図しない回帰(表示崩れ・列順の変化など)を検知する。
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

from sales_report.aggregate import (
    AggregationResult,
    DateSummary,
    ProductSummary,
    StoreSummary,
    aggregate,
)
from sales_report.loader import discover_csv_files, load_files
from sales_report.report import render_csv_report, render_markdown_report

_GOLDEN_DIR = Path(__file__).parent.parent / "data" / "golden"


def _fixed_result() -> AggregationResult:
    """複数店舗・複数商品・複数日付を含む固定の集計結果(再現性のため乱数を使わない)。"""
    return AggregationResult(
        by_store=(
            StoreSummary(store="新宿店", quantity=2, amount=Decimal("2400.00")),
            StoreSummary(store="渋谷店", quantity=5, amount=Decimal("4100.50")),
        ),
        by_product=(
            ProductSummary(product="商品A", quantity=4, amount=Decimal("4800.00")),
            ProductSummary(product="商品B", quantity=3, amount=Decimal("1700.50")),
        ),
        by_date=(
            DateSummary(date=dt.date(2026, 7, 1), quantity=3, amount=Decimal("3600.00")),
            DateSummary(date=dt.date(2026, 7, 2), quantity=4, amount=Decimal("2900.50")),
        ),
        total_quantity=7,
        total_amount=Decimal("6500.50"),
    )


def test_golden_csv_report_matches_reference() -> None:
    content = render_csv_report(_fixed_result())
    expected = (_GOLDEN_DIR / "report_sample.csv").read_text(encoding="utf-8")
    assert content == expected


def test_golden_markdown_report_matches_reference() -> None:
    content = render_markdown_report(_fixed_result())
    expected = (_GOLDEN_DIR / "report_sample.md").read_text(encoding="utf-8")
    assert content == expected


# --- フルパイプライン経由のゴールデン(FIX2-03/Codex#6) -----------------------
#
# 上記2テストは手製のAggregationResultを直接レンダラーへ渡すため、
# load_files→aggregateを経由した際のscale変化(小数桁数の変化)を検知できない。
# 実CSV(data/golden/pipeline_input.csv、小数を含む単価333.33を含む)を
# 実際のパイプライン全体に通し、期待出力と比較する。


def test_golden_pipeline_csv_report_matches_reference() -> None:
    files = discover_csv_files(_GOLDEN_DIR / "pipeline_input.csv")
    result = load_files(files)
    assert result.file_errors == ()
    assert result.row_errors == ()
    content = render_csv_report(aggregate(result.rows))
    expected = (_GOLDEN_DIR / "pipeline_output.csv").read_text(encoding="utf-8")
    assert content == expected


def test_golden_pipeline_markdown_report_matches_reference() -> None:
    files = discover_csv_files(_GOLDEN_DIR / "pipeline_input.csv")
    result = load_files(files)
    assert result.file_errors == ()
    assert result.row_errors == ()
    content = render_markdown_report(aggregate(result.rows))
    expected = (_GOLDEN_DIR / "pipeline_output.md").read_text(encoding="utf-8")
    assert content == expected
