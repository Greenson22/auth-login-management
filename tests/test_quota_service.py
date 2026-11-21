"""Tests untuk fitur pembaruan kuota real-time (Gemini & Claude)."""

import json
from unittest.mock import MagicMock, patch
import pytest

from src.database import AccountDatabase
from src.integrations.antigravity.quota_service import (
    QuotaRetrievalError,
    exchange_refresh_token_for_access_token,
    fetch_account_quota,
    fetch_user_quota_summary,
    parse_quota_summary_response,
)


SAMPLE_QUOTA_RESPONSE = {
    "groups": [
        {
            "buckets": [
                {
                    "bucketId": "gemini-weekly",
                    "displayName": "Weekly Limit Remaining",
                    "window": "weekly",
                    "resetTime": "2026-11-28T08:39:49Z",
                    "remainingFraction": 0.85,
                }
            ],
            "displayName": "Gemini Models",
            "description": "Models within this group: Gemini Flash, Gemini Pro",
        },
        {
            "buckets": [
                {
                    "bucketId": "3p-weekly",
                    "displayName": "Weekly Limit Remaining",
                    "window": "weekly",
                    "resetTime": "2026-11-28T08:39:49Z",
                    "remainingFraction": 0.50,
                }
            ],
            "displayName": "Claude and GPT models",
            "description": "Models within this group: Claude Opus, Claude Sonnet, GPT-OSS",
        },
    ]
}


def test_parse_quota_summary_response():
  quotas = parse_quota_summary_response(SAMPLE_QUOTA_RESPONSE)

  assert "gemini-flash" in quotas
  assert "gemini-pro" in quotas
  assert "claude" in quotas

  assert quotas["gemini-flash"]["remainingFraction"] == 0.85
  assert quotas["gemini-flash"]["resetTime"] == "2026-11-28T08:39:49Z"
  assert quotas["gemini-pro"]["remainingFraction"] == 0.85
  assert quotas["claude"]["remainingFraction"] == 0.50
  assert quotas["claude"]["resetTime"] == "2026-11-28T08:39:49Z"


def test_exchange_refresh_token_for_access_token_success():
  with patch("urllib.request.urlopen") as mock_urlopen:
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"access_token": "mock_token_123"}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    token = exchange_refresh_token_for_access_token("fake_rt")
    assert token == "mock_token_123"


def test_exchange_refresh_token_error():
  with patch("urllib.request.urlopen", side_effect=Exception("Network failure")):
    with pytest.raises(QuotaRetrievalError) as exc_info:
      exchange_refresh_token_for_access_token("fake_rt")
    assert "Koneksi gagal" in str(exc_info.value)


def test_fetch_user_quota_summary_success():
  with patch("urllib.request.urlopen") as mock_urlopen:
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(SAMPLE_QUOTA_RESPONSE).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    quotas = fetch_user_quota_summary("mock_access_token")
    assert quotas["gemini-flash"]["remainingFraction"] == 0.85
    assert quotas["claude"]["remainingFraction"] == 0.50


def test_fetch_account_quota_orchestration():
  with patch(
      "src.integrations.antigravity.quota_service.exchange_refresh_token_for_access_token",
      return_value="mock_token",
  ), patch(
      "src.integrations.antigravity.quota_service.fetch_user_quota_summary",
      return_value={"gemini-flash": {"remainingFraction": 1.0}},
  ):
    res = fetch_account_quota("rt_valid")
    assert res == {"gemini-flash": {"remainingFraction": 1.0}}


def test_database_update_account_quotas(tmp_path):
  db_file = str(tmp_path / "test_quota.db")
  db = AccountDatabase(db_path=db_file)

  # Insert dummy account
  dummy_acc = {
      "id": "acc-123",
      "email": "test@example.com",
      "refreshToken": "sample_rt",
      "projectId": "test-project",
  }
  db.insert_or_update_json(json.dumps([dummy_acc]))

  # Update quotas
  quotas = {
      "gemini-flash": {
          "remainingFraction": 0.75,
          "resetTime": "2026-12-01T00:00:00Z",
          "remainingFractionResetTime": "2026-12-01T00:00:00Z",
          "modelCount": 11,
      },
      "claude": {
          "remainingFraction": 0.40,
          "resetTime": "2026-12-01T00:00:00Z",
          "remainingFractionResetTime": "2026-12-01T00:00:00Z",
          "modelCount": 2,
      },
  }
  success = db.update_account_quotas("acc-123", quotas)
  assert success is True

  # Verifikasi dari database
  rows = db.fetch_accounts_summary()
  assert len(rows) == 1
  row = rows[0]
  # row indices: [id, email, flash_reset, flash_frac, pro_reset, pro_frac, claude_reset, claude_frac, ...]
  assert row[1] == "test@example.com"
  assert row[2] == "2026-12-01T00:00:00Z"
  assert pytest.approx(row[3]) == 0.75
  assert row[6] == "2026-12-01T00:00:00Z"
  assert pytest.approx(row[7]) == 0.40
