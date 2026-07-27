"""堅牢性のテスト: 原子的書き込み・冪等性。

docs/test-design.md §1.3(原子的書き込み・冪等性)に対応する。
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, Literal
from unittest import mock

import pytest
from typer.testing import CliRunner

from sales_report.cli import app
from sales_report.report import write_atomic

from .conftest import VALID_CSV_HEADER, MakeCsv

runner = CliRunner()

_posix_only = pytest.mark.skipif(
    os.name != "posix",
    reason="POSIXファイル権限の検証(Windowsではmodeビットの意味が限定的なため対象外)",
)


def test_atomic_write_interruption_leaves_previous_content_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """処理中断時(書き込み中の例外)に、既存の本番ファイルが中途半端な内容で上書きされないこと。"""
    target = tmp_path / "report.csv"
    target.write_text("old-content\n", encoding="utf-8")

    original_fdopen = os.fdopen

    def broken_fdopen(fd: int, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        real_file = original_fdopen(fd, *args, **kwargs)

        class BrokenWriter:
            def __enter__(self) -> BrokenWriter:
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> Literal[False]:
                real_file.close()
                return False

            def write(self, data: str) -> int:
                real_file.write(data[: len(data) // 2])
                msg = "シミュレートされた中断(ディスクフル等を想定)"
                raise OSError(msg)

        return BrokenWriter()

    monkeypatch.setattr(os, "fdopen", broken_fdopen)

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
        os.close(fd)

        class AlwaysFails:
            def __enter__(self) -> AlwaysFails:
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> Literal[False]:
                return False

            def write(self, data: str) -> int:
                msg = "シミュレートされた中断"
                raise OSError(msg)

        return AlwaysFails()

    monkeypatch.setattr(os, "fdopen", broken_fdopen)

    with pytest.raises(OSError, match="シミュレートされた中断"):
        write_atomic(target, "content\n")

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_write_atomic_closes_fd_when_fdopen_itself_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C#12a(設計裁定・Codexレビュー指摘): os.fdopen()自体が失敗した場合、
    まだファイルオブジェクトにラップされていない生のファイルディスクリプタを
    明示的にos.close()しないとリークする(withブロックの__exit__は__enter__
    失敗時に呼ばれないため)。os.close()が実際に呼ばれることを検証する。
    """
    target = tmp_path / "report.csv"
    closed_fds: list[int] = []
    original_close = os.close

    def spy_close(fd: int) -> None:
        closed_fds.append(fd)
        original_close(fd)

    monkeypatch.setattr(
        os, "fdopen", mock.Mock(side_effect=LookupError("unknown encoding"))
    )
    monkeypatch.setattr(os, "close", spy_close)

    with pytest.raises(LookupError):
        write_atomic(target, "content\n")

    assert len(closed_fds) == 1
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


@_posix_only
def test_write_atomic_preserves_existing_file_permissions(tmp_path: Path) -> None:
    """FIX2-02/DEF-020(Codex#4): 既存ファイルへの上書きでは、その既存ファイルの
    パーミッションを保持すること(tempfile.mkstemp()の既定0600に変わらない)。

    Linux CI(ubuntu-latest)レグで実際に検証されて初めて意味を持つ
    (Windows開発機では原理的に検出できない欠陥だったため)。
    """
    target = tmp_path / "report.csv"
    target.write_text("old-content\n", encoding="utf-8")
    os.chmod(target, 0o644)

    write_atomic(target, "new-content\n")

    assert stat.S_IMODE(target.stat().st_mode) == 0o644


@_posix_only
def test_write_atomic_new_file_uses_default_creation_mode(tmp_path: Path) -> None:
    """FIX2-02: 新規作成時は通常のファイル作成と同じ規則(0o666 & ~umask)を適用する。"""
    target = tmp_path / "new_report.csv"
    current_umask = os.umask(0)
    os.umask(current_umask)

    write_atomic(target, "content\n")

    assert stat.S_IMODE(target.stat().st_mode) == (0o666 & ~current_umask)


def test_idempotent_reruns_produce_byte_identical_output(
    tmp_path: Path, make_csv: MakeCsv, valid_csv_content: str
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
    tmp_path: Path,
) -> None:
    """複数ファイル入力(ディレクトリ)でも、ファイル発見順序がソートされ再実行で結果が変わらない。

    FIX-10/Codex指摘の是正: 以前は出力先を入力ディレクトリの直下(tmp_path)に
    置いており、2回目の実行が1回目の出力を入力として拾ってしまう欠陥があった
    (FIX-03のパス衝突検知により、この状態は現在exit 2で明示的に拒否される)。
    入力と出力を兄弟ディレクトリに分離し、意図した検証(冪等性)のみを行う。
    """
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "b_store.csv").write_text(
        f"{VALID_CSV_HEADER}\n2026-07-01,新宿店,商品B,2,200\n", encoding="utf-8"
    )
    (input_dir / "a_store.csv").write_text(
        f"{VALID_CSV_HEADER}\n2026-07-01,渋谷店,商品A,1,100\n", encoding="utf-8"
    )

    output_dir = tmp_path / "output"
    output1 = output_dir / "out1.csv"
    output2 = output_dir / "out2.csv"

    result1 = runner.invoke(
        app, ["--input", str(input_dir), "--format", "csv", "--output", str(output1)]
    )
    result2 = runner.invoke(
        app, ["--input", str(input_dir), "--format", "csv", "--output", str(output2)]
    )

    assert result1.exit_code == 0
    assert result2.exit_code == 0
    assert output1.read_bytes() == output2.read_bytes()
    # 入力ディレクトリには最初の2ファイルしか無いこと(出力が紛れ込んでいないことの確認)。
    assert sorted(p.name for p in input_dir.iterdir()) == ["a_store.csv", "b_store.csv"]
