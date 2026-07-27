"""report.py のテスト。

docs/test-design.md の BV-SEC-*(CSVインジェクション)に対応する。
原子的書き込みは tests/test_robustness.py で検証する。
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from sales_report.aggregate import (
    AggregationResult,
    DateSummary,
    ProductSummary,
    StoreSummary,
)
from sales_report.loader import FileError, LoadedRowError
from sales_report.models import RowError
from sales_report.report import (
    escape_markdown_cell,
    format_money,
    has_errors_to_report,
    render_csv_report,
    render_errors_csv,
    render_markdown_report,
    sanitize_csv_field,
    write_atomic,
)

# --- format_money(FIX2-03: 金額は常に小数2桁で出力する契約) -----------------


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        pytest.param(Decimal("100"), "100.00", id="integer-amount-padded"),
        pytest.param(Decimal("3600.5"), "3600.50", id="one-decimal-padded"),
        pytest.param(Decimal("3600.50"), "3600.50", id="already-two-decimals"),
        pytest.param(Decimal("302.997"), "303.00", id="three-decimals-rounded-half-up"),
        pytest.param(Decimal("0"), "0.00", id="zero"),
    ],
)
def test_format_money(amount: Decimal, expected: str) -> None:
    assert format_money(amount) == expected


# --- sanitize_csv_field (BV-SEC-01/02) --------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("=cmd|' /C calc'!A0", "'=cmd|' /C calc'!A0", id="BV-SEC-01-equals"),
        pytest.param("+1+1", "'+1+1", id="BV-SEC-01-plus"),
        pytest.param("-1+1", "'-1+1", id="BV-SEC-01-minus"),
        pytest.param("@SUM(A1:A10)", "'@SUM(A1:A10)", id="BV-SEC-01-at"),
        pytest.param("\t=cmd", "'\t=cmd", id="BV-SEC-01-tab"),
    ],
)
def test_sanitize_csv_field_neutralizes_dangerous_prefixes(value: str, expected: str) -> None:
    assert sanitize_csv_field(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("渋谷店", id="BV-SEC-02-japanese"),
        pytest.param("商品A", id="BV-SEC-02-product"),
        pytest.param("Store-1", id="BV-SEC-02-hyphen-not-at-start"),
        pytest.param("", id="BV-SEC-02-empty"),
    ],
)
def test_sanitize_csv_field_leaves_normal_values_untouched(value: str) -> None:
    assert sanitize_csv_field(value) == value


# --- escape_markdown_cell ----------------------------------------------------


def test_escape_markdown_cell_escapes_pipe() -> None:
    assert escape_markdown_cell("A|B") == "A\\|B"


def test_escape_markdown_cell_replaces_newlines_with_space() -> None:
    assert escape_markdown_cell("line1\nline2") == "line1 line2"
    assert escape_markdown_cell("line1\r\nline2") == "line1 line2"


# --- render_csv_report / render_markdown_report -----------------------------


def _sample_result() -> AggregationResult:
    return AggregationResult(
        by_store=(StoreSummary(store="渋谷店", quantity=3, amount=Decimal("3600")),),
        by_product=(ProductSummary(product="商品A", quantity=3, amount=Decimal("3600")),),
        by_date=(DateSummary(date=dt.date(2026, 7, 1), quantity=3, amount=Decimal("3600")),),
        total_quantity=3,
        total_amount=Decimal("3600"),
    )


def test_render_csv_report_contains_all_sections() -> None:
    content = render_csv_report(_sample_result())
    assert "店舗" in content
    assert "渋谷店" in content
    assert "商品" in content
    assert "商品A" in content
    assert "日付" in content
    assert "2026-07-01" in content
    assert "合計" in content
    assert "3600" in content
    # 改行はOS依存にせず\nに固定する(決定性の担保)。
    assert "\r\n" not in content


def test_render_csv_report_sanitizes_dangerous_store_name() -> None:
    result = AggregationResult(
        by_store=(StoreSummary(store="=cmd", quantity=1, amount=Decimal("100")),),
        by_product=(),
        by_date=(),
        total_quantity=1,
        total_amount=Decimal("100"),
    )
    content = render_csv_report(result)
    assert "'=cmd" in content


def test_render_markdown_report_contains_all_sections() -> None:
    content = render_markdown_report(_sample_result())
    assert "# 売上サマリレポート" in content
    assert "## 店舗別" in content
    assert "渋谷店" in content
    assert "## 商品別" in content
    assert "## 日別" in content
    assert "## 合計" in content
    assert "総数量: 3" in content
    assert "総金額: 3600" in content


# --- render_errors_csv -------------------------------------------------------


def test_render_errors_csv_includes_row_and_file_errors() -> None:
    row_errors = [
        LoadedRowError(
            file=Path("sales.csv"),
            row_error=RowError(row_number=3, raw={}, reasons=("dateが空です",)),
        )
    ]
    file_errors = [FileError(path=Path("broken.csv"), reason="文字コードを判定できません")]

    content = render_errors_csv(row_errors, file_errors)
    assert "行エラー" in content
    assert "sales.csv" in content
    assert "3" in content
    assert "dateが空です" in content
    assert "ファイルエラー" in content
    assert "broken.csv" in content


def test_render_errors_csv_sanitizes_file_path_column() -> None:
    """FIX-07/DEF-007: ファイル名列も含め、理由列と同様にCSVインジェクション
    対策(サニタイズ)が適用されていること。攻撃者が制御し得るファイル名
    (`=`始まり等)がpath列に素通しになっていないかを検証する。
    """
    file_errors = [FileError(path=Path("=cmd|calc.csv"), reason="文字コード不明")]
    row_errors = [
        LoadedRowError(
            file=Path("+1+1|evil.csv"),
            row_error=RowError(row_number=2, raw={}, reasons=("storeが空です",)),
        )
    ]

    content = render_errors_csv(row_errors, file_errors)

    assert "'=cmd|calc.csv" in content
    assert "'+1+1|evil.csv" in content


def test_has_errors_to_report() -> None:
    assert has_errors_to_report([], []) is False
    row_errors = [
        LoadedRowError(file=Path("x.csv"), row_error=RowError(row_number=1, raw={}, reasons=("x",)))
    ]
    assert has_errors_to_report(row_errors, []) is True
    assert has_errors_to_report([], [FileError(path=Path("y.csv"), reason="z")]) is True


# --- write_atomic -------------------------------------------------------------


def test_write_atomic_creates_file_with_content(tmp_path: Path) -> None:
    target = tmp_path / "out" / "report.csv"
    write_atomic(target, "hello\n")
    assert target.read_text(encoding="utf-8") == "hello\n"


def test_write_atomic_no_leftover_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "report.csv"
    write_atomic(target, "content\n")
    remaining = list(tmp_path.iterdir())
    assert remaining == [target]


def test_write_atomic_overwrites_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "report.csv"
    write_atomic(target, "old\n")
    write_atomic(target, "new\n")
    assert target.read_text(encoding="utf-8") == "new\n"
