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
