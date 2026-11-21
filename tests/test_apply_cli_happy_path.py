"""Tests untuk Tiket 09: Apply ke Antigravity CLI — happy path.

Kriteria yang diuji:
1. Preflight memastikan availability target, akun ada di DB, refresh_token tidak kosong dan bentuk wajar.
2. Validasi token memanggil OAuth endpoint Google (timeout 30 detik, tanpa retry otomatis).
3. Respons wajib memuat access_token, id_token, dan email cocok case-insensitive dengan akun.
4. Apply mendeteksi ulang sesi: bila ada sesi hidup tanpa izin kill -> gagal tanpa tulis; bila diizinkan -> terminate -> deteksi ulang.
5. Snapshot keyring dan file ~/.gemini dibuat setelah sesi bersih dan sebelum tulis pertama.
6. Keyring diperbarui pada item service=gemini, username=antigravity, schema org.freedesktop.Secret.Generic.
7. Payload keyring mempertahankan auth_method dan writer_id yang ada (bila tidak ada dibuat 32-byte base64url).
8. Token keyring menyimpan access_token, token_type, refresh_token, expiry RFC3339 dengan skew 30 detik, dan expires_in.
9. oauth_creds.json memuat access_token, scope, token_type, id_token, expiry_date (ms), dan refresh_token.
10. google_accounts.json memuat active=email baru dan old=gabungan unik old lama + email aktif sebelumnya, dikurangi email baru.
11. Direktori ~/.gemini belum ada -> dibuat mode 0700 lalu file ditulis mode 0600.
12. Verifikasi membaca ulang keyring dan file; email dan refresh token cocok dengan plan.
13. Apply sukses menandai DB applied_target='antigravity_cli' dan last_applied_at.
14. Deteksi ulang dilakukan tepat sebelum menulis keyring; sesi baru menggagalkan Apply tanpa penulisan.
15. Apply CLI hanya menyentuh item keyring gemini/antigravity, tidak pernah item lain.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from src.integrations.antigravity.constants import (
    KEYRING_SCHEMA,
    KEYRING_SERVICE,
    KEYRING_USERNAME,
)
from src.integrations.antigravity.ports import (
    ApplyPlan,
    ApplyResult,
    ApplyStatus,
)
from src.integrations.antigravity.process import LinuxProcessManager
from src.integrations.antigravity.service import AntigravityFacade
from src.targets import TARGET_ANTIGRAVITY_CLI
from tests.fakes import (
    FakeClock,
    FakeKeyring,
    FakeOAuth,
    FakeProcTable,
    FakeRoot,
    FakeSignalSender,
    make_id_token,
)


class FakeAccountStorage:
  def __init__(self, accounts: Optional[Dict[str, Dict[str, Any]]] = None):
    self.accounts = accounts or {}
    self.applied_marks: List[Dict[str, Any]] = []
    self.updated_tokens: List[Dict[str, Any]] = []

  def reconstruct_account(self, account_id: str, password: str = "") -> Dict[str, Any]:
    if account_id not in self.accounts:
      raise ValueError(f"Akun {account_id} tidak ditemukan")
    return dict(self.accounts[account_id])

  def mark_applied(self, account_id: str, target: str, applied_at: Optional[int] = None) -> bool:
    self.applied_marks.append({
        "account_id": account_id,
        "target": target,
        "applied_at": applied_at,
    })
    return True

  def update_refresh_token(self, account_id: str, new_refresh_token: str, password: str = "") -> bool:
    self.updated_tokens.append({
        "account_id": account_id,
        "new_refresh_token": new_refresh_token,
    })
    return True

  def account_exists(self, email: str) -> bool:
    return any(
        acc.get("email", "").lower() == email.lower()
        for acc in self.accounts.values()
    )


class FakeGeminiFilesPort:
  def __init__(self, gemini_dir: Path):
    self.gemini_dir = gemini_dir

  def read_oauth_creds(self) -> Optional[Dict[str, Any]]:
    path = self.gemini_dir / "oauth_creds.json"
    if not path.exists():
      return None
    return json.loads(path.read_text(encoding="utf-8"))

  def write_oauth_creds(self, creds: Dict[str, Any]) -> None:
    self.gemini_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    path = self.gemini_dir / "oauth_creds.json"
    path.write_text(json.dumps(creds, indent=2), encoding="utf-8")
    path.chmod(0o600)

  def read_google_accounts(self) -> Optional[Dict[str, Any]]:
    path = self.gemini_dir / "google_accounts.json"
    if not path.exists():
      return None
    return json.loads(path.read_text(encoding="utf-8"))

  def write_google_accounts(self, accounts: Dict[str, Any]) -> None:
    self.gemini_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    path = self.gemini_dir / "google_accounts.json"
    path.write_text(json.dumps(accounts, indent=2), encoding="utf-8")
    path.chmod(0o600)


class DummyOpenCodePort:
  def read_accounts_data(self):
    return {"accounts": [], "activeIndex": 0}, None

  def write_accounts_data(self, data):
    pass


class DummyEnvironment:
  def __init__(self, is_linux=True, is_root=False, is_dbus=True, is_locked=False):
    self._is_linux = is_linux
    self._is_root = is_root
    self._is_dbus = is_dbus
    self._is_locked = is_locked

  def is_linux(self) -> bool:
    return self._is_linux

  def is_root(self) -> bool:
    return self._is_root

  def is_dbus_available(self) -> bool:
    return self._is_dbus

  def is_keyring_locked(self) -> bool:
    return self._is_locked


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_cli_happy_path_end_to_end(fake_root: FakeRoot):
  """Happy path penuh: token divalidasi, snapshot dibuat, keyring dan ~/.gemini ditulis, DB ditandai."""
  clock = FakeClock(1700000000.0)
  account_email = "tester@example.com"
  account_rt = "1//valid-refresh-token-12345"

  storage = FakeAccountStorage({
      "acc1": {
          "id": "acc1",
          "email": account_email,
          "refresh_token": account_rt,
      }
  })

  keyring = FakeKeyring()
  # Beri item lain pada keyring untuk memastikan item lain tidak disentuh
  keyring.write("other_service", "other_user", b"unrelated_data")

  gemini_port = FakeGeminiFilesPort(fake_root.gemini_dir)
  oauth = FakeOAuth(clock)
  oauth.respond_for(
      account_email,
      access_token="ya29.new-access-token",
      refresh_token=account_rt,
      expires_in=3600,
  )

  proc_table = FakeProcTable()
  fake_root.proc.mkdir(parents=True, exist_ok=True)
  proc_table.write_to(fake_root.proc)
  proc_mgr = LinuxProcessManager(
      proc_path=fake_root.proc,
      clock=clock,
      excluded_pids=(),
  )

  fake_root.proc.mkdir(parents=True, exist_ok=True)
  facade = AntigravityFacade(
      account_storage=storage,
      keyring=keyring,
      gemini_files=gemini_port,
      opencode_file=DummyOpenCodePort(),
      oauth=oauth,
      process_manager=proc_mgr,
      environment=DummyEnvironment(),
      clock=clock,
  )

  # 1. Build Plan
  plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)
  assert plan.target_available is True
  assert plan.error_code is None
  assert plan.validated_token is not None
  assert plan.validated_token["email"] == account_email
  assert plan.validated_token["access_token"] == "ya29.new-access-token"
  assert len(keyring.writes) == 1  # Hanya item unrelated_data yang ditulis sebelumnya

  # 2. Apply
  result = facade.apply(plan)
  assert result.status == ApplyStatus.SUCCESS
  assert result.email == account_email
  assert result.backup_location is not None
  assert Path(result.backup_location).exists()

  # 3. Verifikasi Keyring
  kr_bytes = keyring.read(KEYRING_SERVICE, KEYRING_USERNAME)
  assert kr_bytes is not None
  kr_data = json.loads(kr_bytes.decode("utf-8"))
  assert kr_data["id_token_email"] == account_email
  assert kr_data["auth_method"] == "consumer"
  assert len(kr_data["writer_id"]) > 20
  token_sec = kr_data["token"]
  assert token_sec["access_token"] == "ya29.new-access-token"
  assert token_sec["refresh_token"] == account_rt
  assert token_sec["token_type"] == "Bearer"
  assert token_sec["expires_in"] == 3600
  assert "T" in token_sec["expiry"]  # RFC3339

  # Pastikan item lain di keyring tidak disentuh
  other_bytes = keyring.read("other_service", "other_user")
  assert other_bytes == b"unrelated_data"

  # 4. Verifikasi oauth_creds.json
  creds = gemini_port.read_oauth_creds()
  assert creds is not None
  assert creds["access_token"] == "ya29.new-access-token"
  assert creds["refresh_token"] == account_rt
  assert creds["token_type"] == "Bearer"
  assert "openid" in creds["scope"]
  assert isinstance(creds["expiry_date"], int)

  # 5. Verifikasi google_accounts.json
  accs = gemini_port.read_google_accounts()
  assert accs is not None
  assert accs["active"] == account_email
  assert accs["old"] == []

  # 6. Verifikasi penandaan DB
  assert len(storage.applied_marks) == 1
  assert storage.applied_marks[0]["account_id"] == "acc1"
  assert storage.applied_marks[0]["target"] == TARGET_ANTIGRAVITY_CLI
  assert storage.applied_marks[0]["applied_at"] == int(clock.now())


def test_cli_preserves_existing_auth_method_and_writer_id(fake_root: FakeRoot):
  """Payload keyring mempertahankan auth_method dan writer_id yang ada sebelumnya."""
  clock = FakeClock()
  keyring = FakeKeyring()
  existing_payload = {
      "token": {"access_token": "old", "refresh_token": "old_rt"},
      "auth_method": "custom_enterprise",
      "writer_id": "existing-writer-id-xyz",
      "id_token_email": "prev@example.com",
  }
  keyring.write(KEYRING_SERVICE, KEYRING_USERNAME, json.dumps(existing_payload).encode("utf-8"))

  storage = FakeAccountStorage({
      "acc1": {"id": "acc1", "email": "new@example.com", "refresh_token": "1//rt_long_token"}
  })
  oauth = FakeOAuth(clock)
  oauth.respond_for("new@example.com", refresh_token="1//rt_long_token")

  fake_root.proc.mkdir(parents=True, exist_ok=True)
  facade = AntigravityFacade(
      account_storage=storage,
      keyring=keyring,
      gemini_files=FakeGeminiFilesPort(fake_root.gemini_dir),
      opencode_file=DummyOpenCodePort(),
      oauth=oauth,
      process_manager=LinuxProcessManager(proc_path=fake_root.proc, clock=clock),
      environment=DummyEnvironment(),
      clock=clock,
  )

  plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)
  res = facade.apply(plan)
  assert res.status == ApplyStatus.SUCCESS

  updated_data = json.loads(keyring.read(KEYRING_SERVICE, KEYRING_USERNAME).decode("utf-8"))
  assert updated_data["auth_method"] == "custom_enterprise"
  assert updated_data["writer_id"] == "existing-writer-id-xyz"
  assert updated_data["id_token_email"] == "new@example.com"


def test_cli_google_accounts_merges_old_emails(fake_root: FakeRoot):
  """google_accounts.json menggabungkan riwayat email lama dan email aktif sebelumnya."""
  clock = FakeClock()
  gemini_port = FakeGeminiFilesPort(fake_root.gemini_dir)
  gemini_port.write_google_accounts({
      "active": "previous_active@example.com",
      "old": ["historical1@example.com", "historical2@example.com"],
  })

  storage = FakeAccountStorage({
      "acc1": {"id": "acc1", "email": "brand_new@example.com", "refresh_token": "1//rt_long_token"}
  })
  oauth = FakeOAuth(clock)
  oauth.respond_for("brand_new@example.com", refresh_token="1//rt_long_token")

  fake_root.proc.mkdir(parents=True, exist_ok=True)
  facade = AntigravityFacade(
      account_storage=storage,
      keyring=FakeKeyring(),
      gemini_files=gemini_port,
      opencode_file=DummyOpenCodePort(),
      oauth=oauth,
      process_manager=LinuxProcessManager(proc_path=fake_root.proc, clock=clock),
      environment=DummyEnvironment(),
      clock=clock,
  )

  plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)
  res = facade.apply(plan)
  assert res.status == ApplyStatus.SUCCESS

  accs = gemini_port.read_google_accounts()
  assert accs["active"] == "brand_new@example.com"
  # old memuat historical1, historical2, dan previous_active (tanpa duplikat dan tanpa brand_new)
  assert "previous_active@example.com" in accs["old"]
  assert "historical1@example.com" in accs["old"]
  assert "historical2@example.com" in accs["old"]
  assert "brand_new@example.com" not in accs["old"]


def test_cli_preflight_validates_refresh_token_before_writing(fake_root: FakeRoot):
  """Preflight gagal bila refresh token kosong atau tidak wajar, sebelum OAuth dan sebelum backup."""
  clock = FakeClock()
  storage = FakeAccountStorage({
      "acc_empty": {"id": "acc_empty", "email": "test@example.com", "refresh_token": ""},
      "acc_space": {"id": "acc_space", "email": "test@example.com", "refresh_token": "token with spaces"},
  })
  keyring = FakeKeyring()
  oauth = FakeOAuth(clock)

  fake_root.proc.mkdir(parents=True, exist_ok=True)
  facade = AntigravityFacade(
      account_storage=storage,
      keyring=keyring,
      gemini_files=FakeGeminiFilesPort(fake_root.gemini_dir),
      opencode_file=DummyOpenCodePort(),
      oauth=oauth,
      process_manager=LinuxProcessManager(proc_path=fake_root.proc, clock=clock),
      environment=DummyEnvironment(),
      clock=clock,
  )

  plan_empty = facade.build_plan("acc_empty", TARGET_ANTIGRAVITY_CLI)
  assert plan_empty.target_available is False
  assert plan_empty.error_code == "empty_refresh_token"
  assert len(oauth.calls) == 0

  plan_space = facade.build_plan("acc_space", TARGET_ANTIGRAVITY_CLI)
  assert plan_space.target_available is False
  assert plan_space.error_code == "invalid_refresh_token_format"
  assert len(oauth.calls) == 0


def test_cli_id_token_email_mismatch_fails_without_writing(fake_root: FakeRoot):
  """id_token dengan email berbeda dari email akun menggagalkan Apply sebelum tulis."""
  clock = FakeClock()
  storage = FakeAccountStorage({
      "acc1": {"id": "acc1", "email": "expected@example.com", "refresh_token": "1//valid-token"}
  })
  oauth = FakeOAuth(clock)
  # Server mengembalikan token milik email lain
  oauth.respond_for("different_user@example.com", refresh_token="1//valid-token")

  keyring = FakeKeyring()
  fake_root.proc.mkdir(parents=True, exist_ok=True)
  facade = AntigravityFacade(
      account_storage=storage,
      keyring=keyring,
      gemini_files=FakeGeminiFilesPort(fake_root.gemini_dir),
      opencode_file=DummyOpenCodePort(),
      oauth=oauth,
      process_manager=LinuxProcessManager(proc_path=fake_root.proc, clock=clock),
      environment=DummyEnvironment(),
      clock=clock,
  )

  plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)
  assert plan.target_available is False
  assert plan.error_code == "email_mismatch"
  assert len(keyring.writes) == 0


def test_cli_gemini_directory_created_with_0700_if_not_exists(fake_root: FakeRoot):
  """Bila direktori ~/.gemini belum ada, dibuat otomatis dengan mode 0700."""
  gemini_dir = fake_root.gemini_dir
  if gemini_dir.exists():
    import shutil
    shutil.rmtree(gemini_dir)

  assert not gemini_dir.exists()

  clock = FakeClock()
  storage = FakeAccountStorage({
      "acc1": {"id": "acc1", "email": "first_run@example.com", "refresh_token": "1//first_run_token"}
  })
  oauth = FakeOAuth(clock)
  oauth.respond_for("first_run@example.com", refresh_token="1//first_run_token")

  gemini_port = FakeGeminiFilesPort(gemini_dir)
  fake_root.proc.mkdir(parents=True, exist_ok=True)
  facade = AntigravityFacade(
      account_storage=storage,
      keyring=FakeKeyring(),
      gemini_files=gemini_port,
      opencode_file=DummyOpenCodePort(),
      oauth=oauth,
      process_manager=LinuxProcessManager(proc_path=fake_root.proc, clock=clock),
      environment=DummyEnvironment(),
      clock=clock,
  )

  plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)
  res = facade.apply(plan)
  assert res.status == ApplyStatus.SUCCESS
  assert gemini_dir.exists()
  # Izin folder 0700
  assert (gemini_dir.stat().st_mode & 0o777) == 0o700


def test_cli_apply_verification_mismatch_triggers_rollback(fake_root: FakeRoot):
  """Ketidakcocokan saat verifikasi pembacaan ulang memicu rollback penuh."""
  clock = FakeClock()
  storage = FakeAccountStorage({
      "acc1": {"id": "acc1", "email": "rollback@example.com", "refresh_token": "1//rollback_token"}
  })
  oauth = FakeOAuth(clock)
  oauth.respond_for("rollback@example.com", refresh_token="1//rollback_token")

  keyring = FakeKeyring()
  # Pasang keyring awal
  init_kr = {"token": {"refresh_token": "original_token"}, "auth_method": "consumer", "id_token_email": "orig@example.com"}
  keyring.write(KEYRING_SERVICE, KEYRING_USERNAME, json.dumps(init_kr).encode("utf-8"))

  # Buat gemini files port yang gagal mengembalikan token yang benar saat dibaca ulang
  class TamperingGeminiFilesPort(FakeGeminiFilesPort):
    def read_oauth_creds(self):
      # Rusak hasil baca ulang verifikasi
      return {"refresh_token": "corrupted_token"}

  tampered_gemini = TamperingGeminiFilesPort(fake_root.gemini_dir)

  fake_root.proc.mkdir(parents=True, exist_ok=True)
  facade = AntigravityFacade(
      account_storage=storage,
      keyring=keyring,
      gemini_files=tampered_gemini,
      opencode_file=DummyOpenCodePort(),
      oauth=oauth,
      process_manager=LinuxProcessManager(proc_path=fake_root.proc, clock=clock),
      environment=DummyEnvironment(),
      clock=clock,
  )

  plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)
  res = facade.apply(plan)

  assert res.status == ApplyStatus.FAILED
  assert res.code == "verification_failed"
  assert "rollback" in res.user_message.lower()
  assert res.backup_location is not None

  # Keyring harus telah di-rollback ke initial
  restored_kr = json.loads(keyring.read(KEYRING_SERVICE, KEYRING_USERNAME).decode("utf-8"))
  assert restored_kr["id_token_email"] == "orig@example.com"
  # DB tidak boleh ditandai
  assert len(storage.applied_marks) == 0
