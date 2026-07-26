"""CLIのE2Eテスト(typer.testing.CliRunner)。

docs/test-design.md の DT-2(終了コード) / DT-3(出力オプションの組み合わせ)に対応する。
"""

from __future__ import annotations

import json
from pathlib import Path

import responses
from typer.testing import CliRunner

from sales_report.cli import EXIT_NO_DATA, EXIT_SUCCESS, EXIT_USAGE_ERROR, app

from .conftest import VALID_CSV_HEADER

runner = CliRunner()


def _find_json_summary_line(text: str) -> dict:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise AssertionError(f"構造化ログのJSON行が見つかりませんでした: {text!r}")


# --- DT-2: 終了コード -------------------------------------------------------


def test_dt2_01_nonexistent_input_path_exits_usage_error(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    result = runner.invoke(app, ["--input", str(missing)])
    assert result.exit_code == EXIT_USAGE_ERROR


def test_dt2_02_directory_without_csv_exits_usage_error(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("hello")
    result = runner.invoke(app, ["--input", str(tmp_path)])
    assert result.exit_code == EXIT_USAGE_ERROR


def test_dt2_03_zero_valid_rows_exits_no_data(tmp_path: Path, make_csv) -> None:
    path = make_csv("empty_data.csv", f"{VALID_CSV_HEADER}\n")  # ヘッダのみ
    output = tmp_path / "out" / "summary.md"
    result = runner.invoke(app, ["--input", str(path), "--output", str(output)])
    assert result.exit_code == EXIT_NO_DATA
    assert not output.exists()


def test_dt2_04_partial_valid_rows_exits_success_with_warning(
    tmp_path: Path, make_csv
) -> None:
    content = (
        f"{VALID_CSV_HEADER}\n"
        "2026-07-01,渋谷店,商品A,3,1200\n"
        "invalid-date,渋谷店,商品B,1,500\n"
    )
    path = make_csv("mixed.csv", content)
    output = tmp_path / "out" / "summary.md"
    result = runner.invoke(app, ["--input", str(path), "--output", str(output)])
    assert result.exit_code == EXIT_SUCCESS
    assert output.exists()
    assert "スキップ" in result.output


def test_dt2_05_all_valid_rows_exits_success(
    tmp_path: Path, make_csv, valid_csv_content: str
) -> None:
    path = make_csv("all_valid.csv", valid_csv_content)
    output = tmp_path / "out" / "summary.md"
    result = runner.invoke(app, ["--input", str(path), "--output", str(output)])
    assert result.exit_code == EXIT_SUCCESS
    assert output.exists()
    assert "スキップ" not in result.output


def test_bv_file_03_single_row_succeeds(tmp_path: Path, make_csv) -> None:
    content = f"{VALID_CSV_HEADER}\n2026-07-01,渋谷店,商品A,1,100\n"
    path = make_csv("single.csv", content)
    output = tmp_path / "out" / "summary.md"
    result = runner.invoke(app, ["--input", str(path), "--output", str(output)])
    assert result.exit_code == EXIT_SUCCESS


# --- DT-3: 出力オプションの組み合わせ ---------------------------------------


def test_dt3_01_markdown_without_report_errors_skips_error_file(
    tmp_path: Path, make_csv
) -> None:
    content = (
        f"{VALID_CSV_HEADER}\n"
        "2026-07-01,渋谷店,商品A,3,1200\n"
        "invalid-date,渋谷店,商品B,1,500\n"
    )
    path = make_csv("mixed.csv", content)
    output = tmp_path / "out" / "summary.md"
    result = runner.invoke(app, ["--input", str(path), "--output", str(output)])
    assert result.exit_code == EXIT_SUCCESS
    # --report-errors未指定なのでエラーレポートは作られない。


def test_dt3_02_csv_format_with_report_errors_writes_both_files(
    tmp_path: Path, make_csv
) -> None:
    content = (
        f"{VALID_CSV_HEADER}\n"
        "2026-07-01,渋谷店,商品A,3,1200\n"
        "invalid-date,渋谷店,商品B,1,500\n"
    )
    path = make_csv("mixed.csv", content)
    output = tmp_path / "out" / "summary.csv"
    errors_output = tmp_path / "out" / "errors.csv"
    result = runner.invoke(
        app,
        [
            "--input",
            str(path),
            "--format",
            "csv",
            "--output",
            str(output),
            "--report-errors",
            str(errors_output),
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert output.exists()
    assert errors_output.exists()
    assert "dateの形式が不正です" in errors_output.read_text(encoding="utf-8")


def test_dt3_03_report_errors_specified_but_no_skips_creates_no_file(
    tmp_path: Path, make_csv, valid_csv_content: str
) -> None:
    """DT-3-03: エラーが0件なら--report-errors指定時でも空ファイルを作らない。"""
    path = make_csv("all_valid.csv", valid_csv_content)
    output = tmp_path / "out" / "summary.md"
    errors_output = tmp_path / "out" / "errors.csv"
    result = runner.invoke(
        app,
        ["--input", str(path), "--output", str(output), "--report-errors", str(errors_output)],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert not errors_output.exists()


def test_dt3_04_invalid_format_exits_usage_error(
    tmp_path: Path, make_csv, valid_csv_content: str
) -> None:
    path = make_csv("all_valid.csv", valid_csv_content)
    result = runner.invoke(app, ["--input", str(path), "--format", "xml"])
    assert result.exit_code == EXIT_USAGE_ERROR


# --- DT-2-06: 書込失敗(FIX-02/DEF-008) ---------------------------------------


def test_dt2_06_output_write_failure_exits_usage_error_not_no_data(
    tmp_path: Path, make_csv, valid_csv_content: str
) -> None:
    """FIX-02/DEF-008: 出力先に書き込めない場合はexit 2(入力・利用方法エラー)。

    exit 1(=有効明細0件)と衝突させない。修正前は生のOSErrorがtracebackとして
    表示されexit 1になっていた(cronで「データが無かっただけ」と誤認される)。
    """
    path = make_csv("all_valid.csv", valid_csv_content)
    # 出力先の親ディレクトリの位置に、あえて通常ファイルを置いて書込不可の状況を作る。
    blocker = tmp_path / "blocker"
    blocker.write_text("this is a file, not a directory")
    output = blocker / "summary.md"

    result = runner.invoke(app, ["--input", str(path), "--output", str(output)])
    assert result.exit_code == EXIT_USAGE_ERROR
    assert result.exit_code != EXIT_NO_DATA


def test_dt2_06_report_errors_write_failure_exits_usage_error(
    tmp_path: Path, make_csv
) -> None:
    """--report-errorsの書込失敗も同様にexit 2になること。"""
    content = (
        f"{VALID_CSV_HEADER}\n"
        "2026-07-01,渋谷店,商品A,3,1200\n"
        "invalid-date,渋谷店,商品B,1,500\n"
    )
    path = make_csv("mixed.csv", content)
    output = tmp_path / "out" / "summary.md"
    blocker = tmp_path / "blocker"
    blocker.write_text("this is a file, not a directory")
    errors_output = blocker / "errors.csv"

    result = runner.invoke(
        app,
        ["--input", str(path), "--output", str(output), "--report-errors", str(errors_output)],
    )
    assert result.exit_code == EXIT_USAGE_ERROR
    # サマリレポート自体は正常に出力されている(部分的成功→エラーレポート書込のみ失敗)。
    assert output.exists()


# --- 構造化ログ -------------------------------------------------------------


def test_structured_log_summary_emitted_on_success(
    tmp_path: Path, make_csv, valid_csv_content: str
) -> None:
    path = make_csv("all_valid.csv", valid_csv_content)
    output = tmp_path / "out" / "summary.md"
    result = runner.invoke(app, ["--input", str(path), "--output", str(output)])
    summary = _find_json_summary_line(result.output)
    assert summary["exit_code"] == EXIT_SUCCESS
    assert summary["valid_rows"] == 3


def test_structured_log_summary_emitted_on_no_data(tmp_path: Path, make_csv) -> None:
    path = make_csv("empty.csv", f"{VALID_CSV_HEADER}\n")
    result = runner.invoke(app, ["--input", str(path)])
    summary = _find_json_summary_line(result.output)
    assert summary["exit_code"] == EXIT_NO_DATA
    assert summary["valid_rows"] == 0


# --- Slack通知との統合 --------------------------------------------------------


@responses.activate
def test_slack_notify_success_does_not_change_exit_code(
    tmp_path: Path, make_csv, valid_csv_content: str
) -> None:
    webhook = "https://hooks.slack.example.com/services/T0/B0/X"
    responses.add(responses.POST, webhook, json={"ok": True}, status=200)
    path = make_csv("all_valid.csv", valid_csv_content)
    output = tmp_path / "out" / "summary.md"
    result = runner.invoke(
        app, ["--input", str(path), "--output", str(output), "--slack-webhook", webhook]
    )
    assert result.exit_code == EXIT_SUCCESS
    assert len(responses.calls) == 1


@responses.activate
def test_slack_notify_failure_still_succeeds_overall(
    tmp_path: Path, make_csv, valid_csv_content: str
) -> None:
    """通知失敗はレポート生成という主目的の成否に影響させない。"""
    webhook = "https://hooks.slack.example.com/services/T0/B0/X"
    responses.add(responses.POST, webhook, json={"error": "boom"}, status=500)
    path = make_csv("all_valid.csv", valid_csv_content)
    output = tmp_path / "out" / "summary.md"
    result = runner.invoke(
        app, ["--input", str(path), "--output", str(output), "--slack-webhook", webhook]
    )
    assert result.exit_code == EXIT_SUCCESS
    assert output.exists()
    assert "Slack" in result.output
