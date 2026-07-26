"""売上明細の集計ロジック。

金額計算はDecimal同士の演算のみで行い、float変換を一切行わない
(丸め誤差を出さないための設計上の制約。docs/test-design.md §1.1参照)。
店舗別・商品別・日別に集計し、いずれも合計金額(total_amount)と一致する
という性質は tests/test_properties.py でHypothesisにより検証する。
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext

from sales_report.models import SaleRow


@dataclass(frozen=True, slots=True)
class StoreSummary:
    store: str
    quantity: int
    amount: Decimal


@dataclass(frozen=True, slots=True)
class ProductSummary:
    product: str
    quantity: int
    amount: Decimal


@dataclass(frozen=True, slots=True)
class DateSummary:
    date: dt.date
    quantity: int
    amount: Decimal


@dataclass(frozen=True, slots=True)
class AggregationResult:
    """集計結果。店舗別・商品別・日別のいずれのグルーピングも合計は一致する。"""

    by_store: tuple[StoreSummary, ...]
    by_product: tuple[ProductSummary, ...]
    by_date: tuple[DateSummary, ...]
    total_quantity: int
    total_amount: Decimal


def aggregate(rows: Sequence[SaleRow]) -> AggregationResult:
    """BV-DUP-01: 同一store/product/dateの複数行はエラーにせず自然に合算される
    (グルーピングキーが同じ行の値を加算するため)。

    出力順は店舗名・商品名・日付でソートして固定する(実行順序に依存しない冪等な出力)。
    """
    store_qty: dict[str, int] = defaultdict(int)
    store_amt: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    product_qty: dict[str, int] = defaultdict(int)
    product_amt: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    date_qty: dict[dt.date, int] = defaultdict(int)
    date_amt: dict[dt.date, Decimal] = defaultdict(lambda: Decimal("0"))

    total_quantity = 0
    total_amount = Decimal("0")

    # FIX-04/DEF-010: 既定のDecimalコンテキストは精度28桁しかなく、大桁の値や
    # 大量行の合算で例外なく丸め誤差が生じ得る(Codexレビューが9桁の単価×9で
    # 実測)。集計処理全体を高精度コンテキスト(50桁)で実行し、入力段階の
    # 桁数上限(models.py参照)を全件合算しても丸めが起きない余裕を持たせる。
    # localcontext()はwithブロック内でのみ有効で、グローバルなDecimalコンテキストは
    # 変更しない(他コードへの副作用が無い)。
    with localcontext() as ctx:
        ctx.prec = 50
        for row in rows:
            amount = row.amount
            store_qty[row.store] += row.quantity
            store_amt[row.store] += amount
            product_qty[row.product] += row.quantity
            product_amt[row.product] += amount
            date_qty[row.date] += row.quantity
            date_amt[row.date] += amount
            total_quantity += row.quantity
            total_amount += amount

    by_store = tuple(
        StoreSummary(store=key, quantity=store_qty[key], amount=store_amt[key])
        for key in sorted(store_qty)
    )
    by_product = tuple(
        ProductSummary(product=key, quantity=product_qty[key], amount=product_amt[key])
        for key in sorted(product_qty)
    )
    by_date = tuple(
        DateSummary(date=key, quantity=date_qty[key], amount=date_amt[key])
        for key in sorted(date_qty)
    )

    return AggregationResult(
        by_store=by_store,
        by_product=by_product,
        by_date=by_date,
        total_quantity=total_quantity,
        total_amount=total_amount,
    )
