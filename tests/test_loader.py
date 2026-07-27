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

from .conftest import VALID_CSV_HEADER, MakeCsv

# --- discover_csv_files ----------------------------------------------------


def test_discover_csv_files_single_file(tmp_path: Path, make_csv: MakeCsv) -> None:
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


def test_discover_csv_files_directory_finds_only_csv_sorted(
    tmp_path: Path, make_csv: MakeCsv
) -> None:
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


def test_discover_csv_files_directory_without_csv_returns_empty(
    tmp_path: Path, make_csv: MakeCsv
) -> None:
    """DT-2-02: ディレクトリは存在するがCSVが1つも無い場合は空リスト(呼び出し側でexit 2)。"""
    (tmp_path / "not-a-csv.txt").write_text("hello")
    result = discover_csv_files(tmp_path)
    assert result == []


# --- load_file: エンコーディング(BV-ENC-*) --------------------------------


def test_load_file_utf8_without_bom(make_csv: MakeCsv, valid_csv_content: str) -> None:
    """BV-ENC-01"""
    path = make_csv("sales.csv", valid_csv_content, encoding="utf-8")
    rows, errors, file_error = load_file(path)
    assert file_error is None
    assert errors == []
    assert len(rows) == 3
    assert rows[0].store == "渋谷店"


def test_load_file_utf8_with_bom(make_csv: MakeCsv, valid_csv_content: str) -> None:
    """BV-ENC-02"""
    path = make_csv("sales.csv", valid_csv_content, encoding="utf-8-sig")
    rows, errors, file_error = load_file(path)
    assert file_error is None
    assert errors == []
    assert len(rows) == 3


def test_load_file_shift_jis(make_csv: MakeCsv, valid_csv_content: str) -> None:
    """BV-ENC-03"""
    path = make_csv("sales.csv", valid_csv_content, encoding="cp932")
    rows, errors, file_error = load_file(path)
    assert file_error is None
    assert errors == []
    assert len(rows) == 3
    assert rows[0].store == "渋谷店"


def test_load_file_utf16_with_bom_is_accepted(make_csv: MakeCsv, valid_csv_content: str) -> None:
    """BV-ENC-05/FIX2-08(Codex#2): BOM付きUTF-16は検出して読み込める
    (BOM無しUTF-16は他エンコーディングとの判別が原理的に難しく対象外のまま)。
    """
    path = make_csv("sales_utf16.csv", valid_csv_content, encoding="utf-16")
    rows, errors, file_error = load_file(path)
    assert file_error is None
    assert errors == []
    assert len(rows) == 3
    assert rows[0].store == "渋谷店"


def test_load_file_cp932_silently_misreads_other_encodings_known_limitation(
    tmp_path: Path,
) -> None:
    """FIX2-08(Codex#2)・既知の限界の明示: cp932は受理範囲が非常に広いため、
    EUC-JP等の他エンコーディングのバイト列でも例外を出さずにデコードでき、
    元の文字と異なる文字化けした内容として黙って読み込まれ得る。

    真の文字コード検出(chardet等)を導入しない限り解消できない構造的な限界
    であり、docs/test-design.md/test-report.mdに残存リスクとして明記する
    (このテストはクラッシュしないことではなく、意味的に誤った内容が
    サイレントに読み込まれてしまう挙動そのものを記録することが目的)。
    """
    # "渋谷店"のEUC-JPバイト列は、UTF-8としてはエラーになるがcp932としては
    # エラーにならずデコードできてしまい、結果は元の文字列と一致しない
    # (文字化け)。他フィールドをASCIIのみにするのは、日本語をUTF-8で
    # 混在させるとマルチバイト境界がずれてcp932自体が失敗してしまい、
    # 「誤読される」という本来示したい限界を再現できなくなるため。
    euc_jp_bytes = "渋谷店".encode("euc-jp")
    path = tmp_path / "euc_jp_misread.csv"
    path.write_bytes(
        f"{VALID_CSV_HEADER}\n2026-07-01,".encode()
        + euc_jp_bytes
        + b",ProductA,3,1200\n"
    )

    rows, errors, file_error = load_file(path)

    assert file_error is None
    assert errors == []
    assert len(rows) == 1
    # 元の"渋谷店"としては読めていない(=文字化けした別の文字列になっている)。
    # これは正しい挙動ではなく、cp932フォールバックの既知の限界の記録。
    assert rows[0].store != "渋谷店"


