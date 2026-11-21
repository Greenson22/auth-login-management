"""Antarmuka port dan kontrak data untuk integrasi Antigravity.

Modul ini mendefinisikan port (dependency injection seams) untuk facade service:
penyimpan akun, keyring, file gemini, file opencode, OAuth, manajer proses,
lingkungan, dan jam/waktu.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Tuple


class ApplyStatus(str, Enum):
  SUCCESS = "SUCCESS"
  CANCELLED = "CANCELLED"
  FAILED = "FAILED"


class TargetCondition(str, Enum):
  ACTIVE = "active"
  NONE = "none"
  UNRECORDED = "unrecorded"
  INVALID_FILE = "invalid_file"
  DRIFT_GEMINI = "drift_gemini"
  UNAVAILABLE = "unavailable"
  LOCKED = "locked"
  ERROR = "error"


@dataclass(frozen=True)
class TargetStatus:
  """Status keterpasangan akun dan kesehatan satu target."""

  target: str
  email: Optional[str] = None
  condition: TargetCondition = TargetCondition.NONE
  message: str = ""
  unavailable_reason: Optional[str] = None
  sessions_summary: Optional[Dict[str, int]] = None
  error: Optional[str] = None


@dataclass(frozen=True)
class OverallStatus:
  """Kumpulan status pembacaan semua target."""

  opencode: TargetStatus
  antigravity_cli: TargetStatus

  def get_status(self, target: str) -> TargetStatus:
    if target == "antigravity_cli":
      return self.antigravity_cli
    return self.opencode


@dataclass(frozen=True)
class ApplyPlan:
  """Objek immutable hasil build plan."""

  account_snapshot: Dict[str, Any]
  target: str
  validated_token: Optional[Dict[str, Any]] = None
  detected_sessions: List[Any] = field(default_factory=list)
  target_available: bool = True
  unavailable_reason: Optional[str] = None
  requires_confirmation: bool = False
  error_code: Optional[str] = None
  error_message: Optional[str] = None


@dataclass(frozen=True)
class ApplyResult:
  """Hasil eksekusi apply."""

  status: ApplyStatus
  code: Optional[str] = None
  user_message: str = ""
  action_suggestion: Optional[str] = None
  backup_location: Optional[str] = None
  email: Optional[str] = None
  accounts_count: Optional[int] = None


@dataclass(frozen=True)
class RestoreResult:
  """Hasil pemulihan backup terakhir."""

  status: ApplyStatus
  message: str = ""
  restored_target: Optional[str] = None
  restored_email: Optional[str] = None
  error: Optional[str] = None


# ─── Port Protocols ──────────────────────────────────────────────────────────


class AccountStoragePort(Protocol):
  """Port untuk berinteraksi dengan database akun."""

  def reconstruct_account(self, account_id: str, password: str = "") -> Dict[str, Any]:
    ...

  def mark_applied(self, account_id: str, target: str, applied_at: Optional[int] = None) -> bool:
    ...

  def update_refresh_token(self, account_id: str, new_refresh_token: str, password: str = "") -> bool:
    ...

  def account_exists(self, email: str) -> bool:
    ...


class KeyringPort(Protocol):
  """Port untuk penyimpanan kredensial Secret Service/Keyring."""

  def read(self, service: str, username: str) -> Optional[bytes]:
    ...

  def write(self, service: str, username: str, payload: bytes) -> None:
    ...

  def delete(self, service: str, username: str) -> None:
    ...


class GeminiFilesPort(Protocol):
  """Port untuk membaca dan menulis file ~/.gemini."""

  def read_oauth_creds(self) -> Optional[Dict[str, Any]]:
    ...

  def write_oauth_creds(self, creds: Dict[str, Any]) -> None:
    ...

  def read_google_accounts(self) -> Optional[Dict[str, Any]]:
    ...

  def write_google_accounts(self, accounts: Dict[str, Any]) -> None:
    ...


class OpenCodeFilePort(Protocol):
  """Port untuk membaca, memeriksa, dan menulis file antigravity-accounts.json."""

  def read_accounts_data(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Mengembalikan (parsed_data, error_condition).

    Jika file tidak ada atau json rusak, parsed_data adalah None dan
    error_condition berisi 'invalid_file' atau pesan error.
    """
    ...

  def write_accounts_data(self, data: Dict[str, Any]) -> None:
    ...


class OAuthPort(Protocol):
  """Port untuk validasi dan penukaran OAuth Google token."""

  def exchange_refresh_token(self, refresh_token: str) -> Any:
    ...


class ProcessManagerPort(Protocol):
  """Port untuk deteksi dan pengelolaan proses agy."""

  def detect_sessions(self) -> List[Any]:
    ...

  def terminate_sessions(self, sessions: List[Any], poll_timeout: float = 5.0) -> bool:
    ...


class EnvironmentPort(Protocol):
  """Port untuk memeriksa lingkungan sistem (OS, D-Bus, keyring locked, root)."""

  def is_linux(self) -> bool:
    ...

  def is_root(self) -> bool:
    ...

  def is_dbus_available(self) -> bool:
    ...

  def is_keyring_locked(self) -> bool:
    ...


class ClockPort(Protocol):
  """Port waktu sistem."""

  def now(self) -> float:
    ...

  def monotonic(self) -> float:
    ...

  def sleep(self, seconds: float) -> None:
    ...
