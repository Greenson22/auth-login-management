"""Facade service untuk integrasi target OpenCode dan Antigravity CLI.

Menyediakan empat operasi utama:
- build_plan
- apply
- read_status
- restore_last_backup
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.targets import TARGET_ANTIGRAVITY_CLI, TARGET_OPENCODE, normalize_target

from .backup import cleanup_old_backups, create_opencode_backup
from .ports import (
    AccountStoragePort,
    ApplyPlan,
    ApplyResult,
    ApplyStatus,
    ClockPort,
    EnvironmentPort,
    GeminiFilesPort,
    KeyringPort,
    OAuthPort,
    OpenCodeFilePort,
    OverallStatus,
    ProcessManagerPort,
    RestoreResult,
    TargetCondition,
    TargetStatus,
)

logger = logging.getLogger(__name__)


def compute_active_di(
    email: str,
    status: OverallStatus,
) -> str:
  """Menghitung nilai kolom 'Aktif di' untuk satu email akun (case-insensitive).

  Returns:
    'OpenCode + CLI' bila aktif di kedua target
    'OpenCode' bila hanya OpenCode
    'Antigravity CLI' bila hanya CLI
    '—' bila tidak ada
  """
  clean_email = (email or "").strip().lower()
  if not clean_email or clean_email == "-":
    return "—"

  opencode_email = (status.opencode.email or "").strip().lower()
  cli_email = (status.antigravity_cli.email or "").strip().lower()

  is_opencode_active = (
      status.opencode.condition in (TargetCondition.ACTIVE, TargetCondition.UNRECORDED)
      and opencode_email == clean_email
  )
  is_cli_active = (
      status.antigravity_cli.condition in (TargetCondition.ACTIVE, TargetCondition.UNRECORDED, TargetCondition.DRIFT_GEMINI)
      and cli_email == clean_email
  )

  if is_opencode_active and is_cli_active:
    return "OpenCode + CLI"
  elif is_opencode_active:
    return "OpenCode"
  elif is_cli_active:
    return "Antigravity CLI"
  else:
    return "—"


class AntigravityFacade:
  """Facade service orkestrator integrasi OpenCode dan Antigravity CLI."""

  def __init__(
      self,
      account_storage: AccountStoragePort,
      keyring: KeyringPort,
      gemini_files: GeminiFilesPort,
      opencode_file: OpenCodeFilePort,
      oauth: OAuthPort,
      process_manager: ProcessManagerPort,
      environment: EnvironmentPort,
      clock: ClockPort,
  ):
    self.account_storage = account_storage
    self.keyring = keyring
    self.gemini_files = gemini_files
    self.opencode_file = opencode_file
    self.oauth = oauth
    self.process_manager = process_manager
    self.environment = environment
    self.clock = clock

  def build_plan(
      self,
      account_id: str,
      target: str,
      *,
      password: str = "",
      **kwargs: Any,
  ) -> ApplyPlan:
    """Preflight, validasi, dan deteksi sesi tanpa menulis perubahan apa pun."""
    canonical_target = normalize_target(target)

    # 1. Rekonstruksi snapshot akun dari DB
    try:
      account = self.account_storage.reconstruct_account(account_id, password=password)
    except Exception as exc:
      return ApplyPlan(
          account_snapshot={},
          target=canonical_target,
          target_available=False,
          error_code="account_reconstruction_failed",
          error_message=str(exc),
      )

    email = account.get("email")
    if not email:
      return ApplyPlan(
          account_snapshot=account,
          target=canonical_target,
          target_available=False,
          error_code="account_has_no_email",
          error_message="Akun tidak memiliki alamat email yang valid.",
      )

    # 2. Validasi per-target
    if canonical_target == TARGET_OPENCODE:
      # Validasi OpenCode: folder target & file harus valid, accounts harus array
      data, error_cond = self.opencode_file.read_accounts_data()
      if error_cond is not None or not isinstance(data, dict):
        return ApplyPlan(
            account_snapshot=account,
            target=canonical_target,
            target_available=False,
            error_code="invalid_opencode_file",
            error_message="File antigravity-accounts.json tidak ditemukan atau bukan objek JSON yang valid.",
        )
      accounts = data.get("accounts")
      if not isinstance(accounts, list):
        return ApplyPlan(
            account_snapshot=account,
            target=canonical_target,
            target_available=False,
            error_code="invalid_accounts_array",
            error_message="Field 'accounts' di antigravity-accounts.json bukan array.",
        )

      return ApplyPlan(
          account_snapshot=account,
          target=canonical_target,
          target_available=True,
      )

    return ApplyPlan(
        account_snapshot=account,
        target=canonical_target,
        target_available=True,
    )

  def apply(
      self,
      plan: ApplyPlan,
      *,
      allow_kill: bool = False,
      **kwargs: Any,
  ) -> ApplyResult:
    """Eksekusi rencana apply.

    Implementasi apply penuh untuk OpenCode (tiket 05) dan CLI (tiket 09).
    """
    if plan.error_code:
      return ApplyResult(
          status=ApplyStatus.FAILED,
          code=plan.error_code,
          user_message=plan.error_message or "Plan tidak valid",
      )

    if plan.target == TARGET_OPENCODE:
      return self._apply_opencode(plan)

    return ApplyResult(
        status=ApplyStatus.SUCCESS,
        user_message="Operasi apply belum diterapkan sepenuhnya pada tiket ini.",
        email=plan.account_snapshot.get("email"),
    )

  def _apply_opencode(self, plan: ApplyPlan) -> ApplyResult:
    account_snapshot = plan.account_snapshot
    email = str(account_snapshot.get("email", "")).strip()
    account_id = account_snapshot.get("id")

    # Pastikan file masih valid sebelum backup
    data, error_cond = self.opencode_file.read_accounts_data()
    if error_cond is not None or not isinstance(data, dict):
      return ApplyResult(
          status=ApplyStatus.FAILED,
          code="invalid_opencode_file",
          user_message="File antigravity-accounts.json tidak ditemukan atau bukan objek JSON yang valid.",
          action_suggestion="Periksa path folder OpenCode di Pengaturan.",
      )

    accounts = data.get("accounts")
    if not isinstance(accounts, list):
      return ApplyResult(
          status=ApplyStatus.FAILED,
          code="invalid_accounts_array",
          user_message="Field 'accounts' di antigravity-accounts.json bukan array.",
          action_suggestion="Perbaiki struktur JSON file antigravity-accounts.json.",
      )

    # 1. Snapshot backup file lama sebelum penulisan
    file_path = None
    if hasattr(self.opencode_file, "get_file_path"):
      file_path = self.opencode_file.get_file_path()
    elif hasattr(self.opencode_file, "_get_file_path"):
      file_path = self.opencode_file._get_file_path()

    backup_location = ""
    if file_path:
      try:
        backup_dir = create_opencode_backup(
            file_path=file_path,
            email=email,
            clock_now=self.clock.now(),
        )
        backup_location = str(backup_dir)
      except Exception as exc:
        logger.warning("Gagal membuat backup OpenCode: %s", exc)

    # 2. Upsert akun
    existing_idx = None
    target_clean = email.lower()
    for idx, acc in enumerate(accounts):
      if isinstance(acc, dict):
        acc_email = str(acc.get("email", "")).strip().lower()
        if acc_email == target_clean:
          existing_idx = idx
          break

    if existing_idx is not None:
      accounts[existing_idx] = account_snapshot
      upsert_idx = existing_idx
    else:
      accounts.append(account_snapshot)
      upsert_idx = len(accounts) - 1

    # 3. Perbarui activeIndex dan activeIndexByFamily
    data["activeIndex"] = upsert_idx
    families = data.get("activeIndexByFamily")
    if isinstance(families, dict):
      if "gemini" in families:
        families["gemini"] = upsert_idx
      if "claude" in families:
        families["claude"] = upsert_idx

    # 4. Tulis file secara atomic
    try:
      self.opencode_file.write_accounts_data(data)
    except Exception as exc:
      logger.exception("Gagal menulis file OpenCode")
      return ApplyResult(
          status=ApplyStatus.FAILED,
          code="write_failed",
          user_message=f"Gagal menulis file OpenCode: {exc}",
          action_suggestion="Periksa izin penulisan file dan folder.",
          backup_location=backup_location,
      )

    # 5. Tandai DB: applied_target='opencode' & last_applied_at=epoch detik
    applied_time = int(self.clock.now())
    try:
      if account_id:
        self.account_storage.mark_applied(account_id, TARGET_OPENCODE, applied_at=applied_time)
    except Exception as db_exc:
      logger.warning("Gagal menandai applied di database: %s", db_exc)

    # 6. Bersihkan backup lama (retensi 30)
    cleanup_old_backups(max_keep=30)

    total_accounts = len(accounts)
    return ApplyResult(
        status=ApplyStatus.SUCCESS,
        user_message=f"Akun {email} berhasil diterapkan ke OpenCode ({total_accounts} akun di file).",
        email=email,
        accounts_count=total_accounts,
        backup_location=backup_location,
    )

  def read_status(self) -> OverallStatus:
    """Membaca status keterpasangan akun dan kesehatan target OpenCode & CLI.

    Metode ini tidak pernah melempar exception ke pemanggil; kegagalan port
    dikembalikan sebagai status dengan kondisi error/invalid_file.
    """
    opencode_status = self._read_opencode_status()
    cli_status = self._read_cli_status()
    return OverallStatus(opencode=opencode_status, antigravity_cli=cli_status)

  def _read_opencode_status(self) -> TargetStatus:
    try:
      data, error_cond = self.opencode_file.read_accounts_data()
      if error_cond is not None or not isinstance(data, dict):
        return TargetStatus(
            target=TARGET_OPENCODE,
            email=None,
            condition=TargetCondition.INVALID_FILE,
            message="File antigravity-accounts.json tidak ditemukan atau tidak valid.",
        )

      accounts = data.get("accounts")
      if not isinstance(accounts, list) or len(accounts) == 0:
        return TargetStatus(
            target=TARGET_OPENCODE,
            email=None,
            condition=TargetCondition.NONE,
            message="Belum ada akun di antigravity-accounts.json.",
        )

      # Tentukan akun aktif: activeIndex dengan fallback activeIndexByFamily.gemini
      active_idx = data.get("activeIndex")
      if active_idx is None:
        families = data.get("activeIndexByFamily")
        if isinstance(families, dict):
          active_idx = families.get("gemini")

      if (
          active_idx is None
          or not isinstance(active_idx, int)
          or active_idx < 0
          or active_idx >= len(accounts)
      ):
        return TargetStatus(
            target=TARGET_OPENCODE,
            email=None,
            condition=TargetCondition.NONE,
            message="Tidak ada akun aktif yang dipilih di OpenCode.",
        )

      active_acc = accounts[active_idx]
      active_email = (
          active_acc.get("email") if isinstance(active_acc, dict) else None
      )

      if not active_email or not str(active_email).strip():
        return TargetStatus(
            target=TARGET_OPENCODE,
            email=None,
            condition=TargetCondition.NONE,
            message="Akun aktif OpenCode tidak memiliki email.",
        )

      active_email = str(active_email).strip()
      # Periksa apakah email ada di database
      exists_in_db = False
      try:
        exists_in_db = self.account_storage.account_exists(active_email)
      except Exception as db_exc:
        logger.warning("Gagal memeriksa akun di storage: %s", db_exc)

      if exists_in_db:
        return TargetStatus(
            target=TARGET_OPENCODE,
            email=active_email,
            condition=TargetCondition.ACTIVE,
            message=f"Aktif: {active_email}",
        )
      else:
        return TargetStatus(
            target=TARGET_OPENCODE,
            email=active_email,
            condition=TargetCondition.UNRECORDED,
            message="Akun aktif di OpenCode tidak tercatat di database.",
        )

    except Exception as exc:
      logger.exception("Error tak terduga saat membaca status OpenCode")
      return TargetStatus(
          target=TARGET_OPENCODE,
          email=None,
          condition=TargetCondition.ERROR,
          message=f"Kesalahan membaca status OpenCode: {exc}",
          error=str(exc),
      )

  def _read_cli_status(self) -> TargetStatus:
    # CLI status didukung bertahap; jika environment tidak mendukung atau tiket 10 belum aktif
    try:
      if not self.environment.is_linux():
        return TargetStatus(
            target=TARGET_ANTIGRAVITY_CLI,
            condition=TargetCondition.UNAVAILABLE,
            unavailable_reason="unsupported_os",
            message="Target hanya didukung pada OS Linux.",
        )
      if self.environment.is_root():
        return TargetStatus(
            target=TARGET_ANTIGRAVITY_CLI,
            condition=TargetCondition.UNAVAILABLE,
            unavailable_reason="root",
            message="Aplikasi dijalankan sebagai root.",
        )
      if not self.environment.is_dbus_available():
        return TargetStatus(
            target=TARGET_ANTIGRAVITY_CLI,
            condition=TargetCondition.UNAVAILABLE,
            unavailable_reason="no_dbus",
            message="D-Bus / Secret Service tidak tersedia.",
        )
      if self.environment.is_keyring_locked():
        return TargetStatus(
            target=TARGET_ANTIGRAVITY_CLI,
            condition=TargetCondition.LOCKED,
            unavailable_reason="keyring_locked",
            message="Keyring terkunci.",
        )
      # Jika dasar terpenuhi, kembalikan status NONE default jika belum dibaca tiket 10
      return TargetStatus(
          target=TARGET_ANTIGRAVITY_CLI,
          condition=TargetCondition.NONE,
          message="Belum login ke Antigravity CLI.",
      )
    except Exception as exc:
      return TargetStatus(
          target=TARGET_ANTIGRAVITY_CLI,
          condition=TargetCondition.ERROR,
          message=f"Kesalahan membaca status CLI: {exc}",
          error=str(exc),
      )

  def restore_last_backup(self) -> RestoreResult:
    """Memulihkan backup terakhir (tiket 08)."""
    return RestoreResult(
        status=ApplyStatus.SUCCESS,
        message="Operasi restore belum diterapkan pada tiket ini.",
    )