def test_load_file_undecodable_bytes_becomes_file_error(tmp_path: Path) -> None:
    """BV-ENC-04: UTF-8/Shift-JISいずれでもデコードできないバイト列はファイルエラーになる。"""
    path = tmp_path / "broken.csv"
    # 0x81単独はcp932としても不完全なマルチバイト先頭でありデコード失敗する。
    # FIX2-08でUTF-16 BOM検出を追加したため、`\xff\xfe`始まり(UTF-16 LE BOM)は
    # 意図せずUTF-16として解釈されてしまう。BOMと誤認しないバイト列にする。
    path.write_bytes(b"\x81\xff")
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
    tmp_path: Path, make_csv: MakeCsv
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


def test_load_file_header_only_returns_empty_without_file_error(make_csv: MakeCsv) -> None:
    """BV-FILE-02: ヘッダのみ(データ0行)はファイルエラーにはせず、単に0行を返す。"""
    path = make_csv("header_only.csv", f"{VALID_CSV_HEADER}\n")
    rows, errors, file_error = load_file(path)
    assert rows == []
    assert errors == []
    assert file_error is None


def test_load_file_single_row(make_csv: MakeCsv) -> None:
    """BV-FILE-03: データ1行のみでも正しく読み込める。"""
    content = f"{VALID_CSV_HEADER}\n2026-07-01,渋谷店,商品A,1,100\n"
    path = make_csv("single.csv", content)
    rows, errors, file_error = load_file(path)
    assert file_error is None
    assert errors == []
    assert len(rows) == 1


def test_load_file_missing_required_column(make_csv: MakeCsv) -> None:
    """必須列が欠落している場合はファイルエラーになる(unit_price列が無い)。"""
    content = "date,store,product,quantity\n2026-07-01,渋谷店,商品A,1\n"
    path = make_csv("missing_column.csv", content)
    rows, errors, file_error = load_file(path)
    assert rows == []
    assert errors == []
    assert isinstance(file_error, FileError)
    assert "unit_price" in file_error.reason


def test_load_file_header_with_mixed_case_is_accepted(make_csv: MakeCsv) -> None:
    """A-1(設計裁定): ヘッダの大文字小文字の揺れを許容する(正規化=casefold)。"""
    content = "Date,Store,Product,Quantity,Unit_Price\n2026-07-01,渋谷店,商品A,3,1200\n"
    path = make_csv("mixed_case_header.csv", content)
    rows, errors, file_error = load_file(path)
    assert file_error is None
    assert errors == []
    assert len(rows) == 1
    assert rows[0].store == "渋谷店"


def test_load_file_header_with_surrounding_whitespace_is_accepted(make_csv: MakeCsv) -> None:
    """A-1(設計裁定): ヘッダの前後空白の揺れを許容する(正規化=strip)。"""
    content = " date , store,product , quantity, unit_price \n2026-07-01,渋谷店,商品A,3,1200\n"
    path = make_csv("whitespace_header.csv", content)
    rows, errors, file_error = load_file(path)
    assert file_error is None
    assert errors == []
    assert len(rows) == 1
    assert rows[0].quantity == 3


def test_load_file_duplicate_header_after_normalization_becomes_file_error(
    make_csv: MakeCsv,
) -> None:
    """FIX2-04/DEF-017(Codex#3): 正規化(strip+casefold)後に同名になる列が
    複数ある場合、どちらの値が採用されたか利用者に分からないまま黙って
    後勝ちで上書きされていた(修正前)。ファイルエラーとして明示的に拒否する。
    """
    content = (
        "date,Date,store,product,quantity,unit_price\n"
        "2026-07-01,2026-07-02,渋谷店,商品A,3,1200\n"
    )
    path = make_csv("duplicate_header.csv", content)
    rows, errors, file_error = load_file(path)
    assert rows == []
    assert errors == []
    assert isinstance(file_error, FileError)
    assert "重複した列名" in file_error.reason
    assert "date" in file_error.reason


