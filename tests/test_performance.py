"""大容量データでの性能・メモリの下限保証テスト(BV-FILE-04)。

通常のテスト実行から分離する(pyproject.tomlのaddoptsで既定除外)。
明示的に実行するには: pytest -m slow tests/test_performance.py
"""

from __future__ import annotations

import time
import tracemalloc
from pathlib import Path

import pytest

from sales_report.aggregate import aggregate
from sales_report.loader import discover_csv_files, load_files

pytestmark = pytest.mark.slow


def _generate_large_csv(path: Path, n_rows: int) -> None:
    stores = ["渋谷店", "新宿店", "池袋店", "横浜店", "千葉店"]
    products = [f"商品{i}" for i in range(20)]
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write("date,store,product,quantity,unit_price\n")
        for i in range(n_rows):
            date = f"2026-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}"
            store = stores[i % len(stores)]
            product = products[i % len(products)]
            quantity = (i % 10) + 1
            price = f"{100 + (i % 500)}.50"
            f.write(f"{date},{store},{product},{quantity},{price}\n")


def test_large_input_performance_completes_within_time_budget(tmp_path: Path) -> None:
    """BV-FILE-04: 10万行を処理しても妥当な時間で完了すること(下限保証)。"""
    path = tmp_path / "large.csv"
    n_rows = 100_000
    _generate_large_csv(path, n_rows)

    started = time.monotonic()
    files = discover_csv_files(path)
    result = load_files(files)
    aggregation = aggregate(result.rows)
    duration = time.monotonic() - started

    assert len(result.rows) == n_rows
    assert result.row_errors == ()
    assert aggregation.total_quantity > 0
    # FIX-10/Codex#指摘: 当初は30秒(実測~1秒の30倍)という緩すぎる閾値で、
    # 回帰が起きても検知できない「通ることが保証された儀式」になっていた。
    # 実測(このマシンで約0.9秒)に約3倍の余裕を持たせた3秒に厳格化する。
    assert duration < 3.0, f"10万行の処理に{duration:.1f}秒かかった(想定を超過)"


def test_large_input_memory_stays_bounded(tmp_path: Path) -> None:
    """BV-FILE-04: 10万行処理時のピークメモリが暴走しないこと(明確な閾値で検知する)。

    注記: 現実装はファイル全体をメモリに読み込む非ストリーミング設計であるため、
    数百万行規模ではメモリ使用量が線形に増加する(docs/test-report.md 残存リスク参照)。
    """
    path = tmp_path / "large_mem.csv"
    n_rows = 100_000
    _generate_large_csv(path, n_rows)

    tracemalloc.start()
    files = discover_csv_files(path)
    result = load_files(files)
    aggregate(result.rows)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak / (1024 * 1024)
    # FIX-10: 実測(このマシンで約52MB)に約3倍の余裕を持たせ500MBから150MBに厳格化。
    assert peak_mb < 150, f"ピークメモリが{peak_mb:.1f}MBに達した(想定を超過)"
