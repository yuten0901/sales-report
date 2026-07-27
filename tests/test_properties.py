"""Hypothesisによるプロパティベーステスト。

手で書いた具体例だけでなく、「性質」を大量のランダム入力で検証する。
docs/test-design.md §8「高度な検証手段の全体像」の一環。

FIX-09/別コンテキスト+Codex#14の指摘: 性質1〜3(total_amountと各グループ合計の
一致)は、どちらも同じ`row.amount`の積み上げから計算されるため**自己参照的**
であり、両者が同じように間違えば性質は成立してしまう(FIX-04のDecimal 28桁
バグを実際に素通りさせた実績あり)。これを補うため、末尾に`aggregate()`の
ロジックを一切通らない独立オラクル(最小通貨単位の整数演算)による検証を追加した。
"""

from __future__ import annotations

import random
from decimal import Decimal

from hypothesis import given, settings

from sales_report.aggregate import aggregate
from sales_report.models import SaleRow

from .strategies import sale_rows, sale_rows_high_value


@given(rows=sale_rows())
@settings(max_examples=100)
def test_property_total_amount_equals_sum_of_store_amounts(rows: list[SaleRow]) -> None:
    """性質1: 総売上金額は、店舗別集計の合計と必ず一致する。"""
    result = aggregate(rows)
    assert result.total_amount == sum((s.amount for s in result.by_store), Decimal("0"))


@given(rows=sale_rows())
@settings(max_examples=100)
def test_property_total_amount_equals_sum_of_product_amounts(rows: list[SaleRow]) -> None:
    """性質2: 総売上金額は、商品別集計の合計とも必ず一致する。"""
    result = aggregate(rows)
    assert result.total_amount == sum((p.amount for p in result.by_product), Decimal("0"))


@given(rows=sale_rows())
@settings(max_examples=100)
def test_property_total_amount_equals_sum_of_date_amounts(rows: list[SaleRow]) -> None:
    """性質3: 総売上金額は、日別集計の合計とも必ず一致する。"""
    result = aggregate(rows)
    assert result.total_amount == sum((d.amount for d in result.by_date), Decimal("0"))


@given(rows=sale_rows())
@settings(max_examples=100)
def test_property_total_quantity_equals_sum_of_store_quantities(rows: list[SaleRow]) -> None:
    """性質4: 総数量も、店舗別集計の合計と一致する(金額だけでなく数量も検証)。"""
    result = aggregate(rows)
    assert result.total_quantity == sum(s.quantity for s in result.by_store)


@given(rows=sale_rows(min_size=1, max_size=30))
@settings(max_examples=50)
def test_property_aggregate_is_order_independent(rows: list[SaleRow]) -> None:
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
def test_property_no_negative_amounts_when_inputs_nonnegative(rows: list[SaleRow]) -> None:
    """性質6: 入力(quantity, unit_price)が常に0以上なら、集計結果に負の金額は現れない。

    注記(FIX-09で再検討): この性質は、生成戦略(strategies.sale_rows)が既に
    非負のquantity/unit_priceしか生成しないため、検知力としては強くない
    (ほぼ恒真に近い)。ただし将来aggregate()に符号反転等のバグが混入した場合の
    安価な回帰ネットとして維持する価値はあるため、削除せず残す。
    """
    result = aggregate(rows)
    assert result.total_amount >= Decimal("0")
    assert all(s.amount >= Decimal("0") for s in result.by_store)
    assert all(p.amount >= Decimal("0") for p in result.by_product)
    assert all(d.amount >= Decimal("0") for d in result.by_date)


def _oracle_total_cents(rows: list[SaleRow]) -> int:
    """aggregate()のロジックを一切経由しない、独立した真のオラクル。

    strategies.sale_rows()が生成するunit_priceは常に小数2桁以内(Hypothesis
    戦略でplaces=2固定)であるため、100倍すれば必ず整数(セント/銭単位)になる。
    最小通貨単位の整数演算のみで計算することで、Decimalの丸め・自己参照から
    完全に独立した比較対象を得る。
    """
    total_cents = 0
    for row in rows:
        price_cents = int(row.unit_price * 100)
        total_cents += row.quantity * price_cents
    return total_cents


