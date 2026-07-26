"""集計結果・エラー情報のレンダリングとファイル出力。

docs/test-design.md の §1.3(出力仕様) に対応する。
- **CSVインジェクション対策**(BV-SEC-01/02): `=` `+` `-` `@` /タブ/CRで始まる値を無害化する。
- **原子的書き込み**: 一時ファイル→os.replace()で、プロセス中断(例外発生)時に
  中途半端な出力を残さない(fsync等の電源断レベルのdurabilityは対象外。C#12b設計裁定)。
- レンダリング(render_*)と書き込み(write_atomic)を分離し、レンダリング結果を
  ゴールデンテスト(tests/test_golden.py)で直接比較できるようにしている。
"""

from __future__ import annotations

import csv
import io
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from sales_report.aggregate import AggregationResult
from sales_report.loader import FileError, LoadedRowError

# CSVインジェクション対策: これらの文字で始まる値はExcel等で数式実行される恐れがある(OWASP推奨)。
_CSV_INJECTION_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r")

SUPPORTED_FORMATS: tuple[str, ...] = ("csv", "markdown")


def sanitize_csv_field(value: str) -> str:
    """BV-SEC-01/02: 危険な接頭辞を持つ文字列の先頭にシングルクォートを付与し無害化する。

    数値列(金額・数量)には適用しない(呼び出し側で文字列フィールドにのみ使うこと)。
    """
    if value and value[0] in _CSV_INJECTION_PREFIXES:
        return f"'{value}"
    return value


def escape_markdown_cell(value: str) -> str:
    """Markdownテーブルのセル内の`|`と改行をエスケープし、表の崩れを防ぐ(セキュリティ目的ではない)。"""
    return value.replace("|", "\\|").replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def render_csv_report(result: AggregationResult) -> str:
    """集計結果をCSV文字列にレンダリングする。改行は\\nに固定し、OS間で決定的にする。"""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["区分", "キー", "数量", "金額"])
    for s in result.by_store:
        writer.writerow(["店舗", sanitize_csv_field(s.store), s.quantity, str(s.amount)])
    for p in result.by_product:
        writer.writerow(["商品", sanitize_csv_field(p.product), p.quantity, str(p.amount)])
    for d in result.by_date:
        writer.writerow(["日付", d.date.isoformat(), d.quantity, str(d.amount)])
    writer.writerow(["合計", "", result.total_quantity, str(result.total_amount)])
    return output.getvalue()


def render_markdown_report(result: AggregationResult) -> str:
    """集計結果をMarkdown文字列にレンダリングする。"""
    lines: list[str] = ["# 売上サマリレポート", ""]

    lines.append("## 店舗別")
    lines.append("")
    lines.append("| 店舗 | 数量 | 金額 |")
    lines.append("|---|---|---|")
    for s in result.by_store:
        lines.append(f"| {escape_markdown_cell(s.store)} | {s.quantity} | {s.amount} |")
    lines.append("")

    lines.append("## 商品別")
    lines.append("")
    lines.append("| 商品 | 数量 | 金額 |")
    lines.append("|---|---|---|")
    for p in result.by_product:
        lines.append(f"| {escape_markdown_cell(p.product)} | {p.quantity} | {p.amount} |")
    lines.append("")

    lines.append("## 日別")
    lines.append("")
    lines.append("| 日付 | 数量 | 金額 |")
    lines.append("|---|---|---|")
    for d in result.by_date:
        lines.append(f"| {d.date.isoformat()} | {d.quantity} | {d.amount} |")
    lines.append("")

    lines.append("## 合計")
    lines.append("")
    lines.append(f"- 総数量: {result.total_quantity}")
    lines.append(f"- 総金額: {result.total_amount}")
    lines.append("")

    return "\n".join(lines)


def render_errors_csv(
    row_errors: Sequence[LoadedRowError],
    file_errors: Sequence[FileError],
) -> str:
    """行エラー・ファイルエラーを理由付きでCSV文字列にレンダリングする。

    FIX-07/DEF-007: ファイルパス列も含め、全ての文字列セルをsanitize_csv_field()
    で無害化する。ファイル名は攻撃者が制御し得る値であり(Linux等では`=evil.csv`
    のようなファイル名も作成可能)、理由列だけを無害化してもパス列が素通しでは
    CSVインジェクション対策として不完全だった。
    """
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["種別", "ファイル", "行番号", "理由"])
    for fe in file_errors:
        writer.writerow(
            ["ファイルエラー", sanitize_csv_field(str(fe.path)), "", sanitize_csv_field(fe.reason)]
        )
    for re_ in row_errors:
        writer.writerow(
            [
                "行エラー",
                sanitize_csv_field(str(re_.file)),
                re_.row_error.row_number,
                sanitize_csv_field(re_.row_error.reason_summary),
            ]
        )
    return output.getvalue()


def has_errors_to_report(
    row_errors: Sequence[LoadedRowError],
    file_errors: Sequence[FileError],
) -> bool:
    """DT-3-03: エラーが0件の場合は空ファイルを作らない、という方針の判定に使う。"""
    return bool(row_errors) or bool(file_errors)


def write_atomic(path: Path, content: str, encoding: str = "utf-8") -> None:
    """一時ファイルに書き込んでからos.replace()で本番パスに置換する。

    処理が中断(例外発生)した際に、プロセス中断時点で中途半端な内容の出力
    ファイルを残さないための実装(電源断・OSクラッシュレベルのdurability
    (fsync)までは対象外。C#12b設計裁定)。改行の自動変換を防ぐため
    newline="" で開く(csv側で\\nに固定済み)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        try:
            f = os.fdopen(fd, "w", encoding=encoding, newline="")
        except BaseException:
            # C#12a(設計裁定): os.fdopen()自体が失敗した場合、fdはまだファイル
            # オブジェクトにラップされていないため、明示的にcloseしないと
            # ファイルディスクリプタがリークする(withブロックの__exit__は
            # __enter__が失敗すると呼ばれない)。Windowsではリークしたfdが
            # ファイルをロックしたままにするため、後続のtmp_path.unlink()自体が
            # PermissionErrorで失敗する実害を確認済み(手動ミューテーションで実測)。
            os.close(fd)
            raise
        with f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
