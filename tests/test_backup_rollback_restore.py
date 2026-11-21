"""Pengujian komprehensif untuk tiket 08: Backup, rollback, dan restore.

Kriteria penerimaan tiket 08 & SPEC §11:
1. Direktori backup ~/.local/state/auth-login-management/backups/<timestamp>/ bermode 0700 dan file di dalamnya 0600.
2. Setiap backup berisi salinan item keyring dan file target yang ada pada saat itu.
3. meta.json mencatat target, email, waktu, versi aplikasi, PID yang dihentikan, dan daftar artefak beserta status "ada"/"tidak ada".
4. Restore mengembalikan isi artefak yang ada, dan menghapus artefak yang sebelumnya tidak ada — baik item keyring maupun file.
5. Restore tidak mengubah kolom audit DB; indikator tetap membaca kenyataan.
6. Retensi menyisakan 30 backup terbaru dan dilakukan setelah Apply sukses, sehingga backup yang baru dibuat tidak ikut terhapus.
7. Rollback otomatis mengembalikan keyring dan file dari snapshot lalu melaporkan kegagalan asli; penandaan DB tidak pernah terjadi lebih dulu.
8. Bila kegagalan terjadi setelah snapshot dibuat, snapshot dipertahankan dan lokasinya disebutkan di dialog kegagalan.
9. Menu Pengaturan memiliki aksi "Pulihkan Backup Terakhir…" dengan konfirmasi yang menyebut waktu, target, dan email dari manifest, serta menyatakan bahwa backup berisi kredensial.
10. Tidak ada backup, keyring, atau file lain yang dibaca/ditulis ketika tidak ada backup.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from src.database import AccountDatabase
from src.integrations.antigravity.backup import (
    cleanup_old_backups,
    create_cli_backup,
    create_opencode_backup,
    get_backups_base_dir,
    get_latest_backup,
    list_backups,
    rollback_from_backup,
)
from src.integrations.antigravity.constants import (
    KEYRING_SERVICE,
    KEYRING_USERNAME,
    TARGET_ANTIGRAVITY_CLI,
    TARGET_OPENCODE,
)
from src.integrations.antigravity.ports import (
    ApplyPlan,
    ApplyStatus,
    OverallStatus,
    RestoreResult,
    TargetCondition,
    TargetStatus,
)
from src.integrations.antigravity.service import AntigravityFacade
from tests.fakes import FakeClock, FakeKeyring, FakeOAuth, FakeProcTable, FakeRoot


# ─── Fake Ports Tambahan ───────────────────────────────────────────────────────


class FakeAccountStorage:

  def __init__(self, accounts: Optional[Dict[str, Dict[str, Any]]] = None):
    self.accounts = accounts or {}
    self.applied_marks: list[tuple[str, str, int]] = []
    self.fail_on_mark: Optional[Exception] = None

  def reconstruct_account(self, account_id: str, password: str = "") -> Dict[str, Any]:
    if account_id not in self.accounts:
      raise ValueError(f"Akun {account_id} tidak ditemukan")
    return dict(self.accounts[account_id])

  def mark_applied(self, account_id: str, target: str, applied_at: Optional[int] = None) -> bool:
    if self.fail_on_mark is not None:
      raise self.fail_on_mark
    self.applied_marks.append((account_id, target, applied_at or 0))
    return True

  def update_refresh_token(self, account_id: str, new_refresh_token: str, password: str = "") -> bool:
    return True

  def account_exists(self, email: str) -> bool:
    return any(a.get("email") == email for a in self.accounts.values())


class FakeOpenCodeFilePort:

  def __init__(self, file_path: Path):
    self.file_path = file_path
    self.fail_on_write: Optional[Exception] = None

  def get_file_path(self) -> Path:
    return self.file_path

  def read_accounts_data(self):
    if not self.file_path.exists():
      return None, "invalid_file"
    try:
      return json.loads(self.file_path.read_text(encoding="utf-8")), None
    except Exception:
      return None, "invalid_file"

  def write_accounts_data(self, data: Dict[str, Any]):
    if self.fail_on_write:
      raise self.fail_on_write
    self.file_path.parent.mkdir(parents=True, exist_ok=True)
    self.file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class FakeGeminiFilesPort:

  def __init__(self, gemini_dir: Path):
    self.gemini_dir = gemini_dir

  def read_oauth_creds(self):
    f = self.gemini_dir / "oauth_creds.json"
    if f.exists():
      return json.loads(f.read_text(encoding="utf-8"))
    return None

  def write_oauth_creds(self, creds):
    self.gemini_dir.mkdir(parents=True, exist_ok=True)
    (self.gemini_dir / "oauth_creds.json").write_text(json.dumps(creds), encoding="utf-8")

  def read_google_accounts(self):
    f = self.gemini_dir / "google_accounts.json"
    if f.exists():
      return json.loads(f.read_text(encoding="utf-8"))
    return None

  def write_google_accounts(self, accounts):
    self.gemini_dir.mkdir(parents=True, exist_ok=True)
    (self.gemini_dir / "google_accounts.json").write_text(json.dumps(accounts), encoding="utf-8")


class DummyProcessManager:

  def detect_sessions(self):
    return []

  def terminate_sessions(self, sessions, poll_timeout: float = 5.0):
    return True, [], ""


class DummyEnvironment:

  def is_linux(self):
    return True

  def is_root(self):
    return False

  def is_dbus_available(self):
    return True

  def is_keyring_locked(self):
    return False


# ─── Tests Unit: Pembuatan Snapshot & Permissions ──────────────────────────────


def test_backup_directory_and_file_permissions(fake_root):
  """Kriteria: Direktori 0700 dan file di dalamnya 0600."""
  opencode_file = fake_root.opencode_accounts_file
  opencode_file.parent.mkdir(parents=True, exist_ok=True)
  opencode_file.write_text(json.dumps({"version": 4, "accounts": []}), encoding="utf-8")

  clock_now = 1700000100.0
  backup_dir = create_opencode_backup(opencode_file, "user@example.com", clock_now)

  assert backup_dir.exists()
  # Periksa mode permission direktori: 0700 (rwx------)
  dir_stat = backup_dir.stat()
  assert stat.S_IMODE(dir_stat.st_mode) == 0o700

  # Periksa permission file di dalam backup: 0600 (rw-------)
  meta_file = backup_dir / "meta.json"
  accounts_backup = backup_dir / "antigravity-accounts.json"
  assert meta_file.exists()
  assert accounts_backup.exists()
  assert stat.S_IMODE(meta_file.stat().st_mode) == 0o600
  assert stat.S_IMODE(accounts_backup.stat().st_mode) == 0o600


def test_meta_json_contents_opencode(fake_root):
  """Kriteria: meta.json mencatat target, email, waktu, versi aplikasi, PID, dan artefak ada/tidak ada."""
  opencode_file = fake_root.opencode_accounts_file
  opencode_file.parent.mkdir(parents=True, exist_ok=True)
  opencode_file.write_text(json.dumps({"accounts": []}), encoding="utf-8")

  clock_now = 1700000200.0
  backup_dir = create_opencode_backup(opencode_file, "alpha@test.com", clock_now, version="1.0.0")

  meta = json.loads((backup_dir / "meta.json").read_text(encoding="utf-8"))
  assert meta["target"] == "opencode"
  assert meta["email"] == "alpha@test.com"
  assert meta["timestamp"] == int(clock_now)
  assert meta["app_version"] == "1.0.0"
  assert meta["stopped_pids"] == []
  assert meta["artifacts"] == {"antigravity-accounts.json": "present"}


def test_meta_json_contents_cli_with_absent_and_present(fake_root):
  """Snapshot CLI mencatat artefak keyring dan file yang ada maupun tidak ada."""
  gemini_dir = fake_root.gemini_dir
  gemini_dir.mkdir(parents=True, exist_ok=True)
  oauth_file = gemini_dir / "oauth_creds.json"
  oauth_file.write_text(json.dumps({"access_token": "ya29.test"}), encoding="utf-8")
  # google_accounts.json sengaja tidak dibuat (absent)

  clock_now = 1700000300.0
  payload = b"keyring-secret-payload"
  stopped_pids = [1024, 2048]

  backup_dir = create_cli_backup(
      keyring_payload=payload,
      gemini_dir=gemini_dir,
      email="cli_user@test.com",
      clock_now=clock_now,
      stopped_pids=stopped_pids,
      version="1.0.0",
  )

  meta = json.loads((backup_dir / "meta.json").read_text(encoding="utf-8"))
  assert meta["target"] == "antigravity_cli"
  assert meta["email"] == "cli_user@test.com"
  assert meta["timestamp"] == int(clock_now)
  assert meta["stopped_pids"] == [1024, 2048]
  assert meta["artifacts"]["keyring_item"] == "present"
  assert meta["artifacts"]["oauth_creds.json"] == "present"
  assert meta["artifacts"]["google_accounts.json"] == "absent"

  assert (backup_dir / "keyring_item.bin").read_bytes() == payload
  assert (backup_dir / "oauth_creds.json").exists()
  assert not (backup_dir / "google_accounts.json").exists()


# ─── Tests Unit: Restore Artefak & Hapus yang Sebelumnya Tidak Ada ─────────────


def test_restore_opencode_artifact_when_was_absent(fake_root):
  """Jika saat backup file belum ada (absent), restore harus menghapus file yang ada."""
  opencode_file = fake_root.opencode_accounts_file
  if opencode_file.exists():
    opencode_file.unlink()

  # Buat backup saat file belum ada
  backup_dir = create_opencode_backup(opencode_file, "absent@test.com", 1700000400.0)
  meta = json.loads((backup_dir / "meta.json").read_text(encoding="utf-8"))
  assert meta["artifacts"]["antigravity-accounts.json"] == "absent"

  # Sekarang simulasikan file dibuat
  opencode_file.parent.mkdir(parents=True, exist_ok=True)
  opencode_file.write_text("dummy new file", encoding="utf-8")
  assert opencode_file.exists()

  # Rollback
  keyring = FakeKeyring()
  rollback_from_backup(backup_dir, keyring, None, opencode_file)

  # File harus terhapus karena sebelumnya tidak ada
  assert not opencode_file.exists()


def test_restore_cli_artifacts_restores_present_and_deletes_absent(fake_root):
  """Restore CLI: mengembalikan item yang ada dan menghapus artefak yang tadinya absent."""
  gemini_dir = fake_root.gemini_dir
  keyring = FakeKeyring()

  # Kondisi awal: keyring ada, oauth_creds ada, google_accounts tidak ada
  keyring.write(KEYRING_SERVICE, KEYRING_USERNAME, b"old-token")
  gemini_dir.mkdir(parents=True, exist_ok=True)
  (gemini_dir / "oauth_creds.json").write_text(json.dumps({"token": "old_oauth"}), encoding="utf-8")

  backup_dir = create_cli_backup(
      keyring_payload=keyring.read(KEYRING_SERVICE, KEYRING_USERNAME),
      gemini_dir=gemini_dir,
      email="test@domain.com",
      clock_now=1700000500.0,
  )

  # Sekarang terjadi perubahan (apply baru): keyring berubah, oauth_creds berubah, google_accounts baru dibuat
  keyring.write(KEYRING_SERVICE, KEYRING_USERNAME, b"new-token")
  (gemini_dir / "oauth_creds.json").write_text(json.dumps({"token": "new_oauth"}), encoding="utf-8")
  (gemini_dir / "google_accounts.json").write_text(json.dumps({"active": "new"}), encoding="utf-8")

  # Lakukan rollback
  rollback_from_backup(backup_dir, keyring, gemini_dir, None)

  # 1. Keyring kembali ke old-token
  assert keyring.read(KEYRING_SERVICE, KEYRING_USERNAME) == b"old-token"
  # 2. oauth_creds.json kembali ke old_oauth
  oauth_restored = json.loads((gemini_dir / "oauth_creds.json").read_text(encoding="utf-8"))
  assert oauth_restored["token"] == "old_oauth"
  # 3. google_accounts.json dihapus karena saat backup statusnya 'absent'
  assert not (gemini_dir / "google_accounts.json").exists()


def test_restore_deletes_keyring_if_previously_absent(fake_root):
  """Jika saat backup keyring kosong (absent), restore harus menghapus item keyring."""
  keyring = FakeKeyring()
  # Pastikan kosong
  assert keyring.read(KEYRING_SERVICE, KEYRING_USERNAME) is None

  backup_dir = create_cli_backup(
      keyring_payload=None,
      gemini_dir=fake_root.gemini_dir,
      email="new@test.com",
      clock_now=1700000550.0,
  )

  # Simulasikan item ditulis
  keyring.write(KEYRING_SERVICE, KEYRING_USERNAME, b"some-credentials")
  assert keyring.read(KEYRING_SERVICE, KEYRING_USERNAME) == b"some-credentials"

  # Rollback
  rollback_from_backup(backup_dir, keyring, fake_root.gemini_dir, None)
  assert keyring.read(KEYRING_SERVICE, KEYRING_USERNAME) is None


# ─── Tests Unit: Retensi 30 Backup ─────────────────────────────────────────────


def test_retention_keeps_30_latest_and_does_not_delete_newest(fake_root):
  """Retensi menyisakan 30 backup terbaru dan tidak menghapus backup yang baru saja dibuat."""
  base_dir = get_backups_base_dir()
  base_dir.mkdir(parents=True, exist_ok=True)

  # Buat 35 direktori backup tiruan dengan timestamp berurutan
  for i in range(1, 36):
    ts = 1700000000 + i * 10
    d = base_dir / str(ts)
    d.mkdir(parents=True, exist_ok=True)
    meta = {"timestamp": ts, "email": f"user{i}@test.com", "target": "opencode", "artifacts": {}}
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    # Set mtime sesuai ts
    os.utime(d, (ts, ts))

  assert len(list(base_dir.iterdir())) == 35

  # Jalankan cleanup retensi 30
  cleanup_old_backups(max_keep=30)

  remaining = sorted([int(p.name) for p in base_dir.iterdir() if p.is_dir()])
  assert len(remaining) == 30

  # Backup paling baru (35) harus tetap ada
  latest_ts = 1700000000 + 35 * 10
  assert latest_ts in remaining

  # Backup tertua (1, 2, 3, 4, 5) harus sudah dihapus
  for i in range(1, 6):
    old_ts = 1700000000 + i * 10
    assert old_ts not in remaining


# ─── Tests Service: Rollback Otomatis Saat Penulisan/DB Gagal ───────────────────


def test_automatic_rollback_on_write_failure(fake_root):
  """Rollback otomatis mengembalikan file dari snapshot bila write_accounts_data gagal."""
  opencode_file = fake_root.opencode_accounts_file
  opencode_file.parent.mkdir(parents=True, exist_ok=True)
  initial_content = {"version": 4, "accounts": [{"email": "orig@test.com", "id": "orig"}]}
  opencode_file.write_text(json.dumps(initial_content), encoding="utf-8")

  opencode_port = FakeOpenCodeFilePort(opencode_file)
  storage = FakeAccountStorage({"acc1": {"email": "acc1@test.com", "id": "acc1", "refresh_token": "token1"}})

  clock = FakeClock(1700001000.0)
  facade = AntigravityFacade(
      account_storage=storage,
      keyring=FakeKeyring(),
      gemini_files=FakeGeminiFilesPort(fake_root.gemini_dir),
      opencode_file=opencode_port,
      oauth=FakeOAuth(),
      process_manager=DummyProcessManager(),
      environment=DummyEnvironment(),
      clock=clock,
  )

  # Simulasikan kegagalan saat penulisan file
  opencode_port.fail_on_write = OSError("Disk write error")

  plan = facade.build_plan("acc1", TARGET_OPENCODE)
  res = facade.apply(plan)

  assert res.status == ApplyStatus.FAILED
  assert res.code == "write_failed"
  assert res.backup_location is not None

  # File harus tetap dalam kondisi semula (atau di-rollback ke snapshot awal)
  restored_data = json.loads(opencode_file.read_text(encoding="utf-8"))
  assert restored_data == initial_content
  # DB tidak pernah ditandai
  assert len(storage.applied_marks) == 0


def test_automatic_rollback_on_db_mark_failure(fake_root):
  """Rollback otomatis bila penandaan database gagal setelah penulisan file berhasil."""
  opencode_file = fake_root.opencode_accounts_file
  opencode_file.parent.mkdir(parents=True, exist_ok=True)
  initial_content = {"version": 4, "accounts": [{"email": "orig@test.com", "id": "orig"}]}
  opencode_file.write_text(json.dumps(initial_content), encoding="utf-8")

  opencode_port = FakeOpenCodeFilePort(opencode_file)
  storage = FakeAccountStorage({"acc1": {"email": "acc1@test.com", "id": "acc1", "refresh_token": "token1"}})
  storage.fail_on_mark = RuntimeError("DB connection timeout")

  clock = FakeClock(1700002000.0)
  facade = AntigravityFacade(
      account_storage=storage,
      keyring=FakeKeyring(),
      gemini_files=FakeGeminiFilesPort(fake_root.gemini_dir),
      opencode_file=opencode_port,
      oauth=FakeOAuth(),
      process_manager=DummyProcessManager(),
      environment=DummyEnvironment(),
      clock=clock,
  )

  plan = facade.build_plan("acc1", TARGET_OPENCODE)
  res = facade.apply(plan)

  assert res.status == ApplyStatus.FAILED
  assert res.code == "db_mark_failed"

  # File harus di-rollback ke initial_content
  current_file_data = json.loads(opencode_file.read_text(encoding="utf-8"))
  assert current_file_data == initial_content


def test_restore_last_backup_does_not_modify_db_audit(fake_root):
  """Kriteria: Restore tidak mengubah kolom audit DB; indikator tetap membaca kenyataan."""
  opencode_file = fake_root.opencode_accounts_file
  opencode_file.parent.mkdir(parents=True, exist_ok=True)
  opencode_file.write_text(json.dumps({"version": 4, "accounts": [{"email": "old@test.com"}]}), encoding="utf-8")

  storage = FakeAccountStorage({"acc1": {"email": "new@test.com", "id": "acc1"}})
  storage.mark_applied("acc1", TARGET_OPENCODE, 1700003000)
  assert len(storage.applied_marks) == 1

  # Buat backup kondisi old
  clock = FakeClock(1700003100.0)
  backup_dir = create_opencode_backup(opencode_file, "old@test.com", clock.now())

  # Ubah file seolah-olah akun new telah terpasang
  opencode_file.write_text(json.dumps({"version": 4, "accounts": [{"email": "new@test.com"}]}), encoding="utf-8")

  facade = AntigravityFacade(
      account_storage=storage,
      keyring=FakeKeyring(),
      gemini_files=FakeGeminiFilesPort(fake_root.gemini_dir),
      opencode_file=FakeOpenCodeFilePort(opencode_file),
      oauth=FakeOAuth(),
      process_manager=DummyProcessManager(),
      environment=DummyEnvironment(),
      clock=clock,
  )

  # Jalankan restore_last_backup
  res = facade.restore_last_backup()
  assert res.status == ApplyStatus.SUCCESS
  assert res.restored_target == TARGET_OPENCODE
  assert res.restored_email == "old@test.com"

  # Pastikan kolom audit DB tidak diubah saat restore
  assert len(storage.applied_marks) == 1
  # File berhasil kembali ke old
  content = json.loads(opencode_file.read_text(encoding="utf-8"))
  assert content["accounts"][0]["email"] == "old@test.com"


def test_no_actions_when_no_backup_exists(fake_root):
  """Kriteria: Tidak ada backup, keyring, atau file lain yang dibaca/ditulis ketika tidak ada backup."""
  base_dir = get_backups_base_dir()
  if base_dir.exists():
    import shutil
    shutil.rmtree(base_dir, ignore_errors=True)

  keyring = FakeKeyring()
  storage = FakeAccountStorage()
  facade = AntigravityFacade(
      account_storage=storage,
      keyring=keyring,
      gemini_files=FakeGeminiFilesPort(fake_root.gemini_dir),
      opencode_file=FakeOpenCodeFilePort(fake_root.opencode_accounts_file),
      oauth=FakeOAuth(),
      process_manager=DummyProcessManager(),
      environment=DummyEnvironment(),
      clock=FakeClock(),
  )

  res = facade.restore_last_backup()
  assert res.status == ApplyStatus.SUCCESS
  assert "Tidak ada backup" in res.message
  # Keyring tidak pernah disentuh (tidak ada writes / deletes)
  assert len(keyring.writes) == 0
  assert len(keyring.deletes) == 0


# ─── Tests UI: Aksi Menu Pulihkan Backup Terakhir ──────────────────────────────


def test_menu_pulihkan_backup_terakhir_exists_in_settings_menu(qtbot):
  """Kriteria: Menu Pengaturan memiliki aksi 'Pulihkan Backup Terakhir…'."""
  from src.ui.main_window import MainWindow

  win = MainWindow()
  qtbot.addWidget(win)

  # Cari menu Pengaturan di menuBar
  menu_bar = win.menuBar()
  settings_menu = None
  for action in menu_bar.actions():
    if "Pengaturan" in action.text():
      settings_menu = action.menu()
      break

  assert settings_menu is not None, "Menu Pengaturan harus ada di menuBar"

  # Cari aksi Pulihkan Backup Terakhir
  restore_action = None
  for act in settings_menu.actions():
    if "Pulihkan" in act.text() and "Backup" in act.text():
      restore_action = act
      break

  assert restore_action is not None, "Aksi 'Pulihkan Backup Terakhir...' harus ada di menu Pengaturan"
  assert restore_action.isEnabled()
