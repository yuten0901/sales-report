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
    except requests.RequestException as e:
        msg = f"Slackへの通知に失敗しました: {e}"
        raise NotifyError(msg) from e
