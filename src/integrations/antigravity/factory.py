"""Perakitan port produksi untuk AntigravityFacade."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.database import AccountDatabase
from .opencode_file import RealOpenCodeFilePort
from .ports import (
    AccountStoragePort,
    ClockPort,
    EnvironmentPort,
    GeminiFilesPort,
    KeyringPort,
    OAuthPort,
    ProcessManagerPort,
)
from .service import AntigravityFacade


class ProductionAccountStoragePort:
  """Implementasi port penyimpanan akun menggunakan AccountDatabase."""

  def __init__(self, db: AccountDatabase):
    self.db = db

  def reconstruct_account(self, account_id: str, password: str = "") -> Dict[str, Any]:
    return self.db.reconstruct_json_by_id(account_id, current_password=password)

  def mark_applied(self, account_id: str, target: str, applied_at: Optional[int] = None) -> bool:
    return self.db.mark_applied(account_id, target, applied_at=applied_at)

  def update_refresh_token(self, account_id: str, new_refresh_token: str, password: str = "") -> bool:
    return self.db.update_refresh_token(account_id, new_refresh_token, password=password)

  def account_exists(self, email: str) -> bool:
    rows = self.db.fetch_accounts_summary()
    target_clean = email.strip().lower()
    for row in rows:
      if len(row) > 1 and row[1] and str(row[1]).strip().lower() == target_clean:
        return True
    return False


class ProductionClockPort:
  """Port waktu nyata menggunakan modul time."""

  def now(self) -> float:
    return time.time()

  def monotonic(self) -> float:
    return time.monotonic()

  def sleep(self, seconds: float) -> None:
    time.sleep(seconds)


class ProductionEnvironmentPort:
  """Port lingkungan sistem Linux/D-Bus/Root nyata."""

  def is_linux(self) -> bool:
    return sys.platform.startswith("linux")

  def is_root(self) -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0

  def is_dbus_available(self) -> bool:
    if not self.is_linux():
      return False
    try:
      import dbus
      bus = dbus.SessionBus()
      return bus is not None
    except Exception:
      return False

  def is_keyring_locked(self) -> bool:
    # Pemeriksaan mendalam diimplementasikan pada tiket 06
    return False


class ProductionKeyringPort:
  """Port keyring nyata (akan dilengkapi penuh di tiket 06/09)."""

  def read(self, service: str, username: str) -> Optional[bytes]:
    return None

  def write(self, service: str, username: str, payload: bytes) -> None:
    pass

  def delete(self, service: str, username: str) -> None:
    pass


class ProductionGeminiFilesPort:
  """Port file ~/.gemini nyata (tiket 09)."""

  def __init__(self, gemini_dir: Optional[Path] = None):
    self.gemini_dir = gemini_dir or Path.home() / ".gemini"

  def read_oauth_creds(self) -> Optional[Dict[str, Any]]:
    return None

  def write_oauth_creds(self, creds: Dict[str, Any]) -> None:
    pass

  def read_google_accounts(self) -> Optional[Dict[str, Any]]:
    return None

  def write_google_accounts(self, accounts: Dict[str, Any]) -> None:
    pass


class ProductionOAuthPort:
  """Port OAuth nyata (tiket 09)."""

  def exchange_refresh_token(self, refresh_token: str) -> Any:
    raise NotImplementedError("OAuth exchange nyata tersedia di tiket 09")


class ProductionProcessManagerPort:
  """Port proses manager nyata (tiket 07)."""

  def detect_sessions(self) -> List[Any]:
    return []

  def terminate_sessions(self, sessions: List[Any], poll_timeout: float = 5.0) -> bool:
    return True


def create_facade(
    db: AccountDatabase,
    folder_provider,
    *,
    gemini_dir: Optional[Path] = None,
) -> AntigravityFacade:
  """Merakit AntigravityFacade dengan port produksi."""
  return AntigravityFacade(
      account_storage=ProductionAccountStoragePort(db),
      keyring=ProductionKeyringPort(),
      gemini_files=ProductionGeminiFilesPort(gemini_dir),
      opencode_file=RealOpenCodeFilePort(folder_provider),
      oauth=ProductionOAuthPort(),
      process_manager=ProductionProcessManagerPort(),
      environment=ProductionEnvironmentPort(),
      clock=ProductionClockPort(),
  )
