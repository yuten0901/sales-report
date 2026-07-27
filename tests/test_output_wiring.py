"""出力の配線(呼び出し側)を検証するテスト。

docs/defects.md DEF-013参照。別コンテキストレビューが手動ミューテーションで
実測した通り、`sanitize_csv_field`/`escape_markdown_cell`は関数単体では
テストされていても、**呼び出し側で実際に使われているか**は別のテスト観点であり、
これまで独立して検証されていなかった(呼び出しを削除しても既存テストは
全て通過してしまっていた=12件中8件のミュータントが生存)。

このファイルでは、最終出力を`csv.reader`で再パースして各セルを厳密比較する
(Codexレビュー「assert "'=cmd" in content だけでは列違い・引用処理の破損を
検出できない」という指摘への対応)。
"""

from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pytest
from typer.testing import CliRunner

from sales_report.aggregate import AggregationResult, ProductSummary, StoreSummary
from sales_report.cli import app
from sales_report.loader import FileError, LoadedRowError
from sales_report.models import RowError
from sales_report.notify import build_slack_payload, send_slack_summary
from sales_report.report import (
    render_csv_report,
    render_errors_csv,
    render_markdown_report,
    sanitize_csv_field,
)

from .conftest import VALID_CSV_HEADER, MakeCsv

runner = CliRunner()


def _parse_csv_cells(content: str) -> list[list[str]]:
    """CSV文字列をcsv.readerで再パースし、行×列のセル値として返す。

    文字列比較(in演算子)では列がずれていても偶然一致し得るため、
    実際にCSVとして解釈した結果のセル値を厳密に比較する。
    """
    return list(csv.reader(io.StringIO(content)))


# --- render_csv_report: 商品列のサニタイズ配線(店舗列だけでなく商品列も) -----


def test_wiring_csv_report_sanitizes_product_column_not_only_store() -> None:
    """商品名が危険な接頭辞で始まる場合、CSV出力の商品列が無害化されていること。

    既存の test_render_csv_report_sanitizes_dangerous_store_name は店舗列しか
    検証しておらず、商品列のsanitize_csv_field呼び出しだけを削除しても
    検出できない構造的な欠落があった(別コンテキストの手動ミューテーションで実測)。
    """
    result = AggregationResult(
        by_store=(),
        by_product=(ProductSummary(product="=cmd|evil", quantity=1, amount=Decimal("100")),),
        by_date=(),
        total_quantity=1,
        total_amount=Decimal("100"),
    )
    content = render_csv_report(result)
    rows = _parse_csv_cells(content)

    product_rows = [r for r in rows if r and r[0] == "商品"]
    assert len(product_rows) == 1
    assert product_rows[0][1] == "'=cmd|evil"  # 危険な接頭辞に'が付与されていること


def test_wiring_csv_report_sanitizes_store_column_via_reparse() -> None:
    """店舗列のサニタイズを、文字列の部分一致でなくCSV再パースで厳密に検証する。"""
    result = AggregationResult(
        by_store=(StoreSummary(store="+1+1|evil", quantity=1, amount=Decimal("100")),),
        by_product=(),
        by_date=(),
        total_quantity=1,
        total_amount=Decimal("100"),
    )
    content = render_csv_report(result)
    rows = _parse_csv_cells(content)

    store_rows = [r for r in rows if r and r[0] == "店舗"]
    assert len(store_rows) == 1
    assert store_rows[0][1] == "'+1+1|evil"
    assert store_rows[0][2] == "1"  # 数量列は無害化対象外(数値のまま)
    assert store_rows[0][3] == "100.00"  # 金額列も無害化対象外(FIX2-03: 常に2桁表示)


# --- render_markdown_report: エスケープ配線(店舗列・商品列の両方) -----------


