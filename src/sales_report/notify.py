"""Slack Webhookへの集計サマリ通知(オプション機能)。

既定では送信しない(--slack-webhook指定時のみ)。送信失敗はCLI全体の
失敗にはしない設計とし、呼び出し側(cli.py)でNotifyErrorを捕捉して
警告表示に留める(レポート生成という主目的を通知の可用性に依存させない)。
"""

from __future__ import annotations

import requests

from sales_report.aggregate import AggregationResult


class NotifyError(Exception):
    """Slack通知の送信に失敗した場合に送出する。"""


def build_slack_payload(result: AggregationResult) -> dict[str, str]:
    """Slack Incoming Webhook用のペイロードを組み立てる。"""
    text = (
        f"売上サマリ: 総数量 {result.total_quantity} / 総金額 {result.total_amount}円\n"
        f"店舗数: {len(result.by_store)} / 商品数: {len(result.by_product)}"
    )
    return {"text": text}


def send_slack_summary(webhook_url: str, result: AggregationResult, timeout: float = 5.0) -> None:
    """集計サマリをSlackへPOSTする。失敗時はNotifyErrorを送出する。"""
    payload = build_slack_payload(result)
    try:
        response = requests.post(webhook_url, json=payload, timeout=timeout)
        response.raise_for_status()
    except requests.HTTPError as e:
        # FIX-05/DEF-011: Webhook URL自体が秘密情報であり、requestsの例外文字列に
        # URL(トークン含む)が含まれ得るため、そのまま{e}を出さずステータスコード
        # のみを表示する。元例外は`raise ... from e`でチェーンとして保持する
        # (Pythonのtracebackには残るが、ユーザー向け表示メッセージには出さない)。
        status = e.response.status_code if e.response is not None else "unknown"
        msg = f"Slackへの通知に失敗しました(HTTPステータス: {status})"
        raise NotifyError(msg) from e
    except requests.RequestException as e:
        # 接続エラー・タイムアウト等。requestsの例外文字列には接続先URLが
        # 含まれ得るため、種別名のみを表示しURLを露出させない。
        msg = f"Slackへの通知に失敗しました({type(e).__name__})"
        raise NotifyError(msg) from e