@given(rows=sale_rows())
@settings(max_examples=100)
def test_property_total_amount_matches_independent_oracle(rows: list[SaleRow]) -> None:
    """性質7(独立オラクル・FIX-09/DEF-013): aggregate()を一切経由しない、
    最小通貨単位の整数演算による独立した計算結果と一致すること。

    性質1〜3は total_amount と各グループ合計のどちらも同じ`row.amount`から
    導出されるため自己参照的で、両方が同時に間違えれば検知できない
    (FIX-04のDecimal 28桁バグが実際にこの弱点を素通りした)。このテストは
    aggregate()のロジックを一切通らない別経路の計算と比較することで、
    真に独立した検証になる。
    """
    result = aggregate(rows)
    oracle_cents = _oracle_total_cents(rows)
    # FIX2-05(Codex#9): int(result.total_amount * 100) は小数部分を切り捨てるため、
    # result側に1銭未満の誤差が混入していても同じ整数へ丸め落ちて検知できない
    # 弱点があった。Decimal同士を直接比較することで、その誤差混入も検知できる。
    assert result.total_amount == Decimal(oracle_cents).scaleb(-2)


@given(rows=sale_rows(min_size=1, max_size=30))
@settings(max_examples=50)
def test_property_grouping_key_swap_is_detected_by_oracle(rows: list[SaleRow]) -> None:
    """独立オラクルが「グルーピングキーの取り違え」も検出できることを確認する。

    別コンテキストレビュー指摘: 性質1〜3は「店舗/商品/日付のグルーピングキーを
    取り違えても総額は一致するため落ちない」という弱点がある。この性質は
    店舗別集計の合計が、店舗ごとに独立集計した値と一致することまで確認し、
    グルーピングキーの取り違えを検出できる形にする。
    """
    result = aggregate(rows)

    # 店舗名ごとに、独立オラクルと同じ方式(整数演算)で真の合計を計算する。
    expected_by_store: dict[str, int] = {}
    for row in rows:
        price_cents = int(row.unit_price * 100)
        expected_by_store[row.store] = (
            expected_by_store.get(row.store, 0) + row.quantity * price_cents
        )

    # FIX2-05(Codex#9): int(s.amount * 100)ではなくDecimal同士を直接比較する
    # (理由は上のtest_property_total_amount_matches_independent_oracle参照)。
    actual_by_store = {s.store: s.amount for s in result.by_store}
    expected_by_store_decimal = {
        store: Decimal(cents).scaleb(-2) for store, cents in expected_by_store.items()
    }
    assert actual_by_store == expected_by_store_decimal


@given(rows=sale_rows_high_value())
@settings(max_examples=30)
def test_property_total_amount_matches_independent_oracle_at_input_digit_limits(
    rows: list[SaleRow],
) -> None:
    """FIX2-11(Codex#8): 独立オラクル(性質7)と同じ検証を、入力バリデーションの
    桁数上限(quantity9桁・unit_price整数部12桁)ぎりぎりの値でも行う。

    既定のsale_rows()はquantity上限10,000・unit_price上限100,000という
    小さい範囲しか生成しないため、バリデーション境界付近の値が
    乗算・集計ロジックを正しく通ることをプロパティテストで確認できて
    いなかった(Codexが再レビューで指摘)。

    **重要な限界の記録**: 「28桁精度では丸め誤差が起きる」という実際の
    精度オーバーフロー(DEF-010)は、少数行(本テストの既定max_size=20)では
    再現しない(手動検証済み: aggregate()のcontext精度を一時的に28に
    落としてもこのテストは失敗しなかった)。桁数上限×大量行(約10万件)の
    組み合わせでのみ発生するため、その閾値はプロパティテストでなく
    `tests/test_aggregate.py`の専用回帰テスト(二分探索で閾値を特定した
    決め打ちのn=100,001件)が担う。本テストの役割は精度オーバーフローの
    検知ではなく、**桁数上限付近の値そのもの**(パース・乗算・比較)に
    未知のバグが無いかをランダム化して探索することである。
    """
    result = aggregate(rows)
    oracle_cents = _oracle_total_cents(rows)
    assert result.total_amount == Decimal(oracle_cents).scaleb(-2)
