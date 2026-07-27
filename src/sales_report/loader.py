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

# FIX2-08(Codex#2): UTF-16はBOMが無いと他エンコーディングと誤判定されやすいため、
# BOMを検出できた場合に限り試行対象に加える(BOM無しUTF-16はスコープ外のまま)。
_UTF16_BOM_PREFIXES: tuple[bytes, ...] = (b"\xff\xfe", b"\xfe\xff")

# 余剰列(ヘッダの列数を超える値)を保持するための予約キー。
_EXTRA_COLUMNS_KEY = "__extra__"


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
        # A-3(設計裁定): 非CSVファイルを直接指定した場合、「ディレクトリ内に
        # CSVが無い」場合と同じ扱い(空リスト→呼び出し側でexit 2)に統一する。
        # 修正前はここで拡張子を見ずにそのまま返し、ファイルレベルエラーを
        # 経由してexit 1(有効明細0件)になっていた。同じ「入力の指定ミス」
        # なのに終了コードが割れていた不整合を解消する。
        if input_path.suffix.lower() == ".csv":
            return [input_path]
        return []
    return sorted(p for p in input_path.iterdir() if p.is_file() and p.suffix.lower() == ".csv")


def _has_utf16_bom(path: Path) -> bool:
    """先頭2バイトがUTF-16のBOM(LE/BE)かどうかを判定する。"""
    with path.open("rb") as f:
        prefix = f.read(2)
    return prefix in _UTF16_BOM_PREFIXES


def _read_text_with_fallback(path: Path) -> str | None:
    """BV-ENC-01〜04: UTF-8(BOM有無問わず)→Shift-JISの順にデコードを**試す**
    (これは文字コードの正式な「判定」ではなく、あくまでベストエフォートの
    フォールバックである。FIX2-08/Codex#2: cp932は受理範囲が非常に広いため、
    UTF-16(BOM無し)・EUC-JP・途中破損したUTF-8等は、エラーにならず
    文字化けした内容として黙って読み込まれ得る。真の文字コード検出
    [chardet等]は導入していない=既知の限界。docs/test-design.md §1.2参照)。

    UTF-16はBOMが検出できた場合のみ試行対象に加える(BOM無しUTF-16は
    cp932等との判別が原理的に難しく、誤判定を増やすだけのため対象外)。

    全て失敗した場合は None を返す(呼び出し側でFileErrorに変換)。
    """
    encodings = ("utf-16", *_ENCODINGS_TO_TRY) if _has_utf16_bom(path) else _ENCODINGS_TO_TRY
    for encoding in encodings:
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
    try:
        text = _read_text_with_fallback(path)
    except OSError as e:
        # FIX-06/DEF-012: 権限エラー・読込中のファイル消失等のI/Oエラーも
        # ファイル単位のエラーとして扱い、他のファイルの処理を継続する
        # (文字コード判定に限らず「1ファイルの事故で全体を止めない」を徹底する)。
        # OSErrorはエンコーディングと無関係のため、全エンコーディングを試す
        # 意味が無く_read_text_with_fallback内では捕捉せずここで一度だけ処理する。
        return [], [], FileError(
            path=path,
            reason=f"ファイルを読み込めませんでした: {e}",
        )
    if text is None:
        return [], [], FileError(
            path=path,
            # FIX2-08(Codex#2): 「判定できませんでした」は文字コード検出を
            # 名乗る表現になってしまうため、実態(フォールバックの試行)に
            # 即した文言に修正。
            reason="対応する文字コード(UTF-8/Shift-JIS)でデコードできませんでした",
        )

    # restval=""で列数不足行の欠損値を""にする
    # (既定Noneだとparse_rowでNone.strip()となりクラッシュする。FIX-01/DEF-006)。
    # restkeyで列数過剰行の余剰値を集約する(FIX2-10/Codex#11: 区切り文字混入
    # 等による列ずれを黙って捨てず検出するため)。
    reader = csv.DictReader(io.StringIO(text), restval="", restkey=_EXTRA_COLUMNS_KEY)
    if reader.fieldnames is None:
        # BV-FILE-01: 空ファイル(0バイト)はヘッダ自体が存在しない。
        return [], [], FileError(
            path=path,
            reason="ヘッダー行が見つかりません(空ファイルの可能性があります)",
        )

    # A-1(設計裁定): ヘッダの前後空白・大文字小文字の揺れを許容する
    # (正規化=strip+casefoldのみ。「売上日→date」等の意味的なエイリアスは
    # 非対応・README/残存リスクに明記)。正規化後の列名から元の列名への
    # 対応表を作り、各行で必須列だけを正規化済みキーとして取り出す。
    normalized_names = [
        name.strip().casefold() for name in reader.fieldnames if name is not None
    ]
    # FIX2-04(Codex#3): 正規化後に同名になる列が複数あると、素朴な辞書内包表記
    # では後の列が前の列を黙って上書きしてしまい、どちらの値が採用されたか
    # 利用者に分からない。売上データの列対応として危険なため、ファイルエラーにする。
    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in normalized_names:
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    if duplicates:
        return [], [], FileError(
            path=path,
            reason=f"重複した列名があります: {sorted(duplicates)}",
        )

    normalized_to_raw = {
        name.strip().casefold(): name for name in reader.fieldnames if name is not None
    }
    missing = set(REQUIRED_COLUMNS) - set(normalized_to_raw)
    if missing:
        return [], [], FileError(
            path=path,
            reason=f"必須列が不足しています: {sorted(missing)}",
        )

    rows: list[SaleRow] = []
    errors: list[RowError] = []
    # ヘッダが1行目のため、データ行は2行目から(行番号を実ファイルと一致させる)。
    for row_number, raw in enumerate(reader, start=2):
        extra_values = raw.get(_EXTRA_COLUMNS_KEY)
        # 末尾の空フィールド(区切り文字の末尾カンマ等)は無害として許容し、
        # 非空の余剰値がある行のみエラーにする(誤検知を避ける)。
        if extra_values and any(v not in (None, "") for v in extra_values):
            translated = {col: raw.get(normalized_to_raw[col], "") for col in REQUIRED_COLUMNS}
            errors.append(
                RowError(
                    row_number=row_number,
                    raw=translated,
                    reasons=("余剰な列があります(区切り文字の混入や列ずれの可能性)",),
                )
            )
            continue
        translated = {col: raw.get(normalized_to_raw[col], "") for col in REQUIRED_COLUMNS}
        row, err = parse_row(translated, row_number=row_number)
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
