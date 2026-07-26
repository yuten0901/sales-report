"""models.py のフィールド単位バリデーションのテスト。

docs/test-design.md の EQ-*(同値分割) / BV-*(境界値) に対応する。
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from sales_report.models import (
    RowError,
    SaleRow,
    parse_row,
    validate_date,
    validate_quantity,
    validate_text_field,
    validate_unit_price,
)

# --- validate_date -----------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("2026-07-26", dt.date(2026, 7, 26), id="EQ-DATE-01"),
        pytest.param("2000-01-01", dt.date(2000, 1, 1), id="EQ-DATE-01-epoch"),
    ],
)
def test_validate_date_valid(value: str, expected: dt.date) -> None:
    result, err = validate_date(value)
    assert result == expected
    assert err is None


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("2026/07/26", id="EQ-DATE-02-slash"),
        pytest.param("26-07-2026", id="EQ-DATE-02-order"),
        pytest.param("not-a-date", id="EQ-DATE-02-text"),
        pytest.param("", id="EQ-DATE-03-empty"),
        pytest.param("   ", id="EQ-DATE-03-whitespace"),
        pytest.param("2026-02-30", id="EQ-DATE-04-nonexistent"),
        pytest.param("2026-13-01", id="EQ-DATE-04-invalid-month"),
    ],
)
def test_validate_date_invalid(value: str) -> None:
    result, err = validate_date(value)
    assert result is None
    assert err is not None


# --- validate_text_field (store / product共通) --------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("渋谷店", "渋谷店", id="EQ-STORE-01"),
        pytest.param("  新宿店  ", "新宿店", id="EQ-STORE-01-strip"),
    ],
)
def test_validate_text_field_valid(value: str, expected: str) -> None:
    result, err = validate_text_field(value, "store")
    assert result == expected
    assert err is None


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("", id="EQ-STORE-02-empty"),
        pytest.param("   ", id="EQ-STORE-02-whitespace"),
    ],
)
def test_validate_text_field_invalid(value: str) -> None:
    result, err = validate_text_field(value, "store")
    assert result is None
    assert err is not None
    assert "store" in err


# --- validate_quantity ---------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("5", 5, id="EQ-QTY-01"),
        pytest.param("0", 0, id="BV-QTY-01-zero"),
        pytest.param("1000000", 1000000, id="BV-QTY-03-large"),
        pytest.param("  7  ", 7, id="EQ-QTY-01-strip"),
        pytest.param("+3", 3, id="EQ-QTY-01-explicit-plus"),
    ],
)
def test_validate_quantity_valid(value: str, expected: int) -> None:
    result, err = validate_quantity(value)
    assert result == expected
    assert err is None


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("abc", id="EQ-QTY-02-alpha"),
        pytest.param("５", id="EQ-QTY-02-fullwidth"),
        pytest.param("1.5", id="EQ-QTY-03-decimal"),
        pytest.param("", id="EQ-QTY-04-empty"),
        pytest.param("-1", id="BV-QTY-02-negative"),
        pytest.param("-100", id="BV-QTY-02-negative-large"),
    ],
)
def test_validate_quantity_invalid(value: str) -> None:
    result, err = validate_quantity(value)
    assert result is None
    assert err is not None


def test_validate_quantity_rejects_fullwidth_explicitly() -> None:
    """Python標準int()は全角数字を暗黙に受理するため、明示チェックで弾けているか確認する。

    実装前の仕様確認で発見した非自明な挙動(docs/defects.md参照)。
    """
    # Python標準の挙動そのものを確認(このテストが失敗したらPythonの仕様が変わった)。
    assert int("５") == 5
    # だが本ツールのvalidate_quantityは明示的に拒否しなければならない。
    result, err = validate_quantity("５")
    assert result is None
    assert err is not None


# --- validate_unit_price --------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("1200", Decimal("1200"), id="EQ-PRICE-01-int"),
        pytest.param("1200.50", Decimal("1200.50"), id="EQ-PRICE-01-decimal"),
        pytest.param("0", Decimal("0"), id="BV-PRICE-01-zero"),
        pytest.param("100.999", Decimal("100.999"), id="BV-PRICE-03-precise"),
    ],
)
def test_validate_unit_price_valid(value: str, expected: Decimal) -> None:
    result, err = validate_unit_price(value)
    assert result == expected
    assert err is None


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("abc", id="EQ-PRICE-02-alpha"),
        pytest.param("¥1200", id="EQ-PRICE-02-currency-symbol"),
        pytest.param("１２００", id="EQ-PRICE-02-fullwidth"),
        pytest.param("", id="EQ-PRICE-03-empty"),
        pytest.param("-0.01", id="BV-PRICE-02-negative"),
        pytest.param("-100", id="BV-PRICE-02-negative-large"),
    ],
)
def test_validate_unit_price_invalid(value: str) -> None:
    result, err = validate_unit_price(value)
    assert result is None
    assert err is not None


# --- SaleRow.amount --------------------------------------------------------


def test_sale_row_amount_calculation() -> None:
    row = SaleRow(
        date=dt.date(2026, 7, 26),
        store="渋谷店",
        product="商品A",
        quantity=3,
        unit_price=Decimal("1200.50"),
    )
    assert row.amount == Decimal("3601.50")


def test_sale_row_amount_zero_quantity_is_zero_yen() -> None:
    """BV-QTY-01: 数量0は有効で、金額は0円になる。"""
    row = SaleRow(
        date=dt.date(2026, 7, 26),
        store="渋谷店",
        product="商品A",
        quantity=0,
        unit_price=Decimal("1200"),
    )
    assert row.amount == Decimal("0")


def test_sale_row_amount_zero_price_is_zero_yen() -> None:
    """BV-PRICE-01: 単価0は有効で、金額は0円になる。"""
    row = SaleRow(
        date=dt.date(2026, 7, 26),
        store="渋谷店",
        product="無料サンプル",
        quantity=5,
        unit_price=Decimal("0"),
    )
    assert row.amount == Decimal("0")


def test_sale_row_amount_no_rounding_error_on_repeated_addition() -> None:
    """Decimal選定の根拠: floatなら生じる丸め誤差がDecimalでは発生しないことを確認する。"""
    row = SaleRow(
        date=dt.date(2026, 7, 26),
        store="渋谷店",
        product="商品B",
        quantity=3,
        unit_price=Decimal("0.1"),
    )
    total = sum((row.amount for _ in range(10)), Decimal("0"))
    assert total == Decimal("3.0")


# --- parse_row (DT-1: デシジョンテーブル) ----------------------------------


def _valid_raw() -> dict[str, str]:
    return {
        "date": "2026-07-26",
        "store": "渋谷店",
        "product": "商品A",
        "quantity": "5",
        "unit_price": "1200",
    }


def test_parse_row_dt1_01_all_valid() -> None:
    raw = _valid_raw()
    row, err = parse_row(raw, row_number=1)
    assert err is None
    assert isinstance(row, SaleRow)
    assert row.store == "渋谷店"
    assert row.quantity == 5


def test_parse_row_dt1_02_invalid_date() -> None:
    raw = _valid_raw()
    raw["date"] = "invalid"
    row, err = parse_row(raw, row_number=2)
    assert row is None
    assert isinstance(err, RowError)
    assert len(err.reasons) == 1
    assert "date" in err.reasons[0]


def test_parse_row_dt1_03_invalid_store() -> None:
    raw = _valid_raw()
    raw["store"] = ""
    row, err = parse_row(raw, row_number=3)
    assert row is None
    assert isinstance(err, RowError)
    assert "store" in err.reasons[0]


def test_parse_row_dt1_04_invalid_quantity() -> None:
    raw = _valid_raw()
    raw["quantity"] = "abc"
    row, err = parse_row(raw, row_number=4)
    assert row is None
    assert isinstance(err, RowError)
    assert "quantity" in err.reasons[0]


def test_parse_row_dt1_05_invalid_unit_price() -> None:
    raw = _valid_raw()
    raw["unit_price"] = "abc"
    row, err = parse_row(raw, row_number=5)
    assert row is None
    assert isinstance(err, RowError)
    assert "unit_price" in err.reasons[0]


def test_parse_row_dt1_06_compound_errors_date_and_quantity() -> None:
    """DT-1-06: 複数フィールドが同時に不正な場合、全ての理由が記録される。"""
    raw = _valid_raw()
    raw["date"] = "invalid"
    raw["quantity"] = "abc"
    row, err = parse_row(raw, row_number=6)
    assert row is None
    assert isinstance(err, RowError)
    assert len(err.reasons) == 2
    assert any("date" in r for r in err.reasons)
    assert any("quantity" in r for r in err.reasons)


def test_parse_row_dt1_07_all_fields_invalid() -> None:
    """DT-1-07: 全フィールドが不正な場合、5件全ての理由が記録される。"""
    raw = {
        "date": "",
        "store": "",
        "product": "",
        "quantity": "",
        "unit_price": "",
    }
    row, err = parse_row(raw, row_number=7)
    assert row is None
    assert isinstance(err, RowError)
    assert len(err.reasons) == 5


def test_parse_row_handles_none_values_without_crashing() -> None:
    """FIX-01/DEF-006: rawの値がNone(csv.DictReaderのrestval未設定時の既定動作)でも
    クラッシュせず、空文字として扱われ行エラーになること(loaderのrestval設定への
    依存だけに頼らない、models側の二重の防御策=_get_strを直接検証する)。
    """
    raw = {
        "date": "2026-07-01",
        "store": "渋谷店",
        "product": "商品A",
        "quantity": None,
        "unit_price": None,
    }
    row, err = parse_row(raw, row_number=1)
    assert row is None
    assert isinstance(err, RowError)
    assert len(err.reasons) == 2
    assert any("quantity" in r for r in err.reasons)
    assert any("unit_price" in r for r in err.reasons)


def test_row_error_reason_summary_joins_all_reasons() -> None:
    err = RowError(row_number=1, raw={}, reasons=("理由A", "理由B"))
    assert err.reason_summary == "理由A; 理由B"
