"""Unit & integration test untuk Tiket 10: Status Antigravity CLI dan 'Aktif di' dua target.

Menguji:
- read status CLI membaca email dari payload keyring; keyring kosong -> none.
- Email keyring yang tidak ada di DB -> unrecorded.
- Keyring dan ~/.gemini menunjuk email berbeda -> drift_gemini, dan status tetap menampilkan email keyring sebagai Active Account.
- Keyring terkunci -> locked; OS tidak didukung -> unavailable beserta alasan; kegagalan lain -> error.
- Untuk CLI, status menyertakan ringkasan sesi (jumlah hidup/stopped/zombie) dan alasan ketidaktersediaan.
- read status CLI tidak pernah melempar exception ke pemanggil, termasuk saat /proc tidak terbaca.
- Chip Target menandai akun aktif yang tidak tercatat di DB dan kondisi file/keyring bermasalah sesuai matriks status; tooltip memuat teks penuh, email aktif, kondisi, alasan ketidaktersediaan, dan ringkasan sesi.
- Kolom 'Aktif di' menampilkan Antigravity CLI bila hanya aktif di CLI, OpenCode + CLI bila aktif di keduanya, OpenCode bila hanya OpenCode, dan — bila tidak ada — semua case-insensitive.
- Kolom audit DB (applied_target, last_applied_at) tidak dipakai untuk kolom 'Aktif di'; nilainya hanya untuk audit dan tooltip kecil.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest
from PyQt6.QtCore import Qt

from src.integrations.antigravity.constants import KEYRING_SERVICE, KEYRING_USERNAME
from src.integrations.antigravity.ports import (
    OverallStatus,
    TargetCondition,
    TargetStatus,
)
from src.integrations.antigravity.service import AntigravityFacade, compute_active_di
from src.targets import TARGET_ANTIGRAVITY_CLI, TARGET_OPENCODE
from src.ui.components.account_table import AccountTableWidget
from src.ui.components.config_bar import ConfigBarWidget
from tests.fakes import (
    FakeClock,
    FakeKeyring,
    FakeOAuth,
    FakeProcTable,
    FakeRoot,
)


class DummyAccountStorage:

  def __init__(self, existing_emails: Optional[List[str]] = None):
    self.existing_emails = set(e.strip().lower() for e in (existing_emails or []))

  def reconstruct_account(self, account_id: str, password: str = "") -> Dict[str, Any]:
    return {"id": account_id, "email": f"{account_id}@example.com"}

  def mark_applied(self, account_id: str, target: str, applied_at: Optional[int] = None) -> bool:
    return True

  def update_refresh_token(self, account_id: str, new_refresh_token: str, password: str = "") -> bool:
    return True

  def account_exists(self, email: str) -> bool:
    return email.strip().lower() in self.existing_emails


class DummyOpenCodePort:

  def __init__(self, email: Optional[str] = None):
    self.email = email

  def read_accounts_data(self):
    if self.email:
      return {"activeIndex": 0, "accounts": [{"email": self.email}]}, None
    return {"activeIndex": 0, "accounts": []}, None

  def write_accounts_data(self, data: Dict[str, Any]) -> None:
    pass


class DummyGeminiFilesPort:

  def __init__(self, active_email: Optional[str] = None, old_emails: Optional[List[str]] = None):
    self.active_email = active_email
    self.old_emails = old_emails or []

  def read_oauth_creds(self):
    return None

  def write_oauth_creds(self, creds):
    pass

  def read_google_accounts(self):
    if self.active_email is not None or self.old_emails:
      return {"active": self.active_email, "old": self.old_emails}
    return None

  def write_google_accounts(self, accounts):
    pass


class DummyEnvironment:

  def __init__(self, is_linux=True, is_root=False, is_dbus=True, is_locked=False):
    self._linux = is_linux
    self._root = is_root
    self._dbus = is_dbus
    self._locked = is_locked

  def is_linux(self) -> bool:
    return self._linux

  def is_root(self) -> bool:
    return self._root

  def is_dbus_available(self) -> bool:
    return self._dbus

  def is_keyring_locked(self) -> bool:
    return self._locked


class DummyProcessManager:

  def __init__(self, sessions=None, summary=None, raise_exc=None):
    self.sessions = sessions or []
    self.summary = summary
    self.raise_exc = raise_exc

  def detect_sessions(self):
    if self.raise_exc:
      raise self.raise_exc
    return self.sessions

  def summarize_sessions(self):
    if self.raise_exc:
      raise self.raise_exc
    if self.summary is not None:
      return self.summary
    return {"alive": len(self.sessions), "stopped": 0, "zombie": 0}


def _make_keyring_payload(email: str, refresh_token: str = "1//rt_test") -> bytes:
  data = {
      "token": {
          "access_token": "ya29.test",
          "token_type": "Bearer",
          "refresh_token": refresh_token,
          "expiry": "2026-11-21T16:00:00+08:00",
          "expires_in": 3600,
      },
      "auth_method": "consumer",
      "id_token_email": email,
      "writer_id": "test_writer",
  }
  return json.dumps(data).encode("utf-8")


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_cli_read_status_keyring_empty_returns_none():
  """Keyring kosong -> condition none."""
  keyring = FakeKeyring()  # Kosong
  storage = DummyAccountStorage(["user@example.com"])
  proc_mgr = DummyProcessManager(summary={"alive": 1, "stopped": 0, "zombie": 0})
  facade = AntigravityFacade(
      account_storage=storage,
      keyring=keyring,
      gemini_files=DummyGeminiFilesPort(),
      opencode_file=DummyOpenCodePort(),
      oauth=FakeOAuth(),
      process_manager=proc_mgr,
      environment=DummyEnvironment(),
      clock=FakeClock(),
  )

  status = facade.read_status()
  cli_status = status.antigravity_cli
  assert cli_status.condition == TargetCondition.NONE
  assert cli_status.email is None
  assert cli_status.sessions_summary == {"alive": 1, "stopped": 0, "zombie": 0}


def test_cli_read_status_unrecorded():
  """Email di keyring tetapi tidak ada di database -> condition unrecorded."""
  keyring = FakeKeyring()
  keyring.write(KEYRING_SERVICE, KEYRING_USERNAME, _make_keyring_payload("wild@example.com"))
  storage = DummyAccountStorage(["known@example.com"])
  facade = AntigravityFacade(
      account_storage=storage,
      keyring=keyring,
      gemini_files=DummyGeminiFilesPort(active_email="wild@example.com"),
      opencode_file=DummyOpenCodePort(),
      oauth=FakeOAuth(),
      process_manager=DummyProcessManager(),
      environment=DummyEnvironment(),
      clock=FakeClock(),
  )

  status = facade.read_status()
  cli_status = status.antigravity_cli
  assert cli_status.condition == TargetCondition.UNRECORDED
  assert cli_status.email == "wild@example.com"


def test_cli_read_status_drift_gemini():
  """Keyring dan ~/.gemini menunjuk email berbeda -> condition drift_gemini.
  
  Status tetap menampilkan email keyring sebagai email aktif.
  """
  keyring = FakeKeyring()
  keyring.write(KEYRING_SERVICE, KEYRING_USERNAME, _make_keyring_payload("keyring_acc@example.com"))
  storage = DummyAccountStorage(["keyring_acc@example.com", "file_acc@example.com"])
  gemini_files = DummyGeminiFilesPort(active_email="file_acc@example.com")
  facade = AntigravityFacade(
      account_storage=storage,
      keyring=keyring,
      gemini_files=gemini_files,
      opencode_file=DummyOpenCodePort(),
      oauth=FakeOAuth(),
      process_manager=DummyProcessManager(),
      environment=DummyEnvironment(),
      clock=FakeClock(),
  )

  status = facade.read_status()
  cli_status = status.antigravity_cli
  assert cli_status.condition == TargetCondition.DRIFT_GEMINI
  assert cli_status.email == "keyring_acc@example.com"
  assert "Drift terdeteksi" in cli_status.message


def test_cli_read_status_locked_and_unavailable():
  """Keyring terkunci -> locked; OS tidak didukung -> unavailable beserta alasan."""
  # 1. Keyring terkunci
  env_locked = DummyEnvironment(is_locked=True)
  facade_locked = AntigravityFacade(
      account_storage=DummyAccountStorage(),
      keyring=FakeKeyring(),
      gemini_files=DummyGeminiFilesPort(),
      opencode_file=DummyOpenCodePort(),
      oauth=FakeOAuth(),
      process_manager=DummyProcessManager(),
      environment=env_locked,
      clock=FakeClock(),
  )
  st_locked = facade_locked.read_status().antigravity_cli
  assert st_locked.condition == TargetCondition.LOCKED
  assert st_locked.unavailable_reason == "keyring_locked"

  # 2. OS tidak didukung
  env_non_linux = DummyEnvironment(is_linux=False)
  facade_non_linux = AntigravityFacade(
      account_storage=DummyAccountStorage(),
      keyring=FakeKeyring(),
      gemini_files=DummyGeminiFilesPort(),
      opencode_file=DummyOpenCodePort(),
      oauth=FakeOAuth(),
      process_manager=DummyProcessManager(),
      environment=env_non_linux,
      clock=FakeClock(),
  )
  st_non_linux = facade_non_linux.read_status().antigravity_cli
  assert st_non_linux.condition == TargetCondition.UNAVAILABLE
  assert st_non_linux.unavailable_reason == "unsupported_os"


def test_cli_read_status_never_throws_on_proc_failure():
  """read status CLI tidak pernah melempar exception, termasuk bila /proc tidak terbaca."""
  keyring = FakeKeyring()
  keyring.write(KEYRING_SERVICE, KEYRING_USERNAME, _make_keyring_payload("active@example.com"))
  storage = DummyAccountStorage(["active@example.com"])
  proc_mgr = DummyProcessManager(raise_exc=PermissionError("Cannot read /proc"))

  facade = AntigravityFacade(
      account_storage=storage,
      keyring=keyring,
      gemini_files=DummyGeminiFilesPort(active_email="active@example.com"),
      opencode_file=DummyOpenCodePort(),
      oauth=FakeOAuth(),
      process_manager=proc_mgr,
      environment=DummyEnvironment(),
      clock=FakeClock(),
  )

  # Tidak melempar exception
  status = facade.read_status()
  cli_status = status.antigravity_cli
  assert cli_status.condition == TargetCondition.ACTIVE
  assert cli_status.email == "active@example.com"
  # Sesi summary adalah None karena /proc gagal
  assert cli_status.sessions_summary is None


def test_compute_active_di_all_cases():
  """Verifikasi kolom 'Aktif di': Antigravity CLI, OpenCode + CLI, OpenCode, dan — (case-insensitive)."""
  overall = OverallStatus(
      opencode=TargetStatus(
          target=TARGET_OPENCODE,
          email="OpenCodeUser@example.com",
          condition=TargetCondition.ACTIVE,
      ),
      antigravity_cli=TargetStatus(
          target=TARGET_ANTIGRAVITY_CLI,
          email="CliUser@example.com",
          condition=TargetCondition.ACTIVE,
      ),
  )

  # Case-insensitive OpenCode
  assert compute_active_di("opencodeuser@example.com", overall) == "OpenCode"
  assert compute_active_di("OPENCODEUSER@EXAMPLE.COM", overall) == "OpenCode"

  # Case-insensitive CLI
  assert compute_active_di("cliuser@example.com", overall) == "Antigravity CLI"
  assert compute_active_di("CLIUSER@EXAMPLE.COM", overall) == "Antigravity CLI"

  # Bukan keduanya
  assert compute_active_di("other@example.com", overall) == "—"

  # Aktif di keduanya
  both_status = OverallStatus(
      opencode=TargetStatus(
          target=TARGET_OPENCODE,
          email="Shared@example.com",
          condition=TargetCondition.ACTIVE,
      ),
      antigravity_cli=TargetStatus(
          target=TARGET_ANTIGRAVITY_CLI,
          email="shared@EXAMPLE.COM",
          condition=TargetCondition.DRIFT_GEMINI,  # Drift tetap dianggap aktif di CLI
      ),
  )
  assert compute_active_di("SHARED@example.com", both_status) == "OpenCode + CLI"


def test_database_audit_columns_not_used_for_active_di(qtbot):
  """Kolom audit DB (applied_target, last_applied_at) tidak dipakai untuk kolom 'Aktif di';
  nilainya hanya untuk tooltip kecil.
  """
  table_widget = AccountTableWidget()
  qtbot.addWidget(table_widget)

  # Status kenyataan: akun CLI adalah 'real_cli@example.com', opencode tidak ada
  overall = OverallStatus(
      opencode=TargetStatus(
          target=TARGET_OPENCODE,
          email=None,
          condition=TargetCondition.NONE,
      ),
      antigravity_cli=TargetStatus(
          target=TARGET_ANTIGRAVITY_CLI,
          email="real_cli@example.com",
          condition=TargetCondition.ACTIVE,
      ),
  )

  # DB row memiliki applied_target='opencode' (misalnya audit lama yang sudah tidak aktif)
  raw_rows = [
      (
          "acc1",
          "real_cli@example.com",
          None, None, None, None, None, None,
          0, None, "",
          "opencode",  # applied_target di DB berbeda dari kenyataan
          1700000000,  # last_applied_at
      ),
      (
          "acc2",
          "audit_only@example.com",
          None, None, None, None, None, None,
          0, None, "",
          "antigravity_cli",  # applied_target di DB
          1700000000,
      ),
  ]

  table_widget.set_accounts_data(raw_rows, overall_status=overall)

  # Mode __ALL__, row 0 = separator "Tanpa Kategori", row 1 dan 2 = data akun (urutan A-Z email)
  # audit_only@example.com (A) < real_cli@example.com (R), jadi:
  # row 1 = audit_only@example.com, row 2 = real_cli@example.com
  item_audit_only = table_widget.table.item(1, 2)   # audit_only
  item_real_cli = table_widget.table.item(2, 2)      # real_cli

  # real_cli@example.com: kenyataan aktif di CLI meskipun DB mencatat 'opencode'
  assert item_real_cli.text() == "Antigravity CLI"
  # Tooltip memuat audit
  assert "Target terakhir: opencode" in item_real_cli.toolTip()
  assert "Waktu apply:" in item_real_cli.toolTip()

  # audit_only@example.com: kenyataan TIDAK aktif di mana pun meskipun DB mencatat 'antigravity_cli'
  assert item_audit_only.text() == "—"
  assert "Target terakhir: antigravity_cli" in item_audit_only.toolTip()


def test_target_badge_chip_and_tooltip_for_cli(qtbot, tmp_path):
  """Chip Target menandai status CLI dan tooltip memuat teks penuh, email aktif, kondisi,
  alasan ketidaktersediaan, dan ringkasan sesi.
  """
  from PyQt6.QtCore import QSettings
  settings = QSettings(str(tmp_path / "badge_cli.ini"), QSettings.Format.IniFormat)
  config_bar = ConfigBarWidget(settings=settings)
  qtbot.addWidget(config_bar)

  config_bar.target_badge.set_target(TARGET_ANTIGRAVITY_CLI)

  # Status dengan drift dan ringkasan sesi
  st_drift = TargetStatus(
      target=TARGET_ANTIGRAVITY_CLI,
      email="drift_user@example.com",
      condition=TargetCondition.DRIFT_GEMINI,
      message="Drift terdeteksi: Keyring berbeda dengan ~/.gemini.",
      sessions_summary={"alive": 2, "stopped": 1, "zombie": 0},
  )
  config_bar.set_target_status(st_drift)
  badge = config_bar.target_badge

  # Teks chip
  assert "🟡 Drift (~/.gemini)" in badge.text()

  # Tooltip memuat semua info yang disyaratkan
  tip = badge.toolTip()
  assert "Email Aktif: drift_user@example.com" in tip
  assert "Kondisi: drift_gemini" in tip
  assert "Drift terdeteksi" in tip
  assert "Sesi agy: 2 hidup, 1 stopped, 0 zombie" in tip

  # Status unavailable
  st_unavail = TargetStatus(
      target=TARGET_ANTIGRAVITY_CLI,
      email=None,
      condition=TargetCondition.UNAVAILABLE,
      unavailable_reason="unsupported_os",
      message="Target hanya didukung pada OS Linux.",
  )
  config_bar.set_target_status(st_unavail)
  assert "⛔ Tidak tersedia" in badge.text()
  assert "Alasan: Hanya didukung di OS Linux" in badge.toolTip()
