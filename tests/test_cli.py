"""CLIのE2Eテスト(typer.testing.CliRunner)。

docs/test-design.md の DT-2(終了コード) / DT-3(出力オプションの組み合わせ)に対応する。
"""

from __future__ import annotations

import json
from pathlib import Path

import responses
from typer.testing import CliRunner

from sales_report.cli import EXIT_NO_DATA, EXIT_SUCCESS, EXIT_USAGE_ERROR, app

from .conftest import VALID_CSV_HEADER, MakeCsv

runner = CliRunner()


def _find_json_summary_line(text: str) -> dict[str, object]:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            result: dict[str, object] = json.loads(line)
            return result
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


def test_a3_non_csv_file_directly_specified_exits_usage_error(tmp_path: Path) -> None:
    """A-3(設計裁定): 非CSVファイルを--inputに直接指定した場合も、
    「ディレクトリにCSVが無い」場合と同じexit 2(usage error)になること
    (修正前はexit 1になっており、同じ入力ミスで終了コードが割れていた)。
    """
    path = tmp_path / "memo.txt"
    path.write_text("this is not a csv")
    result = runner.invoke(app, ["--input", str(path)])
    assert result.exit_code == EXIT_USAGE_ERROR


def test_dt2_03_zero_valid_rows_exits_no_data(tmp_path: Path, make_csv: MakeCsv) -> None:
    path = make_csv("empty_data.csv", f"{VALID_CSV_HEADER}\n")  # ヘッダのみ
    output = tmp_path / "out" / "summary.md"
    result = runner.invoke(app, ["--input", str(path), "--output", str(output)])
    assert result.exit_code == EXIT_NO_DATA
    assert not output.exists()


def test_dt2_04_partial_valid_rows_exits_success_with_warning(
    tmp_path: Path, make_csv: MakeCsv
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
    tmp_path: Path, make_csv: MakeCsv, valid_csv_content: str
) -> None:
    path = make_csv("all_valid.csv", valid_csv_content)
    output = tmp_path / "out" / "summary.md"
    result = runner.invoke(app, ["--input", str(path), "--output", str(output)])
    assert result.exit_code == EXIT_SUCCESS
    assert output.exists()
    assert "スキップ" not in result.output


def test_bv_file_03_single_row_succeeds(tmp_path: Path, make_csv: MakeCsv) -> None:
    content = f"{VALID_CSV_HEADER}\n2026-07-01,渋谷店,商品A,1,100\n"
    path = make_csv("single.csv", content)
    output = tmp_path / "out" / "summary.md"
    result = runner.invoke(app, ["--input", str(path), "--output", str(output)])
    assert result.exit_code == EXIT_SUCCESS


def test_cli_warns_about_file_level_error_but_still_succeeds(tmp_path: Path) -> None:
    """ファイルレベルのエラー(必須列不足等)が発生した場合、警告を表示しつつ
    他の有効なファイルの処理は継続すること(1ファイルの事故で全体を止めない)。

    この経路は以前、test_robustness.pyの冪等性テストが偶然(2回目の実行が
    1回目の出力を入力として誤って拾うことで)カバーしていたが、その欠陥を
    FIX-03で修正した際に偶然のカバレッジも失われた。意図的なテストとして
    こちらに独立させる(偶然のカバレッジに頼らない、という教訓の実例)。
    """
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "good.csv").write_text(
        f"{VALID_CSV_HEADER}\n2026-07-01,渋谷店,商品A,1,100\n", encoding="utf-8"
    )
    # 必須列(unit_price)が欠落したファイル→ファイルレベルエラーになる。
    (input_dir / "broken.csv").write_text(
        "date,store,product,quantity\n2026-07-01,渋谷店,商品B,1\n", encoding="utf-8"
    )
    output = tmp_path / "out" / "summary.md"

    result = runner.invoke(app, ["--input", str(input_dir), "--output", str(output)])

    assert result.exit_code == EXIT_SUCCESS
    assert "broken.csv" in result.output
    assert "読み込めませんでした" in result.output
    assert output.exists()


# --- DT-3: 出力オプションの組み合わせ ---------------------------------------


