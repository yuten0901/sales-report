"""Hypothesisによるプロパティベーステスト。

手で書いた具体例だけでなく、「性質」を大量のランダム入力で検証する。
docs/test-design.md §4.2「高度な検証手段」の一環。
"""

from __future__ import annotations

import random
from decimal import Decimal

from hypothesis import given, settings

from sales_report.aggregate import aggregate

from .strategies import sale_rows


@given(rows=sale_rows())
@settings(max_examples=100)
def test_property_total_amount_equals_sum_of_store_amounts(rows: list) -> None:
    """性質1: 総売上金額は、店舗別集計の合計と必ず一致する。"""
    result = aggregate(rows)
    assert result.total_amount == sum((s.amount for s in result.by_store), Decimal("0"))


@given(rows=sale_rows())
@settings(max_examples=100)
def test_property_total_amount_equals_sum_of_product_amounts(rows: list) -> None:
    """性質2: 総売上金額は、商品別集計の合計とも必ず一致する。"""
    result = aggregate(rows)
    assert result.total_amount == sum((p.amount for p in result.by_product), Decimal("0"))


@given(rows=sale_rows())
@settings(max_examples=100)
def test_property_total_amount_equals_sum_of_date_amounts(rows: list) -> None:
    """性質3: 総売上金額は、日別集計の合計とも必ず一致する。"""
    result = aggregate(rows)
    assert result.total_amount == sum((d.amount for d in result.by_date), Decimal("0"))


@given(rows=sale_rows())
@settings(max_examples=100)
def test_property_total_quantity_equals_sum_of_store_quantities(rows: list) -> None:
    """性質4: 総数量も、店舗別集計の合計と一致する(金額だけでなく数量も検証)。"""
    result = aggregate(rows)
    assert result.total_quantity == sum(s.quantity for s in result.by_store)


@given(rows=sale_rows(min_size=1, max_size=30))
@settings(max_examples=50)
def test_property_aggregate_is_order_independent(rows: list) -> None:
    """性質5: 行の入力順序を入れ替えても集計結果(合計)は不変。"""
    shuffled = rows[:]
    random.Random(42).shuffle(shuffled)

    result_original = aggregate(rows)
    result_shuffled = aggregate(shuffled)

    assert result_original.total_amount == result_shuffled.total_amount
    assert result_original.total_quantity == result_shuffled.total_quantity
    assert result_original.by_store == result_shuffled.by_store
    assert result_original.by_product == result_shuffled.by_product
    assert result_original.by_date == result_shuffled.by_date


@given(rows=sale_rows())
@settings(max_examples=100)
def test_property_no_negative_amounts_when_inputs_nonnegative(rows: list) -> None:
    """性質6: 入力(quantity, unit_price)が常に0以上なら、集計結果に負の金額は現れない。"""
    result = aggregate(rows)
    assert result.total_amount >= Decimal("0")
    assert all(s.amount >= Decimal("0") for s in result.by_store)
    assert all(p.amount >= Decimal("0") for p in result.by_product)
    assert all(d.amount >= Decimal("0") for d in result.by_date)
