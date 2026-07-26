"""共通フィクスチャ。決定性の担保(乱数シード・時刻固定)もここで一括管理する。"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def make_csv(tmp_path: Path):
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
