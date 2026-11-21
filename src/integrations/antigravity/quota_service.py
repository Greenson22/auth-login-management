"""Service untuk mengambil dan memperbarui kuota model (Gemini & Claude) secara langsung dari Google Cloud Code backend."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional
import urllib.error
import urllib.parse
import urllib.request

from src.integrations.antigravity.constants import (
    ANTIGRAVITY_CLIENT_ID,
    ANTIGRAVITY_CLIENT_SECRET,
    TOKEN_ENDPOINT,
)

logger = logging.getLogger(__name__)

# Endpoint Google Cloud Code untuk kuota. Antigravity CLI menggunakan daily-cloudcode-pa untuk kuota terbaru.
QUOTA_ENDPOINTS = [
    "https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary",
    "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary",
]
QUOTA_SUMMARY_ENDPOINT = QUOTA_ENDPOINTS[0]


class QuotaRetrievalError(Exception):
  """Exception saat gagal mengambil kuota dari server."""
  pass


def exchange_refresh_token_for_access_token(
    refresh_token: str,
    client_id: str = ANTIGRAVITY_CLIENT_ID,
    client_secret: str = ANTIGRAVITY_CLIENT_SECRET,
    token_endpoint: str = TOKEN_ENDPOINT,
    timeout: float = 15.0,
) -> str:
  """Menukar refresh_token dengan access_token via Google OAuth2 token endpoint."""
  payload = {
      "client_id": client_id,
      "client_secret": client_secret,
      "refresh_token": refresh_token,
      "grant_type": "refresh_token",
  }
  data = urllib.parse.urlencode(payload).encode("utf-8")
  req = urllib.request.Request(
      token_endpoint,
      data=data,
      headers={"Content-Type": "application/x-www-form-urlencoded"},
      method="POST",
  )

  try:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
      resp_data = json.loads(resp.read().decode("utf-8"))
      access_token = resp_data.get("access_token")
      if not access_token:
        raise QuotaRetrievalError("Token respons tidak mengandung access_token.")
      return access_token
  except urllib.error.HTTPError as exc:
    err_body = exc.read().decode("utf-8", errors="replace")
    logger.error("OAuth token refresh failed with code %d: %s", exc.code, err_body)
    try:
      err_json = json.loads(err_body)
      desc = err_json.get("error_description") or err_json.get("error") or err_body
    except Exception:
      desc = err_body
    raise QuotaRetrievalError(f"Gagal refresh access token ({exc.code}): {desc}") from exc
  except Exception as exc:
    logger.error("Error refreshing token: %s", exc)
    raise QuotaRetrievalError(f"Koneksi gagal saat refresh token: {exc}") from exc


def parse_quota_summary_response(resp_dict: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
  """Mengurai respons JSON dari retrieveUserQuotaSummary ke format cachedQuota internal.

  Format respons server memiliki kelompok 'gemini-weekly' dan '3p-weekly' (Claude & GPT).
  """
  parsed_quota: Dict[str, Dict[str, Any]] = {}
  groups = resp_dict.get("groups", [])

  gemini_frac = 1.0
  gemini_reset = ""
  claude_frac = 1.0
  claude_reset = ""
  found_gemini = False
  found_claude = False

  for g in groups:
    buckets = g.get("buckets", [])
    for b in buckets:
      bucket_id = str(b.get("bucketId", "")).lower()
      rem_frac = b.get("remainingFraction")
      r_time = b.get("resetTime", "")

      if "gemini" in bucket_id:
        found_gemini = True
        gemini_frac = float(rem_frac) if rem_frac is not None else 1.0
        gemini_reset = r_time
      elif "3p" in bucket_id or "claude" in bucket_id:
        found_claude = True
        claude_frac = float(rem_frac) if rem_frac is not None else 1.0
        claude_reset = r_time

  if found_gemini:
    parsed_quota["gemini-flash"] = {
        "remainingFraction": gemini_frac,
        "resetTime": gemini_reset,
        "remainingFractionResetTime": gemini_reset,
        "modelCount": 11,
    }
    parsed_quota["gemini-pro"] = {
        "remainingFraction": gemini_frac,
        "resetTime": gemini_reset,
        "remainingFractionResetTime": gemini_reset,
        "modelCount": 1,
    }

  if found_claude:
    parsed_quota["claude"] = {
        "remainingFraction": claude_frac,
        "resetTime": claude_reset,
        "remainingFractionResetTime": claude_reset,
        "modelCount": 2,
    }

  return parsed_quota


def fetch_user_quota_summary(
    access_token: str,
    project_id: str = "aicode-consumers",
    endpoint: Optional[str] = None,
    timeout: float = 15.0,
) -> Dict[str, Dict[str, Any]]:
  """Memanggil retrieveUserQuotaSummary API dan mengembalikan mapping quota."""
  body = json.dumps({"project": project_id or "aicode-consumers"}).encode("utf-8")
  headers = {
      "Authorization": f"Bearer {access_token}",
      "Content-Type": "application/json",
      "User-Agent": "antigravity/hub/2.28.2 (aidev_client; os_type=linux; arch=x64)",
  }

  target_endpoints = [endpoint] if endpoint else QUOTA_ENDPOINTS
  last_err = None

  for ep in target_endpoints:
    req = urllib.request.Request(
        ep,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
      with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp_data = json.loads(resp.read().decode("utf-8"))
        return parse_quota_summary_response(resp_data)
    except urllib.error.HTTPError as exc:
      err_body = exc.read().decode("utf-8", errors="replace")
      logger.warning("Quota summary request to %s failed with code %d: %s", ep, exc.code, err_body)
      try:
        err_json = json.loads(err_body)
        err_msg = err_json.get("error", {}).get("message") or err_body
      except Exception:
        err_msg = err_body
      last_err = QuotaRetrievalError(f"Server menolak request kuota ({exc.code}): {err_msg}")
    except Exception as exc:
      logger.warning("Error fetching quota summary from %s: %s", ep, exc)
      last_err = QuotaRetrievalError(f"Koneksi gagal saat mengambil kuota: {exc}")

  if last_err:
    raise last_err
  raise QuotaRetrievalError("Gagal mengambil kuota dari seluruh endpoint.")


def fetch_account_quota(
    refresh_token: str,
    project_id: str = "aicode-consumers",
    timeout: float = 15.0,
) -> Dict[str, Dict[str, Any]]:
  """Orkestrasi: Refresh access token lalu ambil quota terbaru."""
  clean_token = (refresh_token or "").strip()
  if not clean_token:
    raise QuotaRetrievalError("Refresh token kosong atau tidak valid.")

  access_token = exchange_refresh_token_for_access_token(
      clean_token,
      timeout=timeout,
  )
  return fetch_user_quota_summary(
      access_token,
      project_id=project_id,
      timeout=timeout,
  )
