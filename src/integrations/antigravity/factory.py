"""Perakitan port produksi untuk AntigravityFacade."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

# Daftar jalur ekstra tempat python3-dbus bisa ditemukan di distribusi Linux.
_DBUS_SYSTEM_PATHS = [
    "/usr/lib/python3/dist-packages",
    "/usr/local/lib/python3/dist-packages",
]


def _ensure_dbus_importable() -> None:
    """Tambahkan jalur sistem ke sys.path bila dbus belum bisa diimpor dari venv."""
    try:
        import dbus  # type: ignore[import-not-found]  # noqa: F401
        return
    except ImportError:
        pass
    for p in _DBUS_SYSTEM_PATHS:
        if p not in sys.path:
            sys.path.append(p)


def _try_import_dbus():
    """Coba import dbus, kembalikan modul atau None jika tidak tersedia."""
    _ensure_dbus_importable()
    try:
        import dbus  # type: ignore[import-not-found]
        return dbus
    except ImportError:
        return None


class ProductionAccountStoragePort:
  """Implementasi port penyimpanan akun menggunakan AccountDatabase."""

  def __init__(self, db: AccountDatabase):
    self.db = db

  def reconstruct_account(self, account_id: str, password: str = "") -> Dict[str, Any]:
    raw_json = self.db.reconstruct_json_by_id(account_id, password=password)
    if not raw_json:
      raise ValueError(f"Akun {account_id} tidak ditemukan di database")
    data = json.loads(raw_json)
    accounts = data.get("accounts", [])
    if not accounts:
      raise ValueError(f"Rekonstruksi akun {account_id} menghasilkan accounts kosong")
    return accounts[0]

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
  """Port lingkungan sistem Linux/D-Bus/Root nyata.

  Availability Antigravity CLI diperiksa secara penuh:
  - is_linux()       → OS Linux
  - is_root()        → bukan root
  - is_dbus_available() → D-Bus/Secret Service dapat dihubungi
  - is_keyring_locked() → koleksi Login keyring tidak terkunci

  Di OS non-Linux semua metode D-Bus mengembalikan False/True tanpa
  mencoba import dbus, sehingga aplikasi tetap berjalan untuk OpenCode.
  """

  def is_linux(self) -> bool:
    return sys.platform.startswith("linux")

  def is_root(self) -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0

  def is_dbus_available(self) -> bool:
    """True bila Secret Service/D-Bus dapat dihubungi dan sesi dibuka."""
    if not self.is_linux():
      return False
    dbus = _try_import_dbus()
    if dbus is None:
      return False
    try:
      bus = dbus.SessionBus()
      service_obj = bus.get_object(
          "org.freedesktop.secrets", "/org/freedesktop/secrets"
      )
      iface = dbus.Interface(service_obj, "org.freedesktop.Secret.Service")
      iface.OpenSession("plain", dbus.String("", variant_level=1))
      return True
    except Exception:
      return False

  def is_keyring_locked(self) -> bool:
    """True bila koleksi Login di keyring terkunci.

    Alasan dikembalikan sebagai kode 'keyring_locked' oleh service.
    Jika D-Bus tidak tersedia atau terjadi error, kembalikan False agar
    is_dbus_available() yang melaporkan ketidaktersediaan lebih dulu.
    """
    if not self.is_linux():
      return False
    dbus = _try_import_dbus()
    if dbus is None:
      return False
    try:
      bus = dbus.SessionBus()
      service_obj = bus.get_object(
          "org.freedesktop.secrets", "/org/freedesktop/secrets"
      )
      props_iface = dbus.Interface(service_obj, "org.freedesktop.DBus.Properties")
      collections = props_iface.Get(
          "org.freedesktop.Secret.Service", "Collections"
      )
      # Periksa apakah seluruh koleksi terkunci (semua Locked=True)
      all_locked = True
      has_collection = False
      for coll_path in collections:
        coll_obj = bus.get_object("org.freedesktop.secrets", coll_path)
        coll_props = dbus.Interface(coll_obj, "org.freedesktop.DBus.Properties")
        try:
          locked = coll_props.Get(
              "org.freedesktop.Secret.Collection", "Locked"
          )
          has_collection = True
          if not bool(locked):
            all_locked = False
        except Exception:
          continue
      # Jika tidak ada koleksi sama sekali dianggap tidak terkunci
      return has_collection and all_locked
    except Exception:
      return False


class NullKeyringPort:
  """Port keyring null untuk OS non-Linux.

  Selalu melaporkan tidak tersedia; aplikasi tetap berjalan untuk OpenCode.
  """

  def read(self, service: str, username: str) -> Optional[bytes]:
    return None

  def write(self, service: str, username: str, payload: bytes) -> None:
    raise RuntimeError("Keyring tidak tersedia di OS ini")

  def delete(self, service: str, username: str) -> None:
    pass


class ProductionKeyringPort:
  """Port keyring nyata menggunakan D-Bus/Secret Service (Linux).

  Memanfaatkan python3-dbus yang tersedia di jalur sistem.
  Tiket 09 akan mengisi implementasi penuh write/delete.
  """

  def read(self, service: str, username: str) -> Optional[bytes]:
    """Baca payload keyring sebagai bytes, atau None jika tidak ada."""
    dbus = _try_import_dbus()
    if dbus is None:
      return None
    try:
      bus = dbus.SessionBus()
      service_obj = bus.get_object(
          "org.freedesktop.secrets", "/org/freedesktop/secrets"
      )
      iface = dbus.Interface(service_obj, "org.freedesktop.Secret.Service")
      _path, session = iface.OpenSession("plain", dbus.String("", variant_level=1))
      attrs = dbus.Dictionary(
          {"service": service, "username": username}, signature="ss"
      )
      unlocked, locked = iface.SearchItems(attrs)
      paths = list(unlocked) + list(locked)
      if not paths:
        return None
      item_obj = bus.get_object("org.freedesktop.secrets", paths[0])
      item_iface = dbus.Interface(item_obj, "org.freedesktop.Secret.Item")
      secret = item_iface.GetSecret(session)
      value = secret[2]
      return bytes(bytearray(value))
    except Exception:
      return None

  def write(self, service: str, username: str, payload: bytes) -> None:
    # Implementasi penuh di tiket 09
    pass

  def delete(self, service: str, username: str) -> None:
    # Implementasi penuh di tiket 09
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
  """Merakit AntigravityFacade dengan port produksi.

  Di OS Linux, dipakai ProductionKeyringPort (D-Bus nyata).
  Di OS non-Linux, dipakai NullKeyringPort yang selalu melaporkan tidak
  tersedia sehingga target CLI nonaktif tanpa crash.
  """
  env_port = ProductionEnvironmentPort()
  keyring_port: KeyringPort = (
      ProductionKeyringPort() if env_port.is_linux() else NullKeyringPort()
  )
  return AntigravityFacade(
      account_storage=ProductionAccountStoragePort(db),
      keyring=keyring_port,
      gemini_files=ProductionGeminiFilesPort(gemini_dir),
      opencode_file=RealOpenCodeFilePort(folder_provider),
      oauth=ProductionOAuthPort(),
      process_manager=ProductionProcessManagerPort(),
      environment=env_port,
      clock=ProductionClockPort(),
  )


def check_cli_availability() -> tuple[bool, str]:
  """Periksa apakah Antigravity CLI tersedia dan kembalikan (available, reason_code).

  Dipanggil dari UI saat menu target dibuka (recheck setiap kali menu dibuka).
  Tidak melempar exception.
  """
  env = ProductionEnvironmentPort()
  try:
    if not env.is_linux():
      return False, "unsupported_os"
    if env.is_root():
      return False, "root"
    if not env.is_dbus_available():
      return False, "no_dbus"
    if env.is_keyring_locked():
      return False, "keyring_locked"
    return True, ""
  except Exception:
    return False, "dbus_error"
