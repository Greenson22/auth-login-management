"""Unit & integration test untuk Facade service, status OpenCode, dan kolom 'Aktif di'."""

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHeaderView, QTableWidgetItem

from src.database import AccountDatabase
from src.integrations.antigravity.factory import create_facade
from src.integrations.antigravity.ports import (
    ApplyPlan,
    ApplyStatus,
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


# ─── Fake Implementations untuk Port Facade ──────────────────────────────────


class FakeAccountStorage:

  def __init__(self, existing_emails=None):
    self.accounts = {}
    self.applied = []
    self.updated_tokens = []
    self.existing_emails = set(e.lower() for e in (existing_emails or []))

  def reconstruct_account(self, account_id: str, password: str = "") -> Dict[str, Any]:
    if account_id in self.accounts:
      return self.accounts[account_id]
    return {"id": account_id, "email": f"{account_id}@example.com"}

  def mark_applied(self, account_id: str, target: str, applied_at: Optional[int] = None) -> bool:
    self.applied.append((account_id, target, applied_at))
    return True

  def update_refresh_token(self, account_id: str, new_refresh_token: str, password: str = "") -> bool:
    self.updated_tokens.append((account_id, new_refresh_token))
    return True

  def account_exists(self, email: str) -> bool:
    return email.lower() in self.existing_emails


class FakeOpenCodeFile:

  def __init__(self, data: Optional[Dict[str, Any]] = None, error: Optional[str] = None):
    self.data = data
    self.error = error
    self.written_data = None

  def read_accounts_data(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    return self.data, self.error

  def write_accounts_data(self, data: Dict[str, Any]) -> None:
    self.written_data = data


class FakeGeminiFiles:

  def __init__(self):
    self.oauth_creds = None
    self.google_accounts = None

  def read_oauth_creds(self) -> Optional[Dict[str, Any]]:
    return self.oauth_creds

  def write_oauth_creds(self, creds: Dict[str, Any]) -> None:
    self.oauth_creds = creds

  def read_google_accounts(self) -> Optional[Dict[str, Any]]:
    return self.google_accounts

  def write_google_accounts(self, accounts: Dict[str, Any]) -> None:
    self.google_accounts = accounts


class FakeProcessManager:

  def __init__(self):
    self.sessions = []

  def detect_sessions(self):
    return list(self.sessions)

  def terminate_sessions(self, sessions, poll_timeout: float = 5.0) -> bool:
    return True


class FakeEnvironment:

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


# ─── Tests: Facade Initialization & Operations ──────────────────────────────


def test_facade_receives_ports_via_constructor():
  storage = FakeAccountStorage()
  keyring = FakeKeyring()
  gemini_files = FakeGeminiFiles()
  opencode_file = FakeOpenCodeFile()
  oauth = FakeOAuth()
  proc_mgr = FakeProcessManager()
  env = FakeEnvironment()
  clock = FakeClock()

  facade = AntigravityFacade(
      account_storage=storage,
      keyring=keyring,
      gemini_files=gemini_files,
      opencode_file=opencode_file,
      oauth=oauth,
      process_manager=proc_mgr,
      environment=env,
      clock=clock,
  )

  assert facade.account_storage is storage
  assert facade.keyring is keyring
  assert facade.gemini_files is gemini_files
  assert facade.opencode_file is opencode_file
  assert facade.oauth is oauth
  assert facade.process_manager is proc_mgr
  assert facade.environment is env
  assert facade.clock is clock


def test_facade_provides_four_operations():
  facade = AntigravityFacade(
      FakeAccountStorage(),
      FakeKeyring(),
      FakeGeminiFiles(),
      FakeOpenCodeFile(),
      FakeOAuth(),
      FakeProcessManager(),
      FakeEnvironment(),
      FakeClock(),
  )

  # 1. build plan
  plan = facade.build_plan("acc1", "opencode")
  assert isinstance(plan, ApplyPlan)
  assert plan.target == "opencode"

  # 2. apply
  apply_res = facade.apply(plan)
  assert apply_res.status in (ApplyStatus.SUCCESS, ApplyStatus.FAILED)

  # 3. read status
  status = facade.read_status()
  assert isinstance(status, OverallStatus)

  # 4. restore last backup
  restore_res = facade.restore_last_backup()
  assert restore_res.status == ApplyStatus.SUCCESS


def test_production_and_test_assembly(fake_root):
  db = AccountDatabase(use_turso=False)
  facade_prod = create_facade(db, lambda: str(fake_root.opencode_config_dir))
  assert facade_prod is not None

  status = facade_prod.read_status()
  assert status.opencode.condition == TargetCondition.INVALID_FILE


# ─── Tests: OpenCode read_status ─────────────────────────────────────────────


def test_read_status_opencode_active_index():
  file_data = {
      "activeIndex": 1,
      "accounts": [
          {"email": "first@example.com"},
          {"email": "second@example.com"},
      ],
  }
  facade = AntigravityFacade(
      FakeAccountStorage(existing_emails=["second@example.com"]),
      FakeKeyring(),
      FakeGeminiFiles(),
      FakeOpenCodeFile(data=file_data),
      FakeOAuth(),
      FakeProcessManager(),
      FakeEnvironment(),
      FakeClock(),
  )

  status = facade.read_status()
  assert status.opencode.condition == TargetCondition.ACTIVE
  assert status.opencode.email == "second@example.com"


def test_read_status_opencode_fallback_family_gemini():
  file_data = {
      "activeIndexByFamily": {"gemini": 0, "claude": 1},
      "accounts": [
          {"email": "gemini@example.com"},
          {"email": "claude@example.com"},
      ],
  }
  facade = AntigravityFacade(
      FakeAccountStorage(existing_emails=["gemini@example.com"]),
      FakeKeyring(),
      FakeGeminiFiles(),
      FakeOpenCodeFile(data=file_data),
      FakeOAuth(),
      FakeProcessManager(),
      FakeEnvironment(),
      FakeClock(),
  )

  status = facade.read_status()
  assert status.opencode.condition == TargetCondition.ACTIVE
  assert status.opencode.email == "gemini@example.com"


def test_read_status_opencode_unrecorded():
  file_data = {
      "activeIndex": 0,
      "accounts": [{"email": "wild@example.com"}],
  }
  facade = AntigravityFacade(
      FakeAccountStorage(existing_emails=["other@example.com"]),
      FakeKeyring(),
      FakeGeminiFiles(),
      FakeOpenCodeFile(data=file_data),
      FakeOAuth(),
      FakeProcessManager(),
      FakeEnvironment(),
      FakeClock(),
  )

  status = facade.read_status()
  assert status.opencode.condition == TargetCondition.UNRECORDED
  assert status.opencode.email == "wild@example.com"


def test_read_status_opencode_missing_or_corrupt_file():
  facade = AntigravityFacade(
      FakeAccountStorage(),
      FakeKeyring(),
      FakeGeminiFiles(),
      FakeOpenCodeFile(data=None, error="invalid_file"),
      FakeOAuth(),
      FakeProcessManager(),
      FakeEnvironment(),
      FakeClock(),
  )

  status = facade.read_status()
  assert status.opencode.condition == TargetCondition.INVALID_FILE
  assert status.opencode.email is None


def test_read_status_never_raises_exception():
  class CrashingPort:
    def read_accounts_data(self):
      raise RuntimeError("Simulated port explosion")

  facade = AntigravityFacade(
      FakeAccountStorage(),
      FakeKeyring(),
      FakeGeminiFiles(),
      CrashingPort(),
      FakeOAuth(),
      FakeProcessManager(),
      FakeEnvironment(),
      FakeClock(),
  )

  status = facade.read_status()
  assert status.opencode.condition == TargetCondition.ERROR
  assert "Simulated port explosion" in (status.opencode.error or "")


# ─── Tests: compute_active_di & AccountTableWidget ───────────────────────────


def test_compute_active_di_logic():
  status_both = OverallStatus(
      opencode=TargetStatus(
          target=TARGET_OPENCODE,
          email="User@Example.com",
          condition=TargetCondition.ACTIVE,
      ),
      antigravity_cli=TargetStatus(
          target=TARGET_ANTIGRAVITY_CLI,
          email="user@example.com",
          condition=TargetCondition.ACTIVE,
      ),
  )
  assert compute_active_di("user@example.com", status_both) == "OpenCode + CLI"

  status_only_opencode = OverallStatus(
      opencode=TargetStatus(
          target=TARGET_OPENCODE,
          email="User@Example.com",
          condition=TargetCondition.ACTIVE,
      ),
      antigravity_cli=TargetStatus(
          target=TARGET_ANTIGRAVITY_CLI,
          email="other@example.com",
          condition=TargetCondition.ACTIVE,
      ),
  )
  assert compute_active_di("USER@example.COM", status_only_opencode) == "OpenCode"
  assert compute_active_di("neither@example.com", status_only_opencode) == "—"


def test_account_table_has_seven_columns_and_proper_headers(qtbot):
  table_widget = AccountTableWidget()
  qtbot.addWidget(table_widget)

  assert table_widget.table.columnCount() == 7
  headers = [
      table_widget.table.horizontalHeaderItem(i).text()
      for i in range(7)
  ]
  assert headers == [
      "Email",
      "Kategori",
      "Aktif di",
      "Status Enkripsi",
      "Flash Quota (Reset)",
      "Pro Quota (Reset)",
      "Claude Quota (Reset)",
  ]

  # Kolom 'Aktif di' ResizeToContents dan max width ~110
  header = table_widget.table.horizontalHeader()
  assert header.sectionResizeMode(2) == QHeaderView.ResizeMode.ResizeToContents
  assert header.maximumSectionSize() == 110


def test_account_table_separator_spans_seven_columns(qtbot):
  table_widget = AccountTableWidget()
  qtbot.addWidget(table_widget)

  raw_rows = [
      ("acc1", "user1@example.com", None, None, None, None, None, None, 0, None, "Work"),
      ("acc2", "user2@example.com", None, None, None, None, None, None, 0, None, "Personal"),
  ]
  table_widget.set_accounts_data(raw_rows)

  # Dalam mode __ALL__, baris pertama adalah pemisah kategori
  assert table_widget.table.rowCount() == 4  # 2 pemisah + 2 data akun
  assert table_widget.table.rowSpan(0, 0) == 1
  assert table_widget.table.columnSpan(0, 0) == 7


def test_account_table_populates_active_di_column(qtbot):
  table_widget = AccountTableWidget()
  qtbot.addWidget(table_widget)

  overall_status = OverallStatus(
      opencode=TargetStatus(
          target=TARGET_OPENCODE,
          email="active@example.com",
          condition=TargetCondition.ACTIVE,
      ),
      antigravity_cli=TargetStatus(
          target=TARGET_ANTIGRAVITY_CLI,
          email=None,
          condition=TargetCondition.NONE,
      ),
  )

  raw_rows = [
      ("acc1", "active@example.com", None, None, None, None, None, None, 0, None, ""),
      ("acc2", "inactive@example.com", None, None, None, None, None, None, 0, None, ""),
  ]
  table_widget.set_accounts_data(raw_rows, overall_status=overall_status)

  # Filter __ALL__, row 0 adalah pemisah Tanpa Kategori, row 1 dan 2 adalah akun
  item_active_di_1 = table_widget.table.item(1, 2)
  item_active_di_2 = table_widget.table.item(2, 2)

  assert item_active_di_1.text() == "OpenCode"
  assert item_active_di_2.text() == "—"


# ─── Tests: TargetBadge Chip Status Display ──────────────────────────────────


def test_target_badge_chip_displays_condition_and_email(qtbot, tmp_path):
  from PyQt6.QtCore import QSettings
  settings = QSettings(str(tmp_path / "badge.ini"), QSettings.Format.IniFormat)
  config_bar = ConfigBarWidget(settings=settings)
  qtbot.addWidget(config_bar)

  target_status = TargetStatus(
      target=TARGET_OPENCODE,
      email="tester@example.com",
      condition=TargetCondition.ACTIVE,
      message="Aktif: tester@example.com",
  )

  config_bar.set_target_status(target_status)
  badge = config_bar.target_badge

  assert "🟢 tester@example.com" in badge.text()
  assert "tester@example.com" in badge.toolTip()
  assert "Kondisi: active" in badge.toolTip()
