"""Fake untuk sistem eksternal yang dipakai test.

Fake di sini sengaja tidak mengimpor modul aplikasi. Test merakit service
produksi dengan fake-fake ini lewat port yang sama seperti produksi, sehingga
tidak ada test yang menyentuh keyring asli, ``~/.gemini`` pengguna, database
repo, atau tabel ``/proc`` nyata.
"""

from __future__ import annotations

import base64
import json
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

INTEGRATION_ENV_VAR = "AUTH_MANAGER_RUN_INTEGRATION"


def integration_enabled() -> bool:
  """True bila test integration diminta lewat environment variable."""
  return os.environ.get(INTEGRATION_ENV_VAR, "").strip().lower() in (
      "1",
      "true",
      "yes",
  )


# ─── Jam palsu ───────────────────────────────────────────────────────────────


class FakeClock:
  """Jam deterministik: waktu dinding dan monotonic hanya bergerak saat diminta."""

  def __init__(self, start: float = 1_700_000_000.0):
    self._wall = float(start)
    self._monotonic = 0.0

  def now(self) -> float:
    """Waktu dinding (epoch detik)."""
    return self._wall

  def monotonic(self) -> float:
    """Waktu monotonic yang tidak pernah mundur."""
    return self._monotonic

  def advance(self, seconds: float) -> None:
    if seconds < 0:
      raise ValueError("Waktu palsu tidak bisa mundur")
    self._wall += float(seconds)
    self._monotonic += float(seconds)

  def sleep(self, seconds: float) -> None:
    """Tidur tanpa benar-benar menunggu; hanya memajukan jam."""
    self.advance(seconds)


# ─── Keyring in-memory ───────────────────────────────────────────────────────


class KeyringUnavailableError(RuntimeError):
  """Keyring/D-Bus tidak dapat dihubungi."""


class KeyringLockedError(RuntimeError):
  """Keyring ada tetapi terkunci."""


class FakeKeyring:
  """Keyring in-memory dengan item berbentuk ``(service, username) -> bytes``."""

  def __init__(self):
    self._items: dict[tuple[str, str], bytes] = {}
    self.available = True
    self.locked = False
    self.fail_on_read: Optional[Exception] = None
    self.fail_on_write: Optional[Exception] = None
    self.fail_on_delete: Optional[Exception] = None
    self.reads: list[tuple[str, str]] = []
    self.writes: list[tuple[str, str, bytes]] = []
    self.deletes: list[tuple[str, str]] = []

  def _ensure_available(self) -> None:
    if not self.available:
      raise KeyringUnavailableError("Secret Service/D-Bus tidak tersedia")
    if self.locked:
      raise KeyringLockedError("Keyring terkunci")

  def read(self, service: str, username: str) -> Optional[bytes]:
    self.reads.append((service, username))
    self._ensure_available()
    if self.fail_on_read is not None:
      raise self.fail_on_read
    return self._items.get((service, username))

  def write(self, service: str, username: str, payload: bytes) -> None:
    self._ensure_available()
    if self.fail_on_write is not None:
      raise self.fail_on_write
    if not isinstance(payload, bytes):
      raise TypeError("Payload keyring harus bytes")
    self.writes.append((service, username, payload))
    self._items[(service, username)] = payload

  def delete(self, service: str, username: str) -> None:
    self._ensure_available()
    if self.fail_on_delete is not None:
      raise self.fail_on_delete
    self.deletes.append((service, username))
    self._items.pop((service, username), None)

  @property
  def items(self) -> dict[tuple[str, str], bytes]:
    """Salinan isi keyring agar test tidak bisa mengubah state tanpa port."""
    return dict(self._items)


# ─── Tabel proses /proc palsu ────────────────────────────────────────────────


class ProcTableUnreadableError(OSError):
  """``/proc`` tidak dapat dibaca (misalnya sandbox/Flatpak)."""


@dataclass
class FakeProcEntry:
  pid: int
  argv: list[str]
  state: str = "S"
  uid: int = field(default_factory=os.getuid)
  deny_signals: bool = False
  unkillable: bool = False


class FakeProcTable:
  """Tabel proses in-memory yang meniru pembacaan ``/proc/<pid>``."""

  def __init__(self):
    self.entries: dict[int, FakeProcEntry] = {}
    self.readable = True

  def add(
      self,
      pid: int,
      argv: list[str],
      *,
      state: str = "S",
      uid: Optional[int] = None,
      deny_signals: bool = False,
      unkillable: bool = False,
  ) -> FakeProcEntry:
    entry = FakeProcEntry(
        pid=pid,
        argv=list(argv),
        state=state,
        uid=os.getuid() if uid is None else uid,
        deny_signals=deny_signals,
        unkillable=unkillable,
    )
    self.entries[pid] = entry
    return entry

  def remove(self, pid: int) -> None:
    self.entries.pop(pid, None)

  def _ensure_readable(self) -> None:
    if not self.readable:
      raise ProcTableUnreadableError("Tidak dapat membaca /proc")

  def _entry(self, pid: int) -> FakeProcEntry:
    self._ensure_readable()
    try:
      return self.entries[pid]
    except KeyError as exc:
      raise FileNotFoundError(f"Proses {pid} tidak ada") from exc

  def read_cmdline(self, pid: int) -> list[str]:
    return list(self._entry(pid).argv)

  def read_state(self, pid: int) -> str:
    return self._entry(pid).state

  @staticmethod
  def _stat_line(entry: FakeProcEntry) -> str:
    comm = os.path.basename(entry.argv[0]) if entry.argv else "?"
    return f"{entry.pid} ({comm}) {entry.state} 1 1 1"

  def read_stat(self, pid: int) -> str:
    return self._stat_line(self._entry(pid))

  def pids(self) -> list[int]:
    self._ensure_readable()
    return sorted(self.entries)

  def list_entries(self) -> list[FakeProcEntry]:
    self._ensure_readable()
    return [self.entries[pid] for pid in sorted(self.entries)]

  def apply_signal(self, pid: int, sig: int) -> None:
    """Terapkan efek sinyal ke state proses pada tabel palsu."""
    entry = self._entry(pid)
    if entry.deny_signals:
      raise PermissionError(f"Tidak diizinkan mengirim sinyal ke {pid}")
    if entry.unkillable:
      return
    if sig == signal.SIGCONT and entry.state in ("T", "t"):
      entry.state = "S"
    elif sig in (signal.SIGTERM, signal.SIGKILL):
      entry.state = "Z"

  def write_to(self, proc_root: Path) -> None:
    """Materialisasi tabel menjadi pohon ``/proc`` di filesystem sementara."""
    proc_root.mkdir(parents=True, exist_ok=True)
    for entry in self.entries.values():
      pid_dir = proc_root / str(entry.pid)
      pid_dir.mkdir(parents=True, exist_ok=True)
      (pid_dir / "cmdline").write_bytes(
          b"\0".join(arg.encode() for arg in entry.argv) + b"\0"
      )
      (pid_dir / "stat").write_text(
          self._stat_line(entry) + "\n", encoding="utf-8"
      )


