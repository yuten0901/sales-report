"""loader.py のテスト。

docs/test-design.md の BV-FILE-*(ファイル境界) / BV-ENC-*(文字コード境界)に対応する。
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from sales_report.loader import (
    FileError,
    discover_csv_files,
    load_file,
    load_files,
)

from .conftest import VALID_CSV_HEADER

# --- discover_csv_files ----------------------------------------------------


def test_discover_csv_files_single_file(tmp_path: Path, make_csv) -> None:
    path = make_csv("sales.csv", f"{VALID_CSV_HEADER}\n")
    result = discover_csv_files(path)
    assert result == [path]


def test_discover_csv_files_non_csv_file_returns_empty(tmp_path: Path) -> None:
    """A-3(設計裁定): 非CSVファイルを直接指定した場合、「ディレクトリ内に
    CSVが無い」場合と同じ空リストを返す(呼び出し側でexit 2に統一するため)。
    修正前は拡張子を見ずそのまま返しファイルレベルエラー経由でexit 1に
    なっており、同じ「入力の指定ミス」で終了コードが割れていた。
    """
    path = tmp_path / "memo.txt"
    path.write_text("this is not a csv")
    result = discover_csv_files(path)
    assert result == []


def test_discover_csv_files_directory_finds_only_csv_sorted(tmp_path: Path, make_csv) -> None:
    make_csv("b.csv", f"{VALID_CSV_HEADER}\n")
    make_csv("a.csv", f"{VALID_CSV_HEADER}\n")
    make_csv("readme.txt", "not a csv")
    result = discover_csv_files(tmp_path)
    assert [p.name for p in result] == ["a.csv", "b.csv"]


def test_discover_csv_files_nonexistent_path_raises(tmp_path: Path) -> None:
    """DT-2-01: 入力パスが存在しない場合はFileNotFoundError(呼び出し側でexit 2に変換)。"""
    missing = tmp_path / "does-not-exist"
    with pytest.raises(FileNotFoundError):
        discover_csv_files(missing)


def test_discover_csv_files_directory_without_csv_returns_empty(tmp_path: Path, make_csv) -> None:
    """DT-2-02: ディレクトリは存在するがCSVが1つも無い場合は空リスト(呼び出し側でexit 2)。"""
    (tmp_path / "not-a-csv.txt").write_text("hello")
    result = discover_csv_files(tmp_path)
    assert result == []


# --- load_file: エンコーディング(BV-ENC-*) --------------------------------


def test_load_file_utf8_without_bom(make_csv, valid_csv_content: str) -> None:
    """BV-ENC-01"""
    path = make_csv("sales.csv", valid_csv_content, encoding="utf-8")
    rows, errors, file_error = load_file(path)
    assert file_error is None
    assert errors == []
    assert len(rows) == 3
    assert rows[0].store == "渋谷店"


def test_load_file_utf8_with_bom(make_csv, valid_csv_content: str) -> None:
    """BV-ENC-02"""
    path = make_csv("sales.csv", valid_csv_content, encoding="utf-8-sig")
    rows, errors, file_error = load_file(path)
    assert file_error is None
    assert errors == []
    assert len(rows) == 3


def test_load_file_shift_jis(make_csv, valid_csv_content: str) -> None:
    """BV-ENC-03"""
    path = make_csv("sales.csv", valid_csv_content, encoding="cp932")
    rows, errors, file_error = load_file(path)
    assert file_error is None
    assert errors == []
    assert len(rows) == 3
    assert rows[0].store == "渋谷店"


def test_load_file_undecodable_bytes_becomes_file_error(tmp_path: Path) -> None:
    """BV-ENC-04: UTF-8/Shift-JISいずれでもデコードできないバイト列はファイルエラーになる。"""
    path = tmp_path / "broken.csv"
    # 0x81 単独はcp932としても不完全なマルチバイト先頭であり、多くの場合both encodingで失敗する。
    path.write_bytes(b"\xff\xfe\x00\x81\x00\xff")
    rows, errors, file_error = load_file(path)
    assert rows == []
    assert errors == []
    assert isinstance(file_error, FileError)
    assert "文字コード" in file_error.reason


def test_load_file_permission_error_becomes_file_error_not_crash(tmp_path: Path) -> None:
    """FIX-06/DEF-012: 読込時の権限エラー(OSError)もファイルエラーとして扱われ、
    クラッシュせず処理が継続すること。UnicodeDecodeErrorのみを捕捉していた
    従来実装では、OSErrorは未捕捉のまま伝播しCLI全体が停止していた(Codex#11)。
    """
    path = tmp_path / "no_permission.csv"
    path.write_text(f"{VALID_CSV_HEADER}\n2026-07-01,渋谷店,商品A,1,100\n", encoding="utf-8")

    with mock.patch.object(Path, "read_text", side_effect=PermissionError("permission denied")):
        rows, errors, file_error = load_file(path)

    assert rows == []
    assert errors == []
    assert isinstance(file_error, FileError)
    assert "読み込めませんでした" in file_error.reason


def test_load_files_permission_error_on_one_file_does_not_stop_others(
    tmp_path: Path, make_csv
) -> None:
    """1ファイルの権限エラーで全体が止まらず、他のファイルの処理は継続されること。"""
    good = make_csv("good.csv", f"{VALID_CSV_HEADER}\n2026-07-01,渋谷店,商品A,1,100\n")
    bad = tmp_path / "bad.csv"
    bad.write_text(f"{VALID_CSV_HEADER}\n2026-07-01,新宿店,商品B,1,200\n", encoding="utf-8")

    original_read_text = Path.read_text

    def flaky_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == bad:
            raise PermissionError("permission denied")
        return original_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    with mock.patch.object(Path, "read_text", flaky_read_text):
        files = discover_csv_files(tmp_path)
        result = load_files(files)

    assert len(result.rows) == 1
    assert result.rows[0].store == "渋谷店"
    assert len(result.file_errors) == 1
    assert result.file_errors[0].path == bad
    assert good.exists()


# --- load_file: ファイル境界(BV-FILE-*) -----------------------------------


def test_load_file_empty_file_is_file_error(tmp_path: Path) -> None:
    """BV-FILE-01: 0バイトファイルはヘッダが無いためファイルエラーになる。"""
    path = tmp_path / "empty.csv"
    path.write_bytes(b"")
    rows, errors, file_error = load_file(path)
    assert rows == []
    assert errors == []
    assert isinstance(file_error, FileError)
    assert "ヘッダー" in file_error.reason


def test_load_file_header_only_returns_empty_without_file_error(make_csv) -> None:
    """BV-FILE-02: ヘッダのみ(データ0行)はファイルエラーにはせず、単に0行を返す。"""
    path = make_csv("header_only.csv", f"{VALID_CSV_HEADER}\n")
    rows, errors, file_error = load_file(path)
    assert rows == []
    assert errors == []
    assert file_error is None


def test_load_file_single_row(make_csv) -> None:
    """BV-FILE-03: データ1行のみでも正しく読み込める。"""
    content = f"{VALID_CSV_HEADER}\n2026-07-01,渋谷店,商品A,1,100\n"
    path = make_csv("single.csv", content)
    rows, errors, file_error = load_file(path)
    assert file_error is None
    assert errors == []
    assert len(rows) == 1


def test_load_file_missing_required_column(make_csv) -> None:
    """必須列が欠落している場合はファイルエラーになる(unit_price列が無い)。"""
    content = "date,store,product,quantity\n2026-07-01,渋谷店,商品A,1\n"
    path = make_csv("missing_column.csv", content)
    rows, errors, file_error = load_file(path)
    assert rows == []
    assert errors == []
    assert isinstance(file_error, FileError)
    assert "unit_price" in file_error.reason


def test_load_file_header_with_mixed_case_is_accepted(make_csv) -> None:
    """A-1(設計裁定): ヘッダの大文字小文字の揺れを許容する(正規化=casefold)。"""
    content = "Date,Store,Product,Quantity,Unit_Price\n2026-07-01,渋谷店,商品A,3,1200\n"
    path = make_csv("mixed_case_header.csv", content)
    rows, errors, file_error = load_file(path)
    assert file_error is None
    assert errors == []
    assert len(rows) == 1
    assert rows[0].store == "渋谷店"


def test_load_file_header_with_surrounding_whitespace_is_accepted(make_csv) -> None:
    """A-1(設計裁定): ヘッダの前後空白の揺れを許容する(正規化=strip)。"""
    content = " date , store,product , quantity, unit_price \n2026-07-01,渋谷店,商品A,3,1200\n"
    path = make_csv("whitespace_header.csv", content)
    rows, errors, file_error = load_file(path)
    assert file_error is None
    assert errors == []
    assert len(rows) == 1
    assert rows[0].quantity == 3


def test_load_file_semantic_alias_header_is_not_accepted(make_csv) -> None:
    """A-1(設計裁定・非対応の明示): 「売上日」のような意味的なエイリアスは
    正規化(strip+casefold)の対象外であり、必須列不足として扱われる。
    """
    content = "売上日,store,product,quantity,unit_price\n2026-07-01,渋谷店,商品A,3,1200\n"
    path = make_csv("alias_header.csv", content)
    rows, errors, file_error = load_file(path)
    assert rows == []
    assert isinstance(file_error, FileError)
    assert "date" in file_error.reason


def test_load_file_mixed_valid_and_invalid_rows(make_csv) -> None:
    """一部の行が不正でも、有効な行は取り込みつつ理由付きでエラーを記録する。"""
    content = (
        f"{VALID_CSV_HEADER}\n"
        "2026-07-01,渋谷店,商品A,3,1200\n"
        "invalid-date,渋谷店,商品B,1,500\n"
        "2026-07-02,新宿店,商品A,-1,1200\n"
    )
    path = make_csv("mixed.csv", content)
    rows, errors, file_error = load_file(path)
    assert file_error is None
    assert len(rows) == 1
    assert len(errors) == 2
    # 元ファイルの行番号(ヘッダが1行目なのでデータは2行目から)と対応していること。
    assert errors[0].row_number == 3
    assert errors[1].row_number == 4


def test_load_file_short_row_is_recorded_as_error_not_crash(make_csv) -> None:
    """FIX-01/DEF-006: 列数がヘッダ未満の行(途中で切れたCSV等)でクラッシュせず、
    行エラーとして記録され、処理は継続すること(1行の事故で全体を止めない、の実例)。
    """
    content = (
        f"{VALID_CSV_HEADER}\n"
        "2026-07-01,渋谷店,商品A\n"  # quantity/unit_priceが欠落(列数不足)
        "2026-07-02,新宿店,商品B,2,200\n"  # 後続行は正常に処理される
    )
    path = make_csv("short_row.csv", content)
    rows, errors, file_error = load_file(path)
    assert file_error is None
    assert len(rows) == 1
    assert rows[0].store == "新宿店"
    assert len(errors) == 1
    assert errors[0].row_number == 2
    assert "unit_price" in errors[0].reason_summary


def test_load_file_excess_columns_are_ignored_safely(make_csv) -> None:
    """列数がヘッダより多い行(restkey)は、必須列さえ揃っていれば余分な値を
    無視して正常に処理されること(csv.DictReaderの既定restkey=Noneキーに吸収される)。
    """
    content = (
        f"{VALID_CSV_HEADER}\n"
        "2026-07-01,渋谷店,商品A,3,1200,備考,余分\n"
    )
    path = make_csv("excess_columns.csv", content)
    rows, errors, file_error = load_file(path)
    assert file_error is None
    assert errors == []
    assert len(rows) == 1
    assert rows[0].quantity == 3


# --- load_files: 複数ファイルの集約 -----------------------------------------


def test_load_files_aggregates_across_multiple_files(tmp_path: Path, make_csv) -> None:
    make_csv("store_a.csv", f"{VALID_CSV_HEADER}\n2026-07-01,渋谷店,商品A,1,100\n")
    make_csv("store_b.csv", f"{VALID_CSV_HEADER}\n2026-07-01,新宿店,商品B,2,200\n")
    files = discover_csv_files(tmp_path)
    result = load_files(files)
    assert len(result.rows) == 2
    assert result.row_errors == ()
    assert result.file_errors == ()
    assert result.has_any_valid_row is True


def test_load_files_one_broken_file_does_not_stop_others(tmp_path: Path, make_csv) -> None:
    """1ファイルの文字コード事故で全体を止めない(継続処理)。"""
    make_csv("good.csv", f"{VALID_CSV_HEADER}\n2026-07-01,渋谷店,商品A,1,100\n")
    broken = tmp_path / "broken.csv"
    broken.write_bytes(b"\xff\xfe\x00\x81\x00\xff")
    files = discover_csv_files(tmp_path)
    result = load_files(files)
    assert len(result.rows) == 1
    assert len(result.file_errors) == 1
    assert result.file_errors[0].path == broken


def test_load_files_empty_list_has_no_valid_rows() -> None:
    result = load_files([])
    assert result.has_any_valid_row is False
    assert result.rows == ()
