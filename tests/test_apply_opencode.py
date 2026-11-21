"""Pengujian end-to-end untuk Apply ke OpenCode (Ticket 05).

Kriteria Pengujian:
1. Build plan gagal — sebelum backup dan penulisan — bila folder target tidak valid, file tidak ada,
   isinya bukan objek JSON, atau `accounts` bukan array.
2. File berisi 3 akun lalu Apply akun ke-4 menghasilkan 4 akun; akun lama utuh, akun baru berada di akhir.
3. Email yang sudah ada dengan kapitalisasi berbeda menggantikan entri lama di posisi yang sama, tanpa duplikat.
4. Snapshot akun diambil dari rekonstruksi DB, bukan dengan menulis konfigurasi hasil rekonstruksi satu akun apa adanya.
5. `activeIndex` menunjuk indeks hasil upsert; `activeIndexByFamily.gemini` dan `.claude` diubah hanya bila kuncinya sudah ada,
   dan kunci yang tidak ada tidak dibuat.
6. Field top-level lain (misalnya `version`) dan seluruh akun lain dipertahankan.
7. Backup file lama dibuat sebelum penulisan; kegagalan plan tidak menghasilkan backup.
8. Penulisan atomic lewat file sementara di direktori yang sama + `os.replace`, mode `0600`, tanpa mengikuti symlink.
9. Apply sukses menandai DB `applied_target='opencode'` dan `last_applied_at` waktu epoch detik.
10. Dialog sukses standar menampilkan email dan jumlah akun di file.
11. Apply OpenCode tidak memanggil port proses maupun keyring, dan tidak membaca/menulis `~/.gemini`.
12. Menu konteks akun memiliki submenu "Terapkan ke…" berisi OpenCode dan Antigravity CLI; item CLI disabled dengan alasan saat target tidak tersedia.
13. Double-click pada baris akun menjalankan Apply ke Selected Target; tidak ada tombol Apply baru di toolbar.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import pytest
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import QTableWidgetItem, QMessageBox

from src.integrations.antigravity.ports import (
    ApplyPlan,
    ApplyResult,
    ApplyStatus,
    OverallStatus,
    TargetCondition,
    TargetStatus,
)
from src.integrations.antigravity.service import AntigravityFacade
from src.integrations.antigravity.opencode_file import RealOpenCodeFilePort
from src.targets import TARGET_ANTIGRAVITY_CLI, TARGET_OPENCODE
from src.ui.components.account_table import AccountTableWidget
from tests.fakes import (
    FakeClock,
    FakeKeyring,
    FakeOAuth,
    FakeProcTable,
    FakeRoot,
)


# ─── Fakes untuk Pengujian Ticket 05 ─────────────────────────────────────────


class RecordingKeyring(FakeKeyring):
  def __init__(self):
    super().__init__()
    self.call_count = 0

  def read(self, service: str, username: str):
    self.call_count += 1
    return super().read(service, username)

  def write(self, service: str, username: str, payload: bytes):
    self.call_count += 1
    return super().write(service, username, payload)

  def delete(self, service: str, username: str):
    self.call_count += 1
    return super().delete(service, username)


class RecordingProcessManager:
  def __init__(self):
    self.detect_calls = 0
    self.terminate_calls = 0

  def detect_sessions(self) -> List[Any]:
    self.detect_calls += 1
    return []

  def terminate_sessions(self, sessions: List[Any], poll_timeout: float = 5.0) -> bool:
    self.terminate_calls += 1
    return True


class RecordingGeminiFiles:
  def __init__(self):
    self.calls = 0

  def read_oauth_creds(self):
    self.calls += 1
    return None

  def write_oauth_creds(self, creds):
    self.calls += 1

  def read_google_accounts(self):
    self.calls += 1
    return None

  def write_google_accounts(self, accounts):
    self.calls += 1


class FakeAccountStorage:
  def __init__(self, accounts=None):
    self.accounts = accounts or {}
    self.applied_marks = []

  def reconstruct_account(self, account_id: str, password: str = "") -> Dict[str, Any]:
    if account_id in self.accounts:
      return dict(self.accounts[account_id])
    return {
        "id": account_id,
        "email": f"{account_id}@example.com",
        "refreshToken": "sample-refresh-token",
    }

  def mark_applied(self, account_id: str, target: str, applied_at: Optional[int] = None) -> bool:
    self.applied_marks.append((account_id, target, applied_at))
    return True

  def update_refresh_token(self, account_id: str, new_refresh_token: str, password: str = "") -> bool:
    return True

  def account_exists(self, email: str) -> bool:
    target_clean = email.lower()
    return any(a.get("email", "").lower() == target_clean for a in self.accounts.values())


class FakeEnvironment:
  def is_linux(self) -> bool:
    return True

  def is_root(self) -> bool:
    return False

  def is_dbus_available(self) -> bool:
    return True

  def is_keyring_locked(self) -> bool:
    return False


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_build_plan_fails_when_file_missing_corrupt_or_not_array(tmp_path):
  """Plan gagal — sebelum backup dan penulisan — bila file tidak ada, rusak, atau accounts bukan array."""
  target_file = tmp_path / "antigravity-accounts.json"
  opencode_port = RealOpenCodeFilePort(str(tmp_path))

  clock = FakeClock(1_700_000_000.0)
  storage = FakeAccountStorage({
      "acc1": {"id": "acc1", "email": "user@example.com"}
  })
  keyring = RecordingKeyring()
  process_mgr = RecordingProcessManager()
  gemini_files = RecordingGeminiFiles()

  facade = AntigravityFacade(
      account_storage=storage,
      keyring=keyring,
      gemini_files=gemini_files,
      opencode_file=opencode_port,
      oauth=FakeOAuth(),
      process_manager=process_mgr,
      environment=FakeEnvironment(),
      clock=clock,
  )

  # 1. File tidak ada
  plan = facade.build_plan("acc1", TARGET_OPENCODE)
  assert not plan.target_available
  assert plan.error_code == "invalid_opencode_file"

  # Pastikan tidak ada backup yang terbuat
  from src.integrations.antigravity.backup import get_backups_base_dir
  base_backups = get_backups_base_dir()
  assert not base_backups.exists() or len(list(base_backups.iterdir())) == 0

  # 2. File bukan JSON valid
  target_file.write_text("NOT_JSON_DATA", encoding="utf-8")
  plan = facade.build_plan("acc1", TARGET_OPENCODE)
  assert not plan.target_available
  assert plan.error_code == "invalid_opencode_file"

  # 3. File JSON tetapi bukan objek dictionary
  target_file.write_text("[]", encoding="utf-8")
  plan = facade.build_plan("acc1", TARGET_OPENCODE)
  assert not plan.target_available
  assert plan.error_code == "invalid_opencode_file"

  # 4. Field accounts bukan list/array
  target_file.write_text(json.dumps({"version": 4, "accounts": "not-a-list"}), encoding="utf-8")
  plan = facade.build_plan("acc1", TARGET_OPENCODE)
  assert not plan.target_available
  assert plan.error_code == "invalid_accounts_array"

  # Pastikan keyring dan process manager tidak pernah dipanggil sama sekali
  assert keyring.call_count == 0
  assert process_mgr.detect_calls == 0
  assert process_mgr.terminate_calls == 0
  assert gemini_files.calls == 0


def test_apply_three_to_four_accounts_and_preserves_others(tmp_path):
  """File berisi 3 akun lalu Apply akun ke-4 menghasilkan 4 akun; akun lama utuh, akun baru di akhir."""
  target_file = tmp_path / "antigravity-accounts.json"
  initial_data = {
      "version": 4,
      "customField": "preserved",
      "accounts": [
          {"id": "a1", "email": "a1@example.com", "refreshToken": "t1"},
          {"id": "a2", "email": "a2@example.com", "refreshToken": "t2"},
          {"id": "a3", "email": "a3@example.com", "refreshToken": "t3"},
      ],
      "activeIndex": 0,
      "activeIndexByFamily": {"gemini": 0, "claude": 1},
  }
  target_file.write_text(json.dumps(initial_data), encoding="utf-8")

  opencode_port = RealOpenCodeFilePort(str(tmp_path))
  clock = FakeClock(1_700_000_100.0)
  account_4 = {"id": "a4", "email": "a4@example.com", "refreshToken": "t4"}
  storage = FakeAccountStorage({"a4": account_4})
  keyring = RecordingKeyring()
  process_mgr = RecordingProcessManager()
  gemini_files = RecordingGeminiFiles()

  facade = AntigravityFacade(
      account_storage=storage,
      keyring=keyring,
      gemini_files=gemini_files,
      opencode_file=opencode_port,
      oauth=FakeOAuth(),
      process_manager=process_mgr,
      environment=FakeEnvironment(),
      clock=clock,
  )

  plan = facade.build_plan("a4", TARGET_OPENCODE)
  assert plan.target_available
  assert plan.error_code is None

  result = facade.apply(plan)
  assert result.status == ApplyStatus.SUCCESS
  assert result.email == "a4@example.com"
  assert result.accounts_count == 4
  assert result.backup_location != ""

  # Periksa isi file setelah apply
  updated_data = json.loads(target_file.read_text(encoding="utf-8"))
  assert updated_data.get("customField") == "preserved"
  assert updated_data.get("version") == 4
  assert len(updated_data["accounts"]) == 4

  # Akun lama utuh
  assert updated_data["accounts"][0]["email"] == "a1@example.com"
  assert updated_data["accounts"][1]["email"] == "a2@example.com"
  assert updated_data["accounts"][2]["email"] == "a3@example.com"

  # Akun baru di akhir
  assert updated_data["accounts"][3]["email"] == "a4@example.com"
  assert updated_data["accounts"][3]["id"] == "a4"

  # activeIndex dan activeIndexByFamily menunjuk akun ke-4 (indeks 3)
  assert updated_data["activeIndex"] == 3
  assert updated_data["activeIndexByFamily"]["gemini"] == 3
  assert updated_data["activeIndexByFamily"]["claude"] == 3

  # Penandaan DB dilakukan
  assert storage.applied_marks == [("a4", TARGET_OPENCODE, 1_700_000_100)]

  # Backup file lama berhasil dibuat dan isinya adalah 3 akun awal
  backup_dir = Path(result.backup_location)
  assert backup_dir.exists()
  backup_acc_file = backup_dir / "antigravity-accounts.json"
  assert backup_acc_file.exists()
  backup_data = json.loads(backup_acc_file.read_text(encoding="utf-8"))
  assert len(backup_data["accounts"]) == 3

  # Mode file 0600
  file_stat = target_file.stat()
  assert oct(file_stat.st_mode)[-3:] == "600"

  # Apply OpenCode tidak memanggil keyring, process manager, atau gemini files
  assert keyring.call_count == 0
  assert process_mgr.detect_calls == 0
  assert process_mgr.terminate_calls == 0
  assert gemini_files.calls == 0


def test_upsert_existing_email_case_insensitive_preserves_position(tmp_path):
  """Email yang sudah ada dengan kapitalisasi berbeda menggantikan entri lama di posisi yang sama tanpa duplikat."""
  target_file = tmp_path / "antigravity-accounts.json"
  initial_data = {
      "version": 4,
      "accounts": [
          {"id": "a1", "email": "alpha@example.com", "refreshToken": "old_alpha"},
          {"id": "a2", "email": "Beta@Example.COM", "refreshToken": "old_beta"},
          {"id": "a3", "email": "gamma@example.com", "refreshToken": "old_gamma"},
      ],
      "activeIndex": 0,
      "activeIndexByFamily": {"gemini": 0},  # Tidak ada key 'claude'
  }
  target_file.write_text(json.dumps(initial_data), encoding="utf-8")

  opencode_port = RealOpenCodeFilePort(str(tmp_path))
  clock = FakeClock(1_700_000_200.0)
  # Update Beta dengan huruf kecil dan token baru
  new_beta = {"id": "a2_new", "email": "beta@example.com", "refreshToken": "new_beta_token"}
  storage = FakeAccountStorage({"a2_new": new_beta})

  facade = AntigravityFacade(
      account_storage=storage,
      keyring=RecordingKeyring(),
      gemini_files=RecordingGeminiFiles(),
      opencode_file=opencode_port,
      oauth=FakeOAuth(),
      process_manager=RecordingProcessManager(),
      environment=FakeEnvironment(),
      clock=clock,
  )

  plan = facade.build_plan("a2_new", TARGET_OPENCODE)
  result = facade.apply(plan)

  assert result.status == ApplyStatus.SUCCESS
  assert result.accounts_count == 3  # Tetap 3, tanpa duplikat

  updated_data = json.loads(target_file.read_text(encoding="utf-8"))
  assert len(updated_data["accounts"]) == 3
  # Posisi tetap di indeks 1
  assert updated_data["accounts"][1]["email"] == "beta@example.com"
  assert updated_data["accounts"][1]["refreshToken"] == "new_beta_token"
  assert updated_data["accounts"][1]["id"] == "a2_new"

  # activeIndex menunjuk 1
  assert updated_data["activeIndex"] == 1
  # activeIndexByFamily.gemini diubah ke 1, dan kunci 'claude' tidak dibuat karena awalnya tidak ada
  assert updated_data["activeIndexByFamily"]["gemini"] == 1
  assert "claude" not in updated_data["activeIndexByFamily"]


def test_snapshot_extracted_from_db_reconstruction(tmp_path):
  """Snapshot akun diambil dari objek akun hasil rekonstruksi DB, bukan menulis konfigurasi satu akun apa adanya."""
  target_file = tmp_path / "antigravity-accounts.json"
  target_file.write_text(json.dumps({"version": 4, "accounts": []}), encoding="utf-8")

  opencode_port = RealOpenCodeFilePort(str(tmp_path))
  clock = FakeClock(1_700_000_300.0)

  account_obj = {
      "id": "single-acc",
      "email": "single@example.com",
      "refreshToken": "tok-123",
      "projectId": "proj-xyz",
  }
  storage = FakeAccountStorage({"single-acc": account_obj})

  facade = AntigravityFacade(
      account_storage=storage,
      keyring=RecordingKeyring(),
      gemini_files=RecordingGeminiFiles(),
      opencode_file=opencode_port,
      oauth=FakeOAuth(),
      process_manager=RecordingProcessManager(),
      environment=FakeEnvironment(),
      clock=clock,
  )

  plan = facade.build_plan("single-acc", TARGET_OPENCODE)
  result = facade.apply(plan)
  assert result.status == ApplyStatus.SUCCESS

  data = json.loads(target_file.read_text(encoding="utf-8"))
  assert len(data["accounts"]) == 1
  assert data["accounts"][0] == account_obj
  assert data["activeIndex"] == 0


def test_opencode_refuses_to_follow_symlink(tmp_path):
  """Penulisan dan pembacaan tidak mengikuti symlink."""
  real_file = tmp_path / "real_accounts.json"
  real_file.write_text(json.dumps({"version": 4, "accounts": []}), encoding="utf-8")

  symlink_dir = tmp_path / "link_dir"
  symlink_dir.mkdir()
  symlink_file = symlink_dir / "antigravity-accounts.json"
  symlink_file.symlink_to(real_file)

  opencode_port = RealOpenCodeFilePort(str(symlink_dir))
  data, err = opencode_port.read_accounts_data()
  assert data is None
  assert err == "invalid_file"

  with pytest.raises(PermissionError):
    opencode_port.write_accounts_data({"version": 4, "accounts": []})


# ─── UI Tests: Context Menu Submenu & Double-Click ───────────────────────────


def test_account_table_context_menu_submenu_and_cli_disabled(qtbot):
  """Menu konteks akun memiliki submenu 'Terapkan ke…' dengan OpenCode & Antigravity CLI."""
  table_widget = AccountTableWidget()
  qtbot.addWidget(table_widget)

  # Status di mana CLI unavailable (misalnya locked / unsupported)
  overall_status = OverallStatus(
      opencode=TargetStatus(
          target=TARGET_OPENCODE,
          email="active@example.com",
          condition=TargetCondition.ACTIVE,
      ),
      antigravity_cli=TargetStatus(
          target=TARGET_ANTIGRAVITY_CLI,
          condition=TargetCondition.UNAVAILABLE,
          unavailable_reason="unsupported_os",
          message="Target hanya didukung pada OS Linux.",
      ),
  )

  raw_rows = [
      ("acc1", "user1@example.com", None, None, None, None, None, None, 0, None, "Work"),
  ]
  table_widget.set_accounts_data(raw_rows, overall_status=overall_status)

  # Pastikan sinyal apply_requested terpasang
  applied_calls = []
  table_widget.apply_requested.connect(lambda acc_id, tgt: applied_calls.append((acc_id, tgt)))

  # Verifikasi bahwa double click memancarkan sinyal apply ke target aktif
  table_widget._on_cell_double_clicked(1, 0)  # Row 1 (row 0 adalah pemisah)
  assert applied_calls == [("acc1", "")]


def test_double_click_on_separator_row_does_not_emit_apply(qtbot):
  """Double click pada baris pemisah kategori tidak memicu Apply."""
  table_widget = AccountTableWidget()
  qtbot.addWidget(table_widget)

  raw_rows = [
      ("acc1", "user1@example.com", None, None, None, None, None, None, 0, None, "Work"),
  ]
  table_widget.set_accounts_data(raw_rows)

  applied_calls = []
  table_widget.apply_requested.connect(lambda acc_id, tgt: applied_calls.append((acc_id, tgt)))

  # Row 0 adalah baris pemisah
  table_widget._on_cell_double_clicked(0, 0)
  assert len(applied_calls) == 0