def test_dt3_01_markdown_without_report_errors_skips_error_file(
    tmp_path: Path, make_csv: MakeCsv
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
    # FIX-10/別コンテキスト指摘: 従来はコメントのみでassertが無く、
    # 「エラーレポートが作られない」ことを実際には検証していなかった。
    # --report-errors未指定なので、出力ディレクトリにsummary.md以外の
    # ファイルが作られていないことを実際に確認する。
    assert output.exists()
    assert sorted(p.name for p in output.parent.iterdir()) == ["summary.md"]


def test_dt3_02_csv_format_with_report_errors_writes_both_files(
    tmp_path: Path, make_csv: MakeCsv
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
    tmp_path: Path, make_csv: MakeCsv, valid_csv_content: str
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
    tmp_path: Path, make_csv: MakeCsv, valid_csv_content: str
) -> None:
    path = make_csv("all_valid.csv", valid_csv_content)
    result = runner.invoke(app, ["--input", str(path), "--format", "xml"])
    assert result.exit_code == EXIT_USAGE_ERROR


# --- DT-2-06: 書込失敗(FIX-02/DEF-008) ---------------------------------------


def test_dt2_06_output_write_failure_exits_usage_error_not_no_data(
    tmp_path: Path, make_csv: MakeCsv, valid_csv_content: str
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
    tmp_path: Path, make_csv: MakeCsv
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


# --- パス衝突検知(FIX-03/DEF-009) -------------------------------------------


def test_fix03_input_file_equals_output_is_rejected_and_data_preserved(
    tmp_path: Path,
) -> None:
    """入力ファイルと--outputが同一パスの場合、exit 2で拒否し元データを破壊しない。

    Codex Critical#2で指摘された公開ブロッカー: 修正前は正常終了(exit 0)し、
    元の入力CSVが集計結果のCSVで上書きされ、気づかれないままデータが消えていた。
    """
    data = tmp_path / "data.csv"
    original_content = f"{VALID_CSV_HEADER}\n2026-01-01,渋谷店,商品A,3,1200\n"
    data.write_text(original_content, encoding="utf-8")

    result = runner.invoke(app, ["--input", str(data), "--format", "csv", "--output", str(data)])

    assert result.exit_code == EXIT_USAGE_ERROR
    # 最重要: 元データが一切変更されていないこと。
    assert data.read_text(encoding="utf-8") == original_content


def test_fix03_output_inside_input_directory_is_rejected(tmp_path: Path) -> None:
    """入力ディレクトリの中に--outputを置く場合もexit 2で拒否する。

    (将来の再実行で自分の出力を入力として拾ってしまう事故を未然に防ぐ)
    """
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "a.csv").write_text(
        f"{VALID_CSV_HEADER}\n2026-01-01,渋谷店,商品A,1,100\n", encoding="utf-8"
    )

    result = runner.invoke(
        app, ["--input", str(input_dir), "--output", str(input_dir / "summary.md")]
    )

    assert result.exit_code == EXIT_USAGE_ERROR
    # 入力ディレクトリに出力ファイルが紛れ込んでいないこと。
    assert sorted(p.name for p in input_dir.iterdir()) == ["a.csv"]


def test_fix03_output_equals_report_errors_is_rejected(tmp_path: Path, make_csv: MakeCsv) -> None:
    """--outputと--report-errorsが同一パスの場合もexit 2で拒否する
    (後から書き込む方が先の内容を上書きする事故を防ぐ)。
    """
    content = (
        f"{VALID_CSV_HEADER}\n"
        "2026-07-01,渋谷店,商品A,3,1200\n"
        "invalid-date,渋谷店,商品B,1,500\n"
    )
    path = make_csv("mixed.csv", content)
    same_path = tmp_path / "same.csv"

    result = runner.invoke(
        app,
        [
            "--input",
            str(path),
            "--format",
            "csv",
            "--output",
            str(same_path),
            "--report-errors",
            str(same_path),
        ],
    )

    assert result.exit_code == EXIT_USAGE_ERROR
    assert not same_path.exists()


def test_fix03_report_errors_equals_input_file_is_rejected(tmp_path: Path) -> None:
    """--report-errorsが--input(単一ファイル)と同一パスの場合もexit 2で拒否する。"""
    data = tmp_path / "data.csv"
    original_content = f"{VALID_CSV_HEADER}\n2026-07-01,渋谷店,商品A,1,100\n"
    data.write_text(original_content, encoding="utf-8")
    output = tmp_path / "out" / "summary.csv"

    result = runner.invoke(
        app,
        [
            "--input",
            str(data),
            "--format",
            "csv",
            "--output",
            str(output),
            "--report-errors",
            str(data),
        ],
    )

    assert result.exit_code == EXIT_USAGE_ERROR
    assert data.read_text(encoding="utf-8") == original_content


def test_fix03_report_errors_inside_input_directory_is_rejected(tmp_path: Path) -> None:
    """--report-errorsが--input(ディレクトリ)の中を指す場合もexit 2で拒否する。"""
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "a.csv").write_text(
        f"{VALID_CSV_HEADER}\n2026-07-01,渋谷店,商品A,1,100\n", encoding="utf-8"
    )
    output = tmp_path / "out" / "summary.csv"

    result = runner.invoke(
        app,
        [
            "--input",
            str(input_dir),
            "--format",
            "csv",
            "--output",
            str(output),
            "--report-errors",
            str(input_dir / "errors.csv"),
        ],
    )

    assert result.exit_code == EXIT_USAGE_ERROR
    assert sorted(p.name for p in input_dir.iterdir()) == ["a.csv"]


