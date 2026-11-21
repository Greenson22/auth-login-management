"""Perakitan port produksi untuk AntigravityFacade."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

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
    acc = accounts[0]
    if "refreshToken" in acc and "refresh_token" not in acc:
      acc["refresh_token"] = acc["refreshToken"]
    elif "refresh_token" in acc and "refreshToken" not in acc:
      acc["refreshToken"] = acc["refresh_token"]
    return acc

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
    if dbus is not None:
      try:
        bus = dbus.SessionBus()
        service_obj = bus.get_object(
            "org.freedesktop.secrets", "/org/freedesktop/secrets"
        )
        iface = dbus.Interface(service_obj, "org.freedesktop.Secret.Service")
        iface.OpenSession("plain", dbus.String("", variant_level=1))
        return True
      except Exception:
        pass

    # Fallback jika secret-tool terpasang dan dapat berkomunikasi dengan Secret Service
    if shutil.which("secret-tool") is not None:
      try:
        # Coba lookup non-destructive probe
        res = subprocess.run(
            ["secret-tool", "search", "--all", "service", "probe_test_nonexistent_12345"],
            capture_output=True,
            check=False,
            timeout=2.0,
        )
        # Jika returncode 0 atau tidak error crash DBus, secret-tool aktif
        if res.returncode == 0:
          return True
        stderr_text = res.stderr.decode("utf-8", errors="replace").lower()
        if "cannot autolaunch d-bus" not in stderr_text and "no such interface" not in stderr_text:
          return True
      except Exception:
        pass

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
  """Port keyring nyata menggunakan D-Bus/Secret Service (Linux) dengan fallback secret-tool."""

  def read(self, service: str, username: str) -> Optional[bytes]:
    """Baca payload keyring sebagai bytes, atau None jika tidak ada."""
    dbus = _try_import_dbus()
    if dbus is not None:
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
        if paths:
          item_obj = bus.get_object("org.freedesktop.secrets", paths[0])
          item_iface = dbus.Interface(item_obj, "org.freedesktop.Secret.Item")
          secret = item_iface.GetSecret(session)
          value = secret[2]
          return bytes(bytearray(value))
      except Exception as exc:
        logger.debug("Gagal membaca keyring via dbus: %s", exc)

    # Fallback via secret-tool bila terpasang
    if shutil.which("secret-tool") is not None:
      try:
        res = subprocess.run(
            ["secret-tool", "lookup", "service", service, "username", username],
            capture_output=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout:
          return res.stdout
      except Exception as exc:
        logger.debug("Gagal membaca keyring via secret-tool: %s", exc)

    return None

  def write(self, service: str, username: str, payload: bytes) -> None:
    """Tulis item keyring dengan atribut service dan username."""
    if not isinstance(payload, bytes):
      raise TypeError("Payload keyring harus bytes")

    label = f"auth-login-management {service} {username}"
    dbus = _try_import_dbus()
    if dbus is not None:
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

        # Cari collection 'default' atau 'login'
        coll_obj = bus.get_object(
            "org.freedesktop.secrets", "/org/freedesktop/secrets/aliases/default"
        )
        coll_iface = dbus.Interface(coll_obj, "org.freedesktop.Secret.Collection")
        properties = dbus.Dictionary({
            "org.freedesktop.Secret.Item.Label": dbus.String(label, variant_level=1),
            "org.freedesktop.Secret.Item.Attributes": dbus.Dictionary(
                {"service": service, "username": username}, signature="ss", variant_level=1
            ),
        }, signature="sv")
        secret_struct = (session, dbus.ByteArray(b""), dbus.ByteArray(payload), dbus.String("text/plain"))
        coll_iface.CreateItem(properties, secret_struct, True)
        return
      except Exception as exc:
        logger.debug("Gagal menulis keyring via dbus: %s", exc)

    # Fallback via secret-tool
    if shutil.which("secret-tool") is not None:
      res = subprocess.run(
          ["secret-tool", "store", "--label", label, "service", service, "username", username],
          input=payload,
          capture_output=True,
          check=False,
      )
      if res.returncode != 0:
        err = res.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"Gagal menulis ke keyring via secret-tool: {err}")
      return

    raise RuntimeError("Tidak ada backend keyring yang tersedia untuk menulis kredensial")

  def delete(self, service: str, username: str) -> None:
    """Hapus item keyring jika ada."""
    dbus = _try_import_dbus()
    if dbus is not None:
      try:
        bus = dbus.SessionBus()
        service_obj = bus.get_object(
            "org.freedesktop.secrets", "/org/freedesktop/secrets"
        )
        iface = dbus.Interface(service_obj, "org.freedesktop.Secret.Service")
        attrs = dbus.Dictionary(
            {"service": service, "username": username}, signature="ss"
        )
        unlocked, locked = iface.SearchItems(attrs)
        for item_path in list(unlocked) + list(locked):
          item_obj = bus.get_object("org.freedesktop.secrets", item_path)
          item_iface = dbus.Interface(item_obj, "org.freedesktop.Secret.Item")
          item_iface.Delete()
        return
      except Exception as exc:
        logger.debug("Gagal menghapus keyring via dbus: %s", exc)

    if shutil.which("secret-tool") is not None:
      subprocess.run(
          ["secret-tool", "clear", "service", service, "username", username],
          capture_output=True,
          check=False,
      )


class ProductionGeminiFilesPort:
  """Port file ~/.gemini nyata (tiket 09).
  
  Membaca dan menulis file oauth_creds.json dan google_accounts.json secara atomic
  dengan mode 0600. Bila direktori ~/.gemini belum ada, dibuat dengan mode 0700.
  """

  def __init__(self, gemini_dir: Optional[Path] = None):
    self.gemini_dir = gemini_dir or (Path.home() / ".gemini")

  def _ensure_dir(self) -> None:
    if not self.gemini_dir.exists():
      self.gemini_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
      try:
        os.chmod(self.gemini_dir, 0o700)
      except Exception:
        pass

  def _write_json_atomic(self, file_path: Path, data: Dict[str, Any]) -> None:
    if file_path.is_symlink():
      raise PermissionError(f"File {file_path.name} adalah symlink, penulisan dibatalkan")

    self._ensure_dir()
    temp_file = file_path.with_name(f"{file_path.name}.tmp")
    content = json.dumps(data, indent=2)
    fd = os.open(temp_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with open(fd, "w", encoding="utf-8") as f:
      f.write(content)
    try:
      os.chmod(temp_file, 0o600)
    except Exception:
      pass
    os.replace(temp_file, file_path)

  def read_oauth_creds(self) -> Optional[Dict[str, Any]]:
    path = self.gemini_dir / "oauth_creds.json"
    if not path.exists() or path.is_symlink():
      return None
    try:
      return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
      return None

  def write_oauth_creds(self, creds: Dict[str, Any]) -> None:
    self._write_json_atomic(self.gemini_dir / "oauth_creds.json", creds)

  def read_google_accounts(self) -> Optional[Dict[str, Any]]:
    path = self.gemini_dir / "google_accounts.json"
    if not path.exists() or path.is_symlink():
      return None
    try:
      return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
      return None

  def write_google_accounts(self, accounts: Dict[str, Any]) -> None:
    self._write_json_atomic(self.gemini_dir / "google_accounts.json", accounts)


class ProductionOAuthPort:
  """Port OAuth nyata (tiket 09) memanggil endpoint token Google."""

  def __init__(self, timeout: float = 30.0):
    self.timeout = timeout

  def exchange_refresh_token(self, refresh_token: str) -> Any:
    from .constants import ANTIGRAVITY_CLIENT_ID, ANTIGRAVITY_CLIENT_SECRET, TOKEN_ENDPOINT
    from .errors import OAuthError
    from tests.fakes import OAuthTokenResponse

    params = {
        "client_id": ANTIGRAVITY_CLIENT_ID,
        "client_secret": ANTIGRAVITY_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
      with urllib.request.urlopen(req, timeout=self.timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as http_err:
      try:
        err_body = json.loads(http_err.read().decode("utf-8"))
        code = err_body.get("error", "oauth_error")
        desc = err_body.get("error_description", str(http_err))
      except Exception:
        code = f"http_{http_err.code}"
        desc = str(http_err)
      raise OAuthError(code, desc)
    except Exception as exc:
      raise RuntimeError(f"Gagal menghubungi server token Google: {exc}")

    expires_in = int(body.get("expires_in", 3600))
    now = time.time()
    return OAuthTokenResponse(
        access_token=body.get("access_token", ""),
        refresh_token=body.get("refresh_token") or None,
        expiry=now + expires_in,
        id_token=body.get("id_token") or None,
        token_type=body.get("token_type", "Bearer"),
        expires_in=expires_in,
    )


from .process import AgySession, LinuxProcessManager


class ProductionProcessManagerPort(LinuxProcessManager):
  """Port proses manager nyata (tiket 07) berbasis Linux /proc."""

  def __init__(self):
    super().__init__()


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
