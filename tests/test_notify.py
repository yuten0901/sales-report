"""notify.py のテスト。responsesライブラリでHTTP通信をモックする。"""

from __future__ import annotations

from decimal import Decimal

import pytest
import requests
import responses

from sales_report.aggregate import AggregationResult, StoreSummary
from sales_report.notify import NotifyError, build_slack_payload, send_slack_summary

_WEBHOOK_URL = "https://hooks.slack.example.com/services/T000/B000/XXXX"


def _sample_result() -> AggregationResult:
    return AggregationResult(
        by_store=(StoreSummary(store="渋谷店", quantity=3, amount=Decimal("3600")),),
        by_product=(),
        by_date=(),
        total_quantity=3,
        total_amount=Decimal("3600"),
    )


def test_build_slack_payload_contains_totals() -> None:
    payload = build_slack_payload(_sample_result())
    assert "3600" in payload["text"]
    assert "3" in payload["text"]


@responses.activate
def test_send_slack_summary_success_posts_expected_payload() -> None:
    responses.add(responses.POST, _WEBHOOK_URL, json={"ok": True}, status=200)

    send_slack_summary(_WEBHOOK_URL, _sample_result())

    assert len(responses.calls) == 1
    sent_body = responses.calls[0].request.body
    assert isinstance(sent_body, bytes)
    assert "3600" in sent_body.decode("utf-8")


@responses.activate
def test_send_slack_summary_raises_notify_error_on_http_error() -> None:
    responses.add(responses.POST, _WEBHOOK_URL, json={"error": "invalid_payload"}, status=400)

    with pytest.raises(NotifyError):
        send_slack_summary(_WEBHOOK_URL, _sample_result())


@responses.activate
def test_send_slack_summary_raises_notify_error_on_connection_failure() -> None:
    responses.add(
        responses.POST,
        _WEBHOOK_URL,
        body=requests.exceptions.ConnectionError("接続できませんでした"),
    )

    with pytest.raises(NotifyError):
        send_slack_summary(_WEBHOOK_URL, _sample_result())


# --- FIX-05/DEF-011: Webhook URL(秘密情報)がエラーメッセージに漏洩しないこと ---

_SECRET_WEBHOOK_URL = "https://hooks.slack.com/services/T00000000/B00000000/SuperSecretToken12345"
_SECRET_TOKEN = "SuperSecretToken12345"


@responses.activate
def test_send_slack_summary_http_error_does_not_leak_webhook_url() -> None:
    """HTTPエラー時、例外メッセージにWebhook URL(秘密情報)が含まれないこと。

    requestsの例外文字列には通常URLが含まれるため、そのまま表示すると
    Slack Webhook URL(URL自体がcredential)がstderr/CIログへ露出する
    (Codex High#8)。ステータスコードのみを表示する形に修正した。
    """
    responses.add(responses.POST, _SECRET_WEBHOOK_URL, json={"error": "boom"}, status=500)

    with pytest.raises(NotifyError) as exc_info:
        send_slack_summary(_SECRET_WEBHOOK_URL, _sample_result())

    message = str(exc_info.value)
    assert _SECRET_TOKEN not in message
    assert _SECRET_WEBHOOK_URL not in message
    assert "500" in message  # ステータスコードは情報として有用なので残す


@responses.activate
def test_send_slack_summary_connection_error_does_not_leak_webhook_url() -> None:
    """接続エラー時も、例外メッセージにWebhook URL(秘密情報)が含まれないこと。"""
    responses.add(
        responses.POST,
        _SECRET_WEBHOOK_URL,
        body=requests.exceptions.ConnectionError(
            f"Failed to establish a new connection to {_SECRET_WEBHOOK_URL}"
        ),
    )

    with pytest.raises(NotifyError) as exc_info:
        send_slack_summary(_SECRET_WEBHOOK_URL, _sample_result())

    message = str(exc_info.value)
    assert _SECRET_TOKEN not in message
    assert _SECRET_WEBHOOK_URL not in message


@responses.activate
def test_send_slack_summary_original_exception_still_chained() -> None:
    """ユーザー表示メッセージからは秘密情報を除去しつつ、原因追跡のため
    元の例外は`raise ... from e`で例外チェーンとして保持されていること。
    """
    responses.add(responses.POST, _SECRET_WEBHOOK_URL, json={"error": "boom"}, status=503)

    with pytest.raises(NotifyError) as exc_info:
        send_slack_summary(_SECRET_WEBHOOK_URL, _sample_result())

    assert isinstance(exc_info.value.__cause__, requests.HTTPError)
