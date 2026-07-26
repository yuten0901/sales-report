"""売上データのモデルとフィールド単位のバリデーションロジック。

テスト設計書(docs/test-design.md)の §1.1(入力仕様) / §2(同値分割 EQ-*) /
§3(境界値分析 BV-*) に対応する。各バリデーション関数は「値または理由」を返し、
複数フィールドが同時に不正な場合でも呼び出し側(loader.parse_row)で
理由を集約できるようにしている。
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

REQUIRED_COLUMNS: tuple[str, ...] = ("date", "store", "product", "quantity", "unit_price")

# ASCII半角の整数のみを許可する(全角数字を暗黙に受理するPython標準動作を弾くため)。
# 注意: `\d` はre.ASCII指定が無いとUnicodeの数字(全角含む)にもマッチしてしまうため、
# 明示的に[0-9]を使う(このtypoでunit_price側は一度実装バグを埋め込んだ→docs/defects.md参照)。
_ASCII_INT_PATTERN = re.compile(r"^[+-]?[0-9]+$")
# ASCII半角の10進数のみを許可する(全角・指数表記なども弾く単純な形式)。
_ASCII_DECIMAL_PATTERN = re.compile(r"^[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)$")

# FIX-04/DEF-010: 桁数の上限。既定のDecimalコンテキストは精度28桁しかなく、
# 上限を設けないと大桁の値で例外なく丸め誤差が発生する(9桁の単価×9で
# 実際に9円ずれることをCodexレビューが実測で指摘した)。入力段階で現実的な
# 業務データの範囲に制限することで、この問題を未然に防ぐ。
_MAX_QUANTITY_DIGITS = 9  # 10億未満(最大999,999,999)
_MAX_PRICE_INTEGER_DIGITS = 12  # 最大999,999,999,999円
_MAX_PRICE_DECIMAL_DIGITS = 2  # 円未満は銭単位(2桁)まで


@dataclass(frozen=True, slots=True)
class SaleRow:
    """検証済みの売上明細1行。"""

    date: dt.date
    store: str
    product: str
    quantity: int
    unit_price: Decimal

    @property
    def amount(self) -> Decimal:
        """この明細の金額(数量 × 単価)。丸め誤差を出さないためDecimal同士で計算する。"""
        return Decimal(self.quantity) * self.unit_price


@dataclass(frozen=True, slots=True)
class RowError:
    """検証に失敗した行の情報。理由は複数フィールド分をまとめて保持する。"""

    row_number: int
    raw: dict[str, str | None]
    reasons: tuple[str, ...]

    @property
    def reason_summary(self) -> str:
        return "; ".join(self.reasons)


def validate_date(value: str) -> tuple[dt.date | None, str | None]:
    """EQ-DATE-01〜04: ISO8601(YYYY-MM-DD)形式のみ有効とする。"""
    stripped = value.strip()
    if not stripped:
        return None, "dateが空です"
    try:
        return dt.date.fromisoformat(stripped), None
    except ValueError:
        return None, f"dateの形式が不正です(YYYY-MM-DD形式で指定してください): '{stripped}'"


def validate_text_field(value: str, field_name: str) -> tuple[str | None, str | None]:
    """EQ-STORE-*, EQ-PRODUCT-*: 前後空白を除去して非空であることを要求する。"""
    stripped = value.strip()
    if not stripped:
        return None, f"{field_name}が空です"
    return stripped, None


def validate_quantity(value: str) -> tuple[int | None, str | None]:
    """EQ-QTY-*, BV-QTY-*: ASCII半角の整数(0以上・桁数上限内)のみ有効とする。"""
    stripped = value.strip()
    if not stripped:
        return None, "quantityが空です"
    if not _ASCII_INT_PATTERN.match(stripped):
        return None, f"quantityは整数で指定してください: '{stripped}'"
    parsed = int(stripped)
    if parsed < 0:
        return None, f"quantityは0以上で指定してください: '{stripped}'"
    if len(str(parsed)) > _MAX_QUANTITY_DIGITS:
        # FIX-04/DEF-010: 既定Decimalコンテキスト(精度28桁)での丸め誤差を防ぐため、
        # 業務データとして現実的な範囲に制限する(桁数上限は上のモジュール定数参照)。
        return None, (
            f"quantityの桁数が上限({_MAX_QUANTITY_DIGITS}桁)を超えています: '{stripped}'"
        )
    return parsed, None


def validate_unit_price(value: str) -> tuple[Decimal | None, str | None]:
    """EQ-PRICE-*, BV-PRICE-*: ASCII半角の10進数(0以上・桁数上限内)のみ有効とする。"""
    stripped = value.strip()
    if not stripped:
        return None, "unit_priceが空です"
    if not _ASCII_DECIMAL_PATTERN.match(stripped):
        return None, f"unit_priceが数値として解釈できません: '{stripped}'"
    try:
        parsed = Decimal(stripped)
    except InvalidOperation:  # pragma: no cover
        # _ASCII_DECIMAL_PATTERNが事前に形式を保証するため通常到達しない防御的分岐。
        return None, f"unit_priceが数値として解釈できません: '{stripped}'"
    if parsed < 0:
        return None, f"unit_priceは0以上で指定してください: '{stripped}'"

    # FIX-04/DEF-010: 整数部・小数部それぞれの桁数上限を検査する。
    # 検証済みの文字列(_ASCII_DECIMAL_PATTERNでASCII数字のみと保証済み)から直接
    # 桁数を数える(Decimal.as_tuple()は正規化により末尾ゼロの扱いが変わるため使わない)。
    unsigned = stripped.lstrip("+-")
    integer_part, _, decimal_part = unsigned.partition(".")
    integer_part = integer_part or "0"
    if len(integer_part) > _MAX_PRICE_INTEGER_DIGITS:
        return None, (
            f"unit_priceの整数部の桁数が上限({_MAX_PRICE_INTEGER_DIGITS}桁)"
            f"を超えています: '{stripped}'"
        )
    if len(decimal_part) > _MAX_PRICE_DECIMAL_DIGITS:
        return None, (
            f"unit_priceの小数部の桁数が上限({_MAX_PRICE_DECIMAL_DIGITS}桁)"
            f"を超えています: '{stripped}'"
        )
    return parsed, None


def _get_str(raw: Mapping[str, str | None], key: str) -> str:
    """rawからkeyを文字列として取得する。キー不在/値Noneのいずれも""として扱う。

    列数不足のCSV行はcsv.DictReaderのrestval設定次第でNoneが入り得るため、
    parse_row側でも防御的にNoneを吸収する(FIX-01/DEF-006。restvalの設定だけに
    依存しない二重の安全策)。"0"等の偽値文字列は保持するためor演算子は使わない。
    """
    value = raw.get(key)
    return "" if value is None else value


def parse_row(
    raw: Mapping[str, str | None], row_number: int
) -> tuple[SaleRow | None, RowError | None]:
    """DT-1: CSVの1行(dict)を検証し、SaleRowまたはRowErrorのどちらかを返す。

    いずれか1フィールドでも無効なら行全体を無効とし、検出した全ての理由を
    RowError.reasonsにまとめる(複数フィールドが同時に不正な場合も一括で伝える)。
    """
    reasons: list[str] = []

    date_value, date_err = validate_date(_get_str(raw, "date"))
    if date_err:
        reasons.append(date_err)

    store_value, store_err = validate_text_field(_get_str(raw, "store"), "store")
    if store_err:
        reasons.append(store_err)

    product_value, product_err = validate_text_field(_get_str(raw, "product"), "product")
    if product_err:
        reasons.append(product_err)

    quantity_value, quantity_err = validate_quantity(_get_str(raw, "quantity"))
    if quantity_err:
        reasons.append(quantity_err)

    price_value, price_err = validate_unit_price(_get_str(raw, "unit_price"))
    if price_err:
        reasons.append(price_err)

    if reasons:
        return None, RowError(row_number=row_number, raw=dict(raw), reasons=tuple(reasons))

    # mypy向けの型絞り込み(ここに到達した時点で全フィールドが検証済み=Noneではない)。
    # セキュリティ上の検証ではなく、数行上のif reasons:分岐で既に保証済みの内部不変条件を
    # 型チェッカーに伝えるためだけの用途 -> bandit B101(assert_used)は妥当な指摘だが実害なし。
    assert date_value is not None  # nosec B101
    assert store_value is not None  # nosec B101
    assert product_value is not None  # nosec B101
    assert quantity_value is not None  # nosec B101
    assert price_value is not None  # nosec B101

    return (
        SaleRow(
            date=date_value,
            store=store_value,
            product=product_value,
            quantity=quantity_value,
            unit_price=price_value,
        ),
        None,
    )
