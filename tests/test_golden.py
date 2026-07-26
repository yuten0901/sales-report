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
)
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