def test_wiring_markdown_report_escapes_pipe_in_store_and_product() -> None:
    """店舗名・商品名にMarkdownテーブル区切り文字`|`が含まれる場合、
    render_markdown_report内でescape_markdown_cell()が実際に呼ばれ、
    出力テーブルの列構造が崩れないこと。
    """
    result = AggregationResult(
        by_store=(StoreSummary(store="渋谷|本店", quantity=1, amount=Decimal("100")),),
        by_product=(ProductSummary(product="商品|A", quantity=1, amount=Decimal("100")),),
        by_date=(),
        total_quantity=1,
        total_amount=Decimal("100"),
    )
    content = render_markdown_report(result)

    # エスケープされていれば「\|」として現れる。
    assert "渋谷\\|本店" in content
    assert "商品\\|A" in content
    # 未エスケープの生の並び("谷|本"のようにバックスラッシュを挟まない形)が
    # 存在しないこと(=列区切りとして誤解釈される生のパイプが残っていない)。
    assert "渋谷|本店" not in content
    assert "商品|A" not in content


def test_wiring_markdown_report_escapes_newline_in_store() -> None:
    """店舗名に改行が含まれる場合もescape_markdown_cell()が適用されること。"""
    result = AggregationResult(
        by_store=(StoreSummary(store="渋谷店\n(本店)", quantity=1, amount=Decimal("100")),),
        by_product=(),
        by_date=(),
        total_quantity=1,
        total_amount=Decimal("100"),
    )
    content = render_markdown_report(result)
    assert "渋谷店 (本店)" in content
    assert "渋谷店\n(本店)" not in content


# --- render_errors_csv: 理由列のサニタイズ配線(パス列だけでなく理由列も) ----


def test_wiring_errors_csv_sanitizes_reason_column_via_reparse() -> None:
    """行エラーの理由(reason)列が危険な接頭辞を含む場合、CSV再パースで
    無害化されていることを確認する(FIX-07ではパス列のみ確認していた。
    理由列のsanitize_csv_field呼び出しだけを削除するミューテーションを
    独立に検出できるようにする)。
    """
    row_errors = [
        LoadedRowError(
            file=Path("sales.csv"),
            row_error=RowError(row_number=3, raw={}, reasons=("=cmd()が原因です",)),
        )
    ]
    content = render_errors_csv(row_errors, [])
    rows = _parse_csv_cells(content)

    error_rows = [r for r in rows if r and r[0] == "行エラー"]
    assert len(error_rows) == 1
    assert error_rows[0][3] == "'=cmd()が原因です"


def test_wiring_errors_csv_sanitizes_path_column_via_reparse() -> None:
    """ファイルエラーのパス列も、CSV再パースで厳密に無害化を確認する(FIX-07)。"""
    file_errors = [FileError(path=Path("@evil.csv"), reason="通常の理由")]
    content = render_errors_csv([], file_errors)
    rows = _parse_csv_cells(content)

    error_rows = [r for r in rows if r and r[0] == "ファイルエラー"]
    assert len(error_rows) == 1
    assert error_rows[0][1] == "'@evil.csv"


