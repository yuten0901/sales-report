"""Hypothesis用のカスタム戦略。test_properties.py から共有利用する。"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from hypothesis import strategies as st

from sales_report.models import SaleRow

# 店舗名・商品名はあえて少数の候補に絞り、重複明細(BV-DUP-01)が
# プロパティテストの中でも自然に発生する確率を上げる。
_STORES = ["渋谷店", "新宿店", "池袋店"]
_PRODUCTS = ["商品A", "商品B", "商品C"]


@st.composite
def sale_rows(draw: st.DrawFn, min_size: int = 0, max_size: int = 50) -> list[SaleRow]:
    """有効な SaleRow のリストを生成する戦略。"""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    rows: list[SaleRow] = []
    for _ in range(n):
        date = draw(st.dates(min_value=dt.date(2020, 1, 1), max_value=dt.date(2030, 12, 31)))
        store = draw(st.sampled_from(_STORES))
        product = draw(st.sampled_from(_PRODUCTS))
        quantity = draw(st.integers(min_value=0, max_value=10_000))
        unit_price = draw(
            st.decimals(
                min_value=Decimal("0"),
                max_value=Decimal("100000"),
                places=2,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        rows.append(
            SaleRow(
                date=date,
                store=store,
                product=product,
                quantity=quantity,
                unit_price=unit_price,
            )
        )
    return rows


@st.composite
def sale_rows_high_value(draw: st.DrawFn, min_size: int = 0, max_size: int = 20) -> list[SaleRow]:
    """FIX2-11(Codex#8): 既定のsale_rows()はquantity上限10,000・unit_price上限
    100,000と生成範囲が小さく、入力バリデーションの桁数上限(quantity 9桁・
    unit_price整数部12桁)付近や大量行の合算境界を独立オラクル性質テストで
    探索できていなかった。桁数上限ぎりぎりまで生成する高負荷版。

    実行時間に配慮し既定のmax_sizeは小さめ(20)に抑える(通常版のmax_size=50
    より小さいが、1行あたりの値の桁数が最大のため合算境界の探索には十分)。
    """
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    rows: list[SaleRow] = []
    for _ in range(n):
        date = draw(st.dates(min_value=dt.date(2020, 1, 1), max_value=dt.date(2030, 12, 31)))
        store = draw(st.sampled_from(_STORES))
        product = draw(st.sampled_from(_PRODUCTS))
        quantity = draw(st.integers(min_value=0, max_value=999_999_999))  # 9桁上限
        unit_price = draw(
            st.decimals(
                min_value=Decimal("0"),
                max_value=Decimal("999999999999.99"),  # 整数部12桁上限
                places=2,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        rows.append(
            SaleRow(
                date=date,
                store=store,
                product=product,
                quantity=quantity,
                unit_price=unit_price,
            )
        )
    return rows
