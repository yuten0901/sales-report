"""堅牢性のテスト: 原子的書き込み・冪等性。

docs/test-design.md §1.3(原子的書き込み・冪等性)に対応する。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import sales_report.report as report_module
from sales_report.cli import app
from sales_report.report import write_atomic

from .conftest import VALID_CSV_HEADER

runner = CliRunner()


def test_atomic_write_interruption_leaves_previous_content_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """処理中断時(書き込み中の例外)に、既存の本番ファイルが中途半端な内容で上書きされないこと。"""
    target = tmp_path / "report.csv"
    target.write_text("old-content\n", encoding="utf-8")

    original_fdopen = report_module.os.fdopen

    def broken_fdopen(fd: int, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        real_file = original_fdopen(fd, *args, **kwargs)

        class BrokenWriter:
            def __enter__(self) -> BrokenWriter:
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
                real_file.close()
                return False

            def write(self, data: str) -> int:
                real_file.write(data[: len(data) // 2])
                msg = "シミュレートされた中断(ディスクフル等を想定)"
                raise OSError(msg)

        return BrokenWriter()

    monkeypatch.setattr(report_module.os, "fdopen", broken_fdopen)

    with pytest.raises(OSError, match="シミュレートされた中断"):
        write_atomic(target, "new-content-that-is-considerably-longer\n")

    # 本番ファイルは古い内容のまま(中途半端な新しい内容に置き換わっていない)。
    assert target.read_text(encoding="utf-8") == "old-content\n"
    # 一時ファイルも残らない。
    remaining = [p for p in tmp_path.iterdir() if p != target]
    assert remaining == []


def test_atomic_write_interruption_when_no_previous_file_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """既存ファイルが無い状態で中断した場合、中途半端なファイルが新規作成されないこと。"""
    target = tmp_path / "report.csv"

    def broken_fdopen(fd: int, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        import os as os_module

        os_module.close(fd)

        class AlwaysFails:
            def __enter__(self) -> AlwaysFails:
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
                return False

            def write(self, data: str) -> int:
                msg = "シミュレートされた中断"
                raise OSError(msg)

        return AlwaysFails()

    monkeypatch.setattr(report_module.os, "fdopen", broken_fdopen)

    with pytest.raises(OSError, match="シミュレートされた中断"):
        write_atomic(target, "content\n")

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_idempotent_reruns_produce_byte_identical_output(
    tmp_path: Path, make_csv, valid_csv_content: str
) -> None:
    """性質: 同一入力・同一オプションで複数回実行しても出力はバイト同一(冪等性)。"""
    path = make_csv("data.csv", valid_csv_content)
    output1 = tmp_path / "out1.md"
    output2 = tmp_path / "out2.md"

    result1 = runner.invoke(app, ["--input", str(path), "--output", str(output1)])
    result2 = runner.invoke(app, ["--input", str(path), "--output", str(output2)])

    assert result1.exit_code == 0
    assert result2.exit_code == 0
    assert output1.read_bytes() == output2.read_bytes()


def test_idempotent_reruns_with_directory_input_and_multiple_files(
    tmp_path: Path, make_csv
) -> None:
    """複数ファイル入力(ディレクトリ)でも、ファイル発見順序がソートされ再実行で結果が変わらない。"""
    make_csv("b_store.csv", f"{VALID_CSV_HEADER}\n2026-07-01,新宿店,商品B,2,200\n")
    make_csv("a_store.csv", f"{VALID_CSV_HEADER}\n2026-07-01,渋谷店,商品A,1,100\n")

    output1 = tmp_path / "out1.csv"
    output2 = tmp_path / "out2.csv"

    result1 = runner.invoke(
        app, ["--input", str(tmp_path), "--format", "csv", "--output", str(output1)]
    )
    result2 = runner.invoke(
        app, ["--input", str(tmp_path), "--format", "csv", "--output", str(output2)]
    )

    assert result1.exit_code == 0
    assert result2.exit_code == 0
    assert output1.read_bytes() == output2.read_bytes()
