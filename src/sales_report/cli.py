"""コマンドラインインターフェース。

docs/test-design.md §1.4(終了コード の3段階) / DT-2(ファイル/実行結果→終了コード) /
DT-3(出力オプションの組み合わせ) に対応する。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import typer

from sales_report.aggregate import aggregate
from sales_report.loader import discover_csv_files, load_files
from sales_report.logging_setup import build_run_summary, log_run_summary
from sales_report.notify import NotifyError, send_slack_summary
from sales_report.report import (
    SUPPORTED_FORMATS,
    has_errors_to_report,
    render_csv_report,
    render_errors_csv,
    render_markdown_report,
    write_atomic,
)

app = typer.Typer(add_completion=False, help="複数の売上CSVを集計してサマリレポートを出力するCLI")

EXIT_SUCCESS = 0
EXIT_NO_DATA = 1
EXIT_USAGE_ERROR = 2

# FIX2-06(Codex#12): webhook URLは秘密情報であり、CLI引数はシェル履歴・
# プロセス一覧・ジョブ定義に露出する。環境変数での受け渡しを併用可能にする。
_SLACK_WEBHOOK_ENV_VAR = "SALES_REPORT_SLACK_WEBHOOK"


def _find_path_collision(
    input_path: Path, output: Path, report_errors: Path | None
) -> str | None:
    """FIX-03/DEF-009: 入力パスと出力パスの衝突を検出する。

    衝突したまま処理を続けると、元の入力データが集計結果で上書きされ、
    exit 0で気づかれないまま消える(Sonnetの探索的テスト「自己上書きは
    安全」は誤りだった。クラッシュしないこととデータが保全されることは別)。
    パスは resolve() で正規化してから比較する(相対パス表記の違いを吸収)。
    衝突が見つかった場合は理由の文字列を返す(呼び出し側でexit 2にする)。
    """
    input_resolved = input_path.resolve()
    output_resolved = output.resolve()

    if input_path.is_file():
        if output_resolved == input_resolved:
            return f"--outputが--inputと同じファイルです: {output}"
    elif output_resolved == input_resolved or output_resolved.is_relative_to(input_resolved):
        return f"--outputが--inputディレクトリの中を指しています: {output}"

    if report_errors is not None:
        report_errors_resolved = report_errors.resolve()
        if input_path.is_file():
            if report_errors_resolved == input_resolved:
                return f"--report-errorsが--inputと同じファイルです: {report_errors}"
        elif (
            report_errors_resolved == input_resolved
            or report_errors_resolved.is_relative_to(input_resolved)
        ):
            return f"--report-errorsが--inputディレクトリの中を指しています: {report_errors}"

        if report_errors_resolved == output_resolved:
            return f"--report-errorsが--outputと同じファイルです: {report_errors}"

    return None


@app.command()
def main(
    input_path: Path = typer.Option(
        ..., "--input", help="CSVファイル、またはCSVを含むディレクトリのパス"
    ),
    format: str = typer.Option("markdown", "--format", help="出力形式: csv または markdown"),
    output: Path = typer.Option(
        Path("out/summary.md"), "--output", help="サマリレポートの出力先パス"
    ),
    report_errors: Path | None = typer.Option(
        None,
        "--report-errors",
        help="スキップした行の理由付きレポートの出力先(指定時のみ出力)",
    ),
    slack_webhook: str | None = typer.Option(
        None,
        "--slack-webhook",
        help=(
            "指定時、サマリをSlackへ通知する(既定では送信しない)。"
            f"秘密情報のため、可能な場合は環境変数{_SLACK_WEBHOOK_ENV_VAR}の"
            "使用を推奨(このフラグの値はコマンド履歴・プロセス一覧に露出する)"
        ),
    ),
) -> None:
    """複数の売上CSVを読み込み、集計してサマリレポートを出力する。"""
    started_at = time.monotonic()

    if format not in SUPPORTED_FORMATS:
        choices = ", ".join(SUPPORTED_FORMATS)
        typer.echo(f"未対応の--format値です: {format}(選択肢: {choices})", err=True)
        raise typer.Exit(EXIT_USAGE_ERROR)

    try:
        files = discover_csv_files(input_path)
    except FileNotFoundError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(EXIT_USAGE_ERROR) from e

    if not files:
        typer.echo(f"入力パスにCSVファイルが見つかりません: {input_path}", err=True)
        raise typer.Exit(EXIT_USAGE_ERROR)

    collision = _find_path_collision(input_path, output, report_errors)
    if collision is not None:
        typer.echo(f"入力と出力のパスが衝突しています。{collision}", err=True)
        raise typer.Exit(EXIT_USAGE_ERROR)

    result = load_files(files)

    for file_error in result.file_errors:
        typer.echo(
            f"警告: {file_error.path} を読み込めませんでした({file_error.reason})", err=True
        )

    if not result.has_any_valid_row:
        typer.echo("有効な明細が1件もありませんでした。処理を終了します。", err=True)
        summary = build_run_summary(
            input_path=str(input_path),
            files_found=len(files),
            valid_rows=0,
            skipped_rows=len(result.row_errors),
            file_errors=len(result.file_errors),
            started_at=started_at,
            exit_code=EXIT_NO_DATA,
        )
        log_run_summary(summary)
        raise typer.Exit(EXIT_NO_DATA)

    aggregation = aggregate(result.rows)
    content = (
        render_csv_report(aggregation) if format == "csv" else render_markdown_report(aggregation)
    )
    try:
        write_atomic(output, content)
    except OSError as e:
        # FIX-02/DEF-008: 書込失敗はexit 1(=有効明細0件)と衝突させず、
        # 入力・利用方法エラーとしてexit 2にする(cronでの誤認を防ぐ)。
        typer.echo(f"出力先に書き込めませんでした({output}): {e}", err=True)
        raise typer.Exit(EXIT_USAGE_ERROR) from e
    typer.echo(f"サマリレポートを出力しました: {output}")

    if result.row_errors:
        typer.echo(f"警告: {len(result.row_errors)}件の行をスキップしました。", err=True)

    if report_errors is not None and has_errors_to_report(result.row_errors, result.file_errors):
        errors_content = render_errors_csv(result.row_errors, result.file_errors)
        try:
            write_atomic(report_errors, errors_content)
        except OSError as e:
            typer.echo(
                f"エラーレポートの出力先に書き込めませんでした({report_errors}): {e}", err=True
            )
            raise typer.Exit(EXIT_USAGE_ERROR) from e
        typer.echo(f"エラーレポートを出力しました: {report_errors}")

    # FIX2-06(Codex#12): --slack-webhookフラグが明示指定されればそちらを優先し、
    # 無ければ環境変数にフォールバックする(秘密情報をコマンド履歴に残さない経路)。
    resolved_slack_webhook = slack_webhook or os.environ.get(_SLACK_WEBHOOK_ENV_VAR)
    if resolved_slack_webhook:
        try:
            send_slack_summary(resolved_slack_webhook, aggregation)
        except NotifyError as e:
            typer.echo(f"警告: {e}", err=True)

    summary = build_run_summary(
        input_path=str(input_path),
        files_found=len(files),
        valid_rows=len(result.rows),
        skipped_rows=len(result.row_errors),
        file_errors=len(result.file_errors),
        started_at=started_at,
        exit_code=EXIT_SUCCESS,
    )
    log_run_summary(summary)