def test_fix03_directory_input_with_non_colliding_report_errors_succeeds(
    tmp_path: Path,
) -> None:
    """入力がディレクトリで、--report-errorsが衝突しない場合は正常に成功すること
    (ディレクトリ入力×report_errors指定という組み合わせの誤検知が無いことの確認)。
    """
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "a.csv").write_text(
        f"{VALID_CSV_HEADER}\n2026-07-01,渋谷店,商品A,1,100\ninvalid-date,渋谷店,商品B,1,200\n",
        encoding="utf-8",
    )
    output = tmp_path / "out" / "summary.csv"
    errors_output = tmp_path / "out" / "errors.csv"

    result = runner.invoke(
        app,
        [
            "--input",
            str(input_dir),
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


def test_fix03_normal_separate_paths_still_succeed(
    tmp_path: Path, make_csv: MakeCsv, valid_csv_content: str
) -> None:
    """衝突していない通常の入出力パスは、パス衝突検知の影響を受けず成功すること
    (誤検知(false positive)が無いことの確認)。
    """
    path = make_csv("all_valid.csv", valid_csv_content)
    output = tmp_path / "out" / "summary.md"
    result = runner.invoke(app, ["--input", str(path), "--output", str(output)])
    assert result.exit_code == EXIT_SUCCESS
    assert output.exists()


# --- 構造化ログ -------------------------------------------------------------


def test_structured_log_summary_emitted_on_success(
    tmp_path: Path, make_csv: MakeCsv, valid_csv_content: str
) -> None:
    path = make_csv("all_valid.csv", valid_csv_content)
    output = tmp_path / "out" / "summary.md"
    result = runner.invoke(app, ["--input", str(path), "--output", str(output)])
    summary = _find_json_summary_line(result.output)
    assert summary["exit_code"] == EXIT_SUCCESS
    assert summary["valid_rows"] == 3


def test_structured_log_summary_emitted_on_no_data(tmp_path: Path, make_csv: MakeCsv) -> None:
    path = make_csv("empty.csv", f"{VALID_CSV_HEADER}\n")
    result = runner.invoke(app, ["--input", str(path)])
    summary = _find_json_summary_line(result.output)
    assert summary["exit_code"] == EXIT_NO_DATA
    assert summary["valid_rows"] == 0


# --- Slack通知との統合 --------------------------------------------------------


@responses.activate
def test_slack_notify_success_does_not_change_exit_code(
    tmp_path: Path, make_csv: MakeCsv, valid_csv_content: str
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
    tmp_path: Path, make_csv: MakeCsv, valid_csv_content: str
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
