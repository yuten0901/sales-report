"""CSVファイルの発見・文字コード判定・行パース。

docs/test-design.md の §1.2(ファイル・エンコーディング仕様) / §3(BV-FILE-*, BV-ENC-*)
に対応する。「発見(discover_csv_files)」と「読込・パース(load_files)」を分離し、
それぞれ独立にテストできるようにしている。
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from sales_report.models import REQUIRED_COLUMNS, RowError, SaleRow, parse_row

# utf-8-sig はBOM有無どちらのUTF-8も読める(BOMがあれば取り除き、無ければ通常のUTF-8として読む)。
# 失敗した場合のみ Shift-JIS(cp932) にフォールバックする。
_ENCODINGS_TO_TRY: tuple[str, ...] = ("utf-8-sig", "cp932")


@dataclass(frozen=True, slots=True)
class FileError:
    """ファイル単位のエラー(文字コード判定失敗・ヘッダ不備など)。行単位の問題ではない。"""

    path: Path
    reason: str


@dataclass(frozen=True, slots=True)
class LoadedRowError:
    """どのファイルの何行目かという情報を付与した行エラー。"""

    file: Path
    row_error: RowError


@dataclass(frozen=True, slots=True)
class LoadResult:
    """複数ファイルを読み込んだ結果の集約。"""

    rows: tuple[SaleRow, ...]
    row_errors: tuple[LoadedRowError, ...]
    file_errors: tuple[FileError, ...]

    @property
    def has_any_valid_row(self) -> bool:
        return len(self.rows) > 0


def discover_csv_files(input_path: Path) -> list[Path]:
    """BV-FILE-*, DT-2-01/02: 入力パスからCSVファイルの一覧を発見する。

    入力パスが存在しない場合は FileNotFoundError を送出する(呼び出し側でexit 2に変換)。
    パスは存在するがCSVファイルが1つも無い場合は空リストを返す(これもexit 2の判断材料)。
    順序はソートして固定し、実行ごとの出力を決定的にする(冪等性)。
    """
    if not input_path.exists():
        msg = f"入力パスが存在しません: {input_path}"
        raise FileNotFoundError(msg)
    if input_path.is_file():
        return [input_path]
    return sorted(p for p in input_path.iterdir() if p.is_file() and p.suffix.lower() == ".csv")


def _read_text_with_fallback(path: Path) -> str | None:
    """BV-ENC-01〜04: UTF-8(BOM有無問わず)→Shift-JISの順でデコードを試みる。

    両方失敗した場合は None を返す(呼び出し側でFileErrorに変換)。
    """
    for encoding in _ENCODINGS_TO_TRY:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return None


def load_file(path: Path) -> tuple[list[SaleRow], list[RowError], FileError | None]:
    """1ファイルを読み込み、有効行・行エラー・ファイルエラーのいずれかを返す。

    ファイルエラーが発生した場合、rows/row_errorsは空リストになる(そのファイルは
    まるごとスキップされ、他のファイルの処理は継続される=1ファイルの事故で全体を止めない)。
    """
    text = _read_text_with_fallback(path)
    if text is None:
        return [], [], FileError(
            path=path,
            reason="文字コードを判定できませんでした(UTF-8/Shift-JISいずれでもデコード失敗)",
        )

    # restval=""で列数不足行の欠損値を""にする
    # (既定Noneだとparse_rowでNone.strip()となりクラッシュする。FIX-01/DEF-006)。
    reader = csv.DictReader(io.StringIO(text), restval="")
    if reader.fieldnames is None:
        # BV-FILE-01: 空ファイル(0バイト)はヘッダ自体が存在しない。
        return [], [], FileError(
            path=path,
            reason="ヘッダー行が見つかりません(空ファイルの可能性があります)",
        )

    missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames)
    if missing:
        return [], [], FileError(
            path=path,
            reason=f"必須列が不足しています: {sorted(missing)}",
        )

    rows: list[SaleRow] = []
    errors: list[RowError] = []
    # ヘッダが1行目のため、データ行は2行目から(行番号を実ファイルと一致させる)。
    for row_number, raw in enumerate(reader, start=2):
        row, err = parse_row(raw, row_number=row_number)
        if row is not None:
            rows.append(row)
        if err is not None:
            errors.append(err)
    # BV-FILE-02: ヘッダのみ(データ0行)の場合、ここでrows/errorsが両方空のまま返る。
    return rows, errors, None


def load_files(files: list[Path]) -> LoadResult:
    """複数ファイルを読み込み、結果を集約する。"""
    all_rows: list[SaleRow] = []
    all_row_errors: list[LoadedRowError] = []
    all_file_errors: list[FileError] = []

    for path in files:
        rows, row_errors, file_error = load_file(path)
        all_rows.extend(rows)
        all_row_errors.extend(LoadedRowError(file=path, row_error=e) for e in row_errors)
        if file_error is not None:
            all_file_errors.append(file_error)

    return LoadResult(
        rows=tuple(all_rows),
        row_errors=tuple(all_row_errors),
        file_errors=tuple(all_file_errors),
    )
