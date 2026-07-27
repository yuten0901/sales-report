"""aggregate.py の例ベーステスト。プロパティベースの性質検証は test_properties.py 参照。"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from sales_report.aggregate import StoreSummary, aggregate
from sales_report.models import SaleRow


def _row(
    date: str = "2026-07-01",
    store: str = "渋谷店",
    product: str = "商品A",
    quantity: int = 1,
    unit_price: str = "100",
) -> SaleRow:
    return SaleRow(
        date=dt.date.fromisoformat(date),
        store=store,
        product=product,
        quantity=quantity,
        unit_price=Decimal(unit_price),
    )


def test_aggregate_empty_rows_returns_zero_totals() -> None:
    result = aggregate([])
    assert result.by_store == ()
    assert result.by_product == ()
    assert result.by_date == ()
    assert result.total_quantity == 0
    assert result.total_amount == Decimal("0")


def test_aggregate_single_row() -> None:
    result = aggregate([_row(quantity=3, unit_price="1200")])
    assert result.total_quantity == 3
    assert result.total_amount == Decimal("3600")
    assert result.by_store == (
        StoreSummary(store="渋谷店", quantity=3, amount=Decimal("3600")),
    )


def test_aggregate_by_store_by_product_by_date_grouping() -> None:
    rows = [
        _row(date="2026-07-01", store="渋谷店", product="商品A", quantity=2, unit_price="100"),
        _row(date="2026-07-01", store="新宿店", product="商品A", quantity=1, unit_price="100"),
        _row(date="2026-07-02", store="渋谷店", product="商品B", quantity=3, unit_price="200"),
    ]
    result = aggregate(rows)

    stores = {s.store: (s.quantity, s.amount) for s in result.by_store}
    assert stores == {
        "渋谷店": (5, Decimal("800")),
        "新宿店": (1, Decimal("100")),
    }

    products = {p.product: (p.quantity, p.amount) for p in result.by_product}
    assert products == {
        "商品A": (3, Decimal("300")),
        "商品B": (3, Decimal("600")),
    }

    dates = {d.date: (d.quantity, d.amount) for d in result.by_date}
    assert dates == {
        dt.date(2026, 7, 1): (3, Decimal("300")),
        dt.date(2026, 7, 2): (3, Decimal("600")),
    }

    assert result.total_quantity == 6
    assert result.total_amount == Decimal("900")


def test_aggregate_duplicate_lines_are_summed() -> None:
    """BV-DUP-01: 同一date/store/productの複数行はエラーにせず合算する。"""
    rows = [
        _row(date="2026-07-01", store="渋谷店", product="商品A", quantity=1, unit_price="100"),
        _row(date="2026-07-01", store="渋谷店", product="商品A", quantity=2, unit_price="100"),
    ]
    result = aggregate(rows)
    assert result.total_quantity == 3
    assert result.total_amount == Decimal("300")
    assert len(result.by_store) == 1
    assert result.by_store[0].quantity == 3


def test_aggregate_boundary_zero_quantity_and_zero_price() -> None:
    """BV-QTY-01, BV-PRICE-01: 数量0・単価0の行も正しく(0円として)集計される。"""
    rows = [
        _row(quantity=0, unit_price="1200"),
        _row(quantity=5, unit_price="0"),
    ]
    result = aggregate(rows)
    assert result.total_quantity == 5
    assert result.total_amount == Decimal("0")


def test_aggregate_result_sorted_by_key_for_determinism() -> None:
    """出力順がソートされ、入力順に依存しないことを確認する(冪等性の一部)。"""
    rows = [
        _row(store="新宿店", product="商品B"),
        _row(store="渋谷店", product="商品A"),
        _row(store="池袋店", product="商品C"),
    ]
    result = aggregate(rows)
    store_names = [s.store for s in result.by_store]
    assert store_names == sorted(store_names)
    product_names = [p.product for p in result.by_product]
    assert product_names == sorted(product_names)


def test_aggregate_precise_decimal_no_rounding_error() -> None:
    """BV-PRICE-03: 小数点以下が長い値でもDecimalで正確に計算される。"""
    rows = [_row(quantity=3, unit_price="100.999")]
    result = aggregate(rows)
    assert result.total_amount == Decimal("302.997")


@pytest.mark.slow
def test_aggregate_no_rounding_at_large_scale_with_default_28_digit_precision_would_fail() -> None:
    """FIX-04/DEF-010: 既定のDecimalコンテキスト(精度28桁)では、大量の高額行を
    合算すると例外なく丸め誤差が発生する(Codexレビューが実測で指摘)。

    入力バリデーションの桁数上限(models.py: unit_price整数部12桁・quantity9桁)
    ぎりぎりの値を100,001件合算する。この件数は「デフォルト精度28桁では
    ちょうど丸め誤差が発生し、高精度(50桁)コンテキストでは発生しない」という
    閾値を二分探索で特定したもの(n=100,000は一致・n=100,001から不一致になる)。
    aggregate()が内部でlocalcontext(prec=50)を使っていることの直接的な証明。

    FIX2-15(Codex#7): 100,001個のオブジェクトを毎回生成するため通常の
    テスト実行を不必要に重くしていた。境界値の証明という性質上、この
    構成自体(prec=50への依存)を縮小すると意味が変わってしまうため、
    性能テストと同様にslowマーカーで通常実行から分離する。
    """
    max_price = Decimal("999999999999.99")  # 整数部12桁の上限値
    max_quantity = 999999999  # 9桁の上限値
    n = 100_001

    rows = [
        _row(
            date="2026-01-01",
            store="S",
            product="P",
            quantity=max_quantity,
            unit_price=str(max_price),
        )
        for _ in range(n)
    ]

    # 期待値は整数演算(cents単位)で丸め無しに算出する、丸めから独立した真のオラクル。
    # Decimalの除算は既定コンテキストで丸められ得るため、文字列組み立てで
    # Decimal化する(除算を一切使わない)。
    per_row_cents = int(max_price * 100) * max_quantity
    expected_cents = per_row_cents * n
    expected = Decimal(f"{expected_cents // 100}.{expected_cents % 100:02d}")

    result = aggregate(rows)

    assert result.total_amount == expected