def test_load_file_duplicate_header_via_whitespace_variant_becomes_file_error(
    make_csv: MakeCsv,
) -> None:
    """FIX2-04: 前後空白違いによる重複(`store`と` store `)も検出すること。"""
    content = (
        "date,store, store ,product,quantity,unit_price\n"
        "2026-07-01,渋谷店,新宿店,商品A,3,1200\n"
    )
    path = make_csv("duplicate_header_whitespace.csv", content)
    rows, errors, file_error = load_file(path)
    assert rows == []
    assert errors == []
    assert isinstance(file_error, FileError)
    assert "重複した列名" in file_error.reason


def test_load_file_semantic_alias_header_is_not_accepted(make_csv: MakeCsv) -> None:
    """A-1(設計裁定・非対応の明示): 「売上日」のような意味的なエイリアスは
    正規化(strip+casefold)の対象外であり、必須列不足として扱われる。
    """
    content = "売上日,store,product,quantity,unit_price\n2026-07-01,渋谷店,商品A,3,1200\n"
    path = make_csv("alias_header.csv", content)
    rows, errors, file_error = load_file(path)
    assert rows == []
    assert isinstance(file_error, FileError)
    assert "date" in file_error.reason


def test_load_file_mixed_valid_and_invalid_rows(make_csv: MakeCsv) -> None:
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


def test_load_file_short_row_is_recorded_as_error_not_crash(make_csv: MakeCsv) -> None:
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


def test_load_file_excess_non_empty_columns_become_row_error(make_csv: MakeCsv) -> None:
    """FIX2-10/DEF-019(Codex#11): 列数がヘッダより多く、かつ余剰値が非空の行は、
    区切り文字の混入・列ずれの可能性がある「データ破損の隠蔽」を避けるため
    行エラーにする(修正前は余剰値を無条件に無視していた)。
    """
    content = f"{VALID_CSV_HEADER}\n2026-07-01,渋谷店,商品A,3,1200,備考,余分\n"
    path = make_csv("excess_columns.csv", content)
    rows, errors, file_error = load_file(path)
    assert file_error is None
    assert rows == []
    assert len(errors) == 1
    assert errors[0].row_number == 2
    assert "余剰な列があります" in errors[0].reason_summary


def test_load_file_trailing_empty_extra_column_is_tolerated(make_csv: MakeCsv) -> None:
    """FIX2-10: 末尾の区切り文字による空の余剰列(例: 行末の`,`)は無害として
    許容し、行エラーにしない(誤検知を避けるため非空の余剰値のみを対象とする)。
    """
    content = f"{VALID_CSV_HEADER}\n2026-07-01,渋谷店,商品A,3,1200,\n"
    path = make_csv("trailing_comma.csv", content)
    rows, errors, file_error = load_file(path)
    assert file_error is None
    assert errors == []
    assert len(rows) == 1
    assert rows[0].quantity == 3


# --- load_files: 複数ファイルの集約 -----------------------------------------


def test_load_files_aggregates_across_multiple_files(tmp_path: Path, make_csv: MakeCsv) -> None:
    make_csv("store_a.csv", f"{VALID_CSV_HEADER}\n2026-07-01,渋谷店,商品A,1,100\n")
    make_csv("store_b.csv", f"{VALID_CSV_HEADER}\n2026-07-01,新宿店,商品B,2,200\n")
    files = discover_csv_files(tmp_path)
    result = load_files(files)
    assert len(result.rows) == 2
    assert result.row_errors == ()
    assert result.file_errors == ()
    assert result.has_any_valid_row is True


def test_load_files_one_broken_file_does_not_stop_others(tmp_path: Path, make_csv: MakeCsv) -> None:
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
