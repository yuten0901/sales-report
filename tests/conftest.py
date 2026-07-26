"""共通フィクスチャ。CSVファイル作成のヘルパーを提供する。

FIX-11: 以前のdocstringは「決定性の担保(乱数シード・時刻固定)もここで
一括管理する」と書いていたが、実体が無かった(虚偽のdocstring)。現状の
テストスイートは日時固定や時刻フリーズを必要としない(コード側が
datetime.now()等を使っておらず、出力にタイムスタンプを埋め込まない
ため)。順序不変性を検証するtest_property_aggregate_is_order_independent
は、ローカルスコープの`random.Random(42)`で既に決定的にシャッフルして
おり、グローバルな乱数シード管理も不要。実態に合わせてdocstringを
訂正し、未使用だった`freezegun`依存もpyproject.tomlから削除した。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pytest


class MakeCsv(Protocol):
    """`make_csv`フィクスチャが返す関数の型(残存リスク#12対応でtests/にも型を導入)。"""

    def __call__(self, name: str, content: str, encoding: str = "utf-8") -> Path: ...


@pytest.fixture
def make_csv(tmp_path: Path) -> MakeCsv:
    """指定した内容・エンコーディングでCSVファイルを作成するヘルパーを返す。"""

    def _make(name: str, content: str, encoding: str = "utf-8") -> Path:
        path = tmp_path / name
        path.write_bytes(content.encode(encoding))
        return path

    return _make


VALID_CSV_HEADER = "date,store,product,quantity,unit_price"


@pytest.fixture
def valid_csv_content() -> str:
    return (
        f"{VALID_CSV_HEADER}\n"
        "2026-07-01,渋谷店,商品A,3,1200\n"
        "2026-07-01,渋谷店,商品B,1,500\n"
        "2026-07-02,新宿店,商品A,2,1200\n"
    )