def test_wiring_cli_sanitizes_dangerous_directory_name_in_errors_csv_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FIX2-09(Codex#10): サニタイズの検証を、レンダラーへの直接渡し(上記2テスト)
    ではなく、CLI経由の実ファイルパスから発生した経路で行う。

    パス文字列全体がCSVインジェクションの危険な接頭辞で始まるのは、絶対パスの
    場合は通常あり得ない(ドライブ文字や`/`から始まるため)。現実的に起こり
    得るのは、**危険な名前を持つディレクトリを相対パスで`--input`指定した**
    場合(discover_csv_filesがそのディレクトリ配下のファイルを
    `<危険なディレクトリ名>/<ファイル名>`として返すため)。cwdを一時的に
    切り替え、実際にそのようなディレクトリとファイルを作成して検証する。
    """
    monkeypatch.chdir(tmp_path)
    dangerous_dir = Path("=evildir")
    dangerous_dir.mkdir()
    (dangerous_dir / "good.csv").write_text(
        f"{VALID_CSV_HEADER}\n2026-07-01,渋谷店,商品A,1,100\n", encoding="utf-8"
    )
    # 必須列(unit_price)が欠落したファイル→ファイルエラーになる。
    (dangerous_dir / "broken.csv").write_text(
        "date,store,product,quantity\n2026-07-01,渋谷店,商品B,1\n", encoding="utf-8"
    )
    errors_output = Path("errors.csv")

    result = runner.invoke(
        app,
        [
            "--input",
            str(dangerous_dir),
            "--output",
            "summary.md",
            "--report-errors",
            str(errors_output),
        ],
    )

    assert result.exit_code == 0
    assert errors_output.exists()
    content = errors_output.read_text(encoding="utf-8")
    rows = _parse_csv_cells(content)

    error_rows = [r for r in rows if r and r[0] == "ファイルエラー"]
    assert len(error_rows) == 1
    expected_path = str(dangerous_dir / "broken.csv")
    assert error_rows[0][1] == f"'{expected_path}"


# --- notify.py: requests.postの呼び出し引数(timeout)の配線検証 -------------


def test_wiring_send_slack_summary_passes_timeout_to_requests_post() -> None:
    """send_slack_summary()がrequests.post()にtimeoutを実際に渡していること。

    HTTPモック(responsesライブラリ)はワイヤー上のHTTPリクエストしか観測できず、
    タイムアウトはクライアント側の設定でネットワーク上に現れないため、
    responses.callsからは検証できない。requests.post自体をモックして
    呼び出し引数を直接検証する(timeout削除というミューテーションは
    responsesベースの既存テストでは検出できなかった)。
    """
    result = AggregationResult(
        by_store=(), by_product=(), by_date=(), total_quantity=0, total_amount=Decimal("0")
    )

    with mock.patch("sales_report.notify.requests.post") as mock_post:
        mock_post.return_value.raise_for_status.return_value = None
        send_slack_summary("https://hooks.slack.example.com/x", result, timeout=7.5)

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs.get("timeout") == 7.5


# --- notify.py: build_slack_payloadの店舗数/商品数の配線検証 ----------------


def test_wiring_slack_payload_includes_store_and_product_count_labels() -> None:
    """Slack通知本文に店舗数・商品数の行が実際に含まれていること。

    従来の検証は payload["text"] に "3600" や "3" が含まれるかだけを見ており、
    "3"は総数量とも偶然一致するため、店舗数/商品数の行自体を削除しても
    検出できなかった(手動ミューテーションで実測)。ラベル文字列で厳密に確認する。
    """
    result = AggregationResult(
        by_store=(
            StoreSummary(store="渋谷店", quantity=1, amount=Decimal("100")),
            StoreSummary(store="新宿店", quantity=1, amount=Decimal("100")),
        ),
        by_product=(ProductSummary(product="商品A", quantity=2, amount=Decimal("200")),),
        by_date=(),
        total_quantity=2,
        total_amount=Decimal("200"),
    )
    payload = build_slack_payload(result)
    assert "店舗数: 2" in payload["text"]
    assert "商品数: 1" in payload["text"]


# --- cli.py: 構造化ログのskipped_rowsが実際の値と一致するか(部分スキップ時) --


def test_wiring_cli_structured_log_skipped_rows_matches_actual_count(
    tmp_path: Path, make_csv: MakeCsv
) -> None:
    """一部の行がスキップされるケースで、構造化ログのskipped_rowsが
    ハードコードされた0等ではなく、実際のスキップ件数と一致すること。

    既存の構造化ログテストは「全行有効」または「有効行0件」のケースしか
    検証しておらず、部分スキップ時のskipped_rows配線を確認していなかった。
    """
    content = (
        f"{VALID_CSV_HEADER}\n"
        "2026-07-01,渋谷店,商品A,3,1200\n"
        "invalid-date,渋谷店,商品B,1,500\n"
        "2026-07-02,新宿店,商品A,-1,1200\n"
    )
    path = make_csv("mixed.csv", content)
    output = tmp_path / "out" / "summary.md"

    result = runner.invoke(app, ["--input", str(path), "--output", str(output)])

    summary_line = next(line for line in result.output.splitlines() if line.strip().startswith("{"))
    summary = json.loads(summary_line)
    assert summary["skipped_rows"] == 2
    assert summary["valid_rows"] == 1


# --- sanitize_csv_field: CR接頭辞のケース(Codex#10で指摘・パラメータ未整備) --


def test_wiring_sanitize_csv_field_neutralizes_cr_prefix() -> None:
    """`\\r`(復帰)で始まる値も無害化対象であること。

    _CSV_INJECTION_PREFIXESには`\\r`が含まれているが、既存のパラメータ化
    テストには`\\r`始まりのケースが無かった(Codexレビュー指摘)。
    """
    value = "\r=cmd"
    result = sanitize_csv_field(value)
    assert result == f"'{value}"