class FakeSignalSender:
  """Pencatat sinyal yang memperbarui state proses pada tabel palsu."""

  def __init__(self, proc_table: FakeProcTable):
    self.proc_table = proc_table
    self.sent: list[tuple[int, int]] = []

  def send(self, pid: int, sig: int) -> None:
    self.sent.append((pid, sig))
    self.proc_table.apply_signal(pid, sig)


# ─── Stub OAuth ──────────────────────────────────────────────────────────────


class OAuthErrorStub(Exception):
  """Error dari endpoint token Google yang bisa dipetakan service."""

  def __init__(self, code: str, description: str = ""):
    self.code = code
    self.description = description
    super().__init__(f"{code}: {description}" if description else code)


def _b64url(data: bytes) -> str:
  return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_id_token(email: str, *, expires_at: Optional[float] = None) -> str:
  """Membuat JWT tanpa tanda tangan yang cukup untuk membaca klaim ``email``."""
  header = {"alg": "none", "typ": "JWT"}
  payload = {"email": email}
  if expires_at is not None:
    payload["exp"] = int(expires_at)
  return ".".join(
      _b64url(json.dumps(part, separators=(",", ":")).encode("utf-8"))
      for part in (header, payload)
  ) + "."


def decode_id_token_email(id_token: str) -> Optional[str]:
  """Membaca klaim email dari payload JWT tanpa memverifikasi tanda tangan."""
  try:
    _, payload_b64, _ = id_token.split(".")
  except ValueError:
    return None
  padded = payload_b64 + "=" * (-len(payload_b64) % 4)
  try:
    payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
  except (ValueError, json.JSONDecodeError):
    return None
  email = payload.get("email")
  return email if isinstance(email, str) and email else None


@dataclass(frozen=True)
class OAuthTokenResponse:
  access_token: str
  refresh_token: Optional[str]
  expiry: float
  id_token: Optional[str]
  token_type: str = "Bearer"
  expires_in: int = 3600

  @property
  def expires_at(self) -> float:
    return self.expiry

  @property
  def email(self) -> Optional[str]:
    return decode_id_token_email(self.id_token) if self.id_token else None


class FakeOAuth:
  """Stub penukaran refresh token dengan respons dan error yang bisa diatur."""

  def __init__(self, clock: Optional[FakeClock] = None):
    self.clock = clock or FakeClock()
    self.calls: list[dict] = []
    self.error: Optional[Exception] = None
    self._response: Optional[OAuthTokenResponse] = None

  def respond_for(
      self,
      email: str,
      *,
      access_token: str = "ya29.fake-access-token",
      refresh_token: Optional[str] = None,
      expires_in: int = 3600,
      id_token: Optional[str] = None,
  ) -> OAuthTokenResponse:
    now = self.clock.now()
    self._response = OAuthTokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expiry=now + expires_in,
        id_token=id_token if id_token is not None else make_id_token(email),
        expires_in=expires_in,
    )
    return self._response

  def fail_with(self, code: str, description: str = "") -> None:
    self.error = OAuthErrorStub(code, description)

  def exchange_refresh_token(self, refresh_token: str, **kwargs) -> OAuthTokenResponse:
    self.calls.append({"refresh_token": refresh_token, **kwargs})
    if self.error is not None:
      raise self.error
    if self._response is None:
      raise AssertionError(
          "FakeOAuth belum dikonfigurasi; panggil respond_for() atau fail_with()"
      )
    return self._response


# ─── Root filesystem sementara ───────────────────────────────────────────────


@dataclass(frozen=True)
class FakeRoot:
  """Struktur direktori sementara yang meniru home dan folder XDG pengguna."""

  root: Path
  home: Path
  config: Path
  state: Path
  data: Path
  cache: Path
  runtime: Path
  work: Path
  proc: Path

  @property
  def gemini_dir(self) -> Path:
    return self.home / ".gemini"

  @property
  def opencode_config_dir(self) -> Path:
    return self.config / "opencode"

  @property
  def opencode_accounts_file(self) -> Path:
    return self.opencode_config_dir / "antigravity-accounts.json"

  @property
  def database_file(self) -> Path:
    return self.work / "accounts_manager.db"

  def make_dirs(self) -> None:
    for path in (
        self.home,
        self.config,
        self.state,
        self.data,
        self.cache,
        self.runtime,
        self.work,
    ):
      path.mkdir(parents=True, exist_ok=True)
    self.runtime.chmod(0o700)
