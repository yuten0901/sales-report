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
    assert sent_body is not None
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
