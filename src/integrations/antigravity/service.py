"""Facade service untuk integrasi target OpenCode dan Antigravity CLI.

Menyediakan empat operasi utama:
- build_plan
- apply
- read_status
- restore_last_backup
"""

from __future__ import annotations

import base64
import datetime
import json
import logging
import os
import secrets
from typing import Any, Dict, List, Optional

from src.targets import TARGET_ANTIGRAVITY_CLI, TARGET_OPENCODE, normalize_target

from .backup import (
    cleanup_old_backups,
    create_cli_backup,
    create_opencode_backup,
    get_latest_backup,
    rollback_from_backup,
)
from .constants import KEYRING_SERVICE, KEYRING_USERNAME
from .errors import OAuthError
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


def _decode_id_token_email(id_token: str) -> Optional[str]:
  """Membaca klaim email dari payload JWT id_token tanpa memverifikasi tanda tangan."""
  try:
    parts = id_token.split(".")
    if len(parts) < 2:
      return None
    payload_b64 = parts[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    email = payload.get("email")
    return str(email).strip().lower() if email else None
  except Exception:
    return None


def _format_rfc3339_with_skew(timestamp: float, skew_seconds: float = 30.0) -> str:
  """Format timestamp epoch ke format RFC3339 (ISO8601) dengan timezone lokal dan skew 30 detik."""
  dt = datetime.datetime.fromtimestamp(timestamp + skew_seconds).astimezone()
  return dt.isoformat()


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

    # Validasi Antigravity CLI (tiket 06, 07, 09)
    # Availability check
    if not self.environment.is_linux():
      return ApplyPlan(
          account_snapshot=account,
          target=canonical_target,
          target_available=False,
          unavailable_reason="unsupported_os",
          error_code="unsupported_os",
          error_message="Target Antigravity CLI hanya didukung di OS Linux.",
      )
    if self.environment.is_root():
      return ApplyPlan(
          account_snapshot=account,
          target=canonical_target,
          target_available=False,
          unavailable_reason="root",
          error_code="root",
          error_message="Aplikasi dijalankan sebagai root (tidak aman).",
      )
    if not self.environment.is_dbus_available():
      return ApplyPlan(
          account_snapshot=account,
          target=canonical_target,
          target_available=False,
          unavailable_reason="no_dbus",
          error_code="no_dbus",
          error_message="D-Bus / Secret Service tidak tersedia.",
      )
    if self.environment.is_keyring_locked():
      return ApplyPlan(
          account_snapshot=account,
          target=canonical_target,
          target_available=False,
          unavailable_reason="keyring_locked",
          error_code="keyring_locked",
          error_message="Keyring terkunci. Silakan buka keyring terlebih dahulu.",
      )

    # Deteksi sesi agy terlebih dahulu
    try:
      sessions = self.process_manager.detect_sessions()
    except Exception as exc:
      logger.exception("Gagal membaca /proc untuk deteksi sesi agy")
      return ApplyPlan(
          account_snapshot=account,
          target=canonical_target,
          target_available=False,
          error_code="proc_unreadable",
          error_message="Tidak dapat membaca /proc (periksa proses manual). Tidak ada perubahan yang ditulis.",
      )

    auto_kill = kwargs.get("auto_kill_agy", False)
    # Sesi hidup (R, S, D, T, t) memerlukan penanganan
    alive_sessions = [
        s for s in sessions
        if getattr(s, "is_alive", True) and not getattr(s, "is_zombie", False)
    ]
    requires_confirmation = bool(alive_sessions and not auto_kill)

    # Validasi format refresh_token akun
    raw_refresh_token = account.get("refresh_token")
    if not raw_refresh_token or not isinstance(raw_refresh_token, str) or not raw_refresh_token.strip():
      return ApplyPlan(
          account_snapshot=account,
          target=canonical_target,
          target_available=False,
          detected_sessions=sessions,
          requires_confirmation=requires_confirmation,
          error_code="empty_refresh_token",
          error_message="Refresh token akun kosong atau tidak valid.",
      )

    clean_rt = raw_refresh_token.strip()
    # Bentuk wajar: tidak kosong, tidak memuat spasi/karakter newline
    if any(c.isspace() for c in clean_rt) or len(clean_rt) < 5:
      return ApplyPlan(
          account_snapshot=account,
          target=canonical_target,
          target_available=False,
          detected_sessions=sessions,
          requires_confirmation=requires_confirmation,
          error_code="invalid_refresh_token_format",
          error_message="Format refresh token tidak wajar (memuat spasi atau karakter ilegal).",
      )

    # Validasi token ke endpoint OAuth Google
    try:
      token_resp = self.oauth.exchange_refresh_token(clean_rt)
    except Exception as oauth_exc:
      err_code = getattr(oauth_exc, "code", "oauth_failed")
      err_desc = getattr(oauth_exc, "description", str(oauth_exc))
      if err_code == "invalid_grant":
        msg = "Refresh token telah dicabut atau kedaluwarsa (invalid_grant). Silakan login ulang."
      elif err_code == "unauthorized_client":
        msg = "Token bukan milik client Antigravity (unauthorized_client). Silakan login ulang."
      else:
        msg = f"Gagal memvalidasi token ke Google: {err_code} - {err_desc}"

      return ApplyPlan(
          account_snapshot=account,
          target=canonical_target,
          target_available=False,
          detected_sessions=sessions,
          requires_confirmation=requires_confirmation,
          error_code=err_code,
          error_message=msg,
      )

    # Respons wajib memuat access_token
    access_token = getattr(token_resp, "access_token", None) or (
        token_resp.get("access_token") if isinstance(token_resp, dict) else None
    )
    if not access_token:
      return ApplyPlan(
          account_snapshot=account,
          target=canonical_target,
          target_available=False,
          detected_sessions=sessions,
          requires_confirmation=requires_confirmation,
          error_code="missing_access_token",
          error_message="Respons server token Google tidak memuat access_token.",
      )

    # id_token dan email di dalamnya wajib ada dan sama (case-insensitive) dengan email akun
    id_token = getattr(token_resp, "id_token", None) or (
        token_resp.get("id_token") if isinstance(token_resp, dict) else None
    )
    token_email = getattr(token_resp, "email", None)
    if not token_email and id_token:
      token_email = _decode_id_token_email(id_token)

    if not id_token or not token_email:
      return ApplyPlan(
          account_snapshot=account,
          target=canonical_target,
          target_available=False,
          detected_sessions=sessions,
          requires_confirmation=requires_confirmation,
          error_code="missing_id_token_email",
          error_message="Respons token Google tidak memuat id_token atau klaim email.",
      )

    if token_email.strip().lower() != email.strip().lower():
      return ApplyPlan(
          account_snapshot=account,
          target=canonical_target,
          target_available=False,
          detected_sessions=sessions,
          requires_confirmation=requires_confirmation,
          error_code="email_mismatch",
          error_message=f"Email pada token ({token_email}) tidak cocok dengan email akun ({email}).",
      )

    # Bungkus hasil validasi token ke dict terstruktur
    validated_token_data = {
        "access_token": access_token,
        "token_type": getattr(token_resp, "token_type", "Bearer") or "Bearer",
        "refresh_token": getattr(token_resp, "refresh_token", None) or clean_rt,
        "expires_in": int(getattr(token_resp, "expires_in", 3600) or 3600),
        "expiry": float(getattr(token_resp, "expiry", self.clock.now() + 3600) or (self.clock.now() + 3600)),
        "id_token": id_token,
        "email": token_email,
    }

    return ApplyPlan(
        account_snapshot=account,
        target=canonical_target,
        target_available=True,
        validated_token=validated_token_data,
        detected_sessions=sessions,
        requires_confirmation=requires_confirmation,
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

    # Apply Antigravity CLI
    return self._apply_cli(plan, allow_kill=allow_kill, **kwargs)

  def _apply_cli(
      self,
      plan: ApplyPlan,
      *,
      allow_kill: bool = False,
      **kwargs: Any,
  ) -> ApplyResult:
    # 1. Periksa sesi yang berjalan
    try:
      current_sessions = self.process_manager.detect_sessions()
    except Exception as exc:
      return ApplyResult(
          status=ApplyStatus.FAILED,
          code="proc_unreadable",
          user_message="Gagal memeriksa proses: tidak dapat membaca /proc. Periksa proses manual.",
          action_suggestion="Pastikan aplikasi memiliki izin mengakses /proc.",
      )

    alive_sessions = [
        s for s in current_sessions
        if getattr(s, "is_alive", True) and not getattr(s, "is_zombie", False)
    ]

    if alive_sessions:
      if not allow_kill:
        return ApplyResult(
            status=ApplyStatus.FAILED,
            code="sessions_still_running",
            user_message="Terdapat sesi agy yang masih berjalan dan izin penghentian belum diberikan.",
            action_suggestion="Hentikan sesi agy sebelum menerapkan kredensial ke Antigravity CLI.",
        )

      # Lakukan penghentian sesi
      terminate_fn = getattr(self.process_manager, "terminate_sessions", None)
      if terminate_fn is not None:
        on_progress = kwargs.get("on_progress")
        is_cancelled = kwargs.get("is_cancelled")
        try:
          # Cek signature terminate_sessions (bisa tuple atau bool)
          term_res = terminate_fn(
              alive_sessions,
              on_progress=on_progress,
              is_cancelled=is_cancelled,
          )
        except TypeError:
          term_res = terminate_fn(alive_sessions)

        if isinstance(term_res, tuple):
          success, failed_pids, err_msg = term_res
        else:
          success = bool(term_res)
          failed_pids = []
          err_msg = ""

        if is_cancelled and is_cancelled():
          return ApplyResult(
              status=ApplyStatus.CANCELLED,
              code="cancelled",
              user_message="Penantian penghentian sesi dibatalkan oleh pengguna. Tidak ada penulisan.",
          )

        if not success:
          pids_str = ", ".join(str(p) for p in failed_pids) if failed_pids else "agy"
          return ApplyResult(
              status=ApplyStatus.FAILED,
              code="kill_failed",
              user_message=err_msg or f"Gagal menghentikan sesi agy pada PID: {pids_str}.",
              action_suggestion="Jalankan manual: pkill -9 -x agy lalu coba lagi. Tidak ada perubahan yang ditulis.",
          )

      # Deteksi ulang tepat sebelum penulisan untuk menutup race sesi baru yang muncul
      try:
        recheck_sessions = self.process_manager.detect_sessions()
      except Exception as exc:
        return ApplyResult(
            status=ApplyStatus.FAILED,
            code="proc_unreadable",
            user_message="Gagal memverifikasi proses sebelum penulisan: tidak dapat membaca /proc.",
        )

      recheck_alive = [
          s for s in recheck_sessions
          if getattr(s, "is_alive", True) and not getattr(s, "is_zombie", False)
      ]
      if recheck_alive:
        pids_str = ", ".join(str(getattr(s, "pid", s)) for s in recheck_alive)
        return ApplyResult(
            status=ApplyStatus.FAILED,
            code="new_sessions_detected",
            user_message=f"Sesi agy baru terdeteksi (PID: {pids_str}) sebelum penulisan.",
            action_suggestion="Tutup sesi agy dan coba lagi. Tidak ada perubahan yang ditulis.",
        )

    # 2. Snapshot backup keyring & file ~/.gemini sebelum penulisan
    email = str(plan.account_snapshot.get("email", "")).strip()
    account_id = plan.account_snapshot.get("id")
    token_data = plan.validated_token or {}
    write_gemini_files = kwargs.get("write_gemini_files", True)

    # Baca payload keyring lama jika ada
    old_keyring_payload = None
    try:
      old_keyring_payload = self.keyring.read(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception as kr_read_exc:
      logger.warning("Gagal membaca keyring saat snapshot: %s", kr_read_exc)

    gemini_dir = getattr(self.gemini_files, "gemini_dir", None)
    backup_dir = None
    backup_location = ""
    try:
      backup_dir = create_cli_backup(
          keyring_payload=old_keyring_payload,
          gemini_dir=gemini_dir,
          email=email,
          clock_now=self.clock.now(),
      )
      backup_location = str(backup_dir)
    except Exception as bkp_exc:
      logger.warning("Gagal membuat snapshot CLI backup: %s", bkp_exc)

    # Fungsi pembantu untuk rollback bila ada langkah berikutnya yang gagal
    def _perform_rollback():
      if backup_dir:
        try:
          rollback_from_backup(
              backup_dir=backup_dir,
              keyring_port=self.keyring,
              gemini_dir=gemini_dir,
              opencode_file_path=None,
          )
        except Exception as rb_exc:
          logger.error("Gagal melakukan rollback otomatis CLI: %s", rb_exc)

    # 3. Bentuk dan tulis payload keyring
    existing_auth_method = "consumer"
    existing_writer_id = None
    if old_keyring_payload:
      try:
        old_data = json.loads(old_keyring_payload.decode("utf-8"))
        if isinstance(old_data, dict):
          if "auth_method" in old_data:
            existing_auth_method = old_data["auth_method"]
          if "writer_id" in old_data:
            existing_writer_id = old_data["writer_id"]
      except Exception:
        pass

    if not existing_writer_id:
      existing_writer_id = secrets.token_urlsafe(32)

    now_wall = self.clock.now()
    expiry_rfc3339 = _format_rfc3339_with_skew(now_wall, 30.0)
    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    token_type = token_data.get("token_type", "Bearer")
    expires_in = token_data.get("expires_in", 3600)
    id_token = token_data.get("id_token")

    keyring_payload_dict = {
        "token": {
            "access_token": access_token,
            "token_type": token_type,
            "refresh_token": refresh_token,
            "expiry": expiry_rfc3339,
            "expires_in": expires_in,
        },
        "auth_method": existing_auth_method,
        "id_token_email": email,
        "writer_id": existing_writer_id,
    }
    keyring_bytes = json.dumps(keyring_payload_dict, indent=2).encode("utf-8")

    try:
      self.keyring.write(KEYRING_SERVICE, KEYRING_USERNAME, keyring_bytes)
    except Exception as kw_exc:
      logger.exception("Gagal menulis keyring gemini/antigravity")
      _perform_rollback()
      return ApplyResult(
          status=ApplyStatus.FAILED,
          code="keyring_write_failed",
          user_message=f"Gagal menulis kredensial ke keyring: {kw_exc}. Perubahan telah di-rollback.",
          action_suggestion="Periksa status Secret Service / Keyring Linux.",
          backup_location=backup_location,
      )

    # 4. Tulis file ~/.gemini (bila write_gemini_files aktif)
    if write_gemini_files:
      # 4a. oauth_creds.json
      expiry_date_ms = int((now_wall + expires_in) * 1000)
      oauth_creds_dict = {
          "access_token": access_token,
          "scope": "https://www.googleapis.com/auth/cloud-platform https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile openid",
          "token_type": token_type,
          "id_token": id_token,
          "expiry_date": expiry_date_ms,
          "refresh_token": refresh_token,
      }
      try:
        self.gemini_files.write_oauth_creds(oauth_creds_dict)
      except Exception as ow_exc:
        logger.exception("Gagal menulis ~/.gemini/oauth_creds.json")
        _perform_rollback()
        return ApplyResult(
            status=ApplyStatus.FAILED,
            code="gemini_write_failed",
            user_message=f"Gagal menulis ~/.gemini/oauth_creds.json: {ow_exc}. Perubahan telah di-rollback.",
            action_suggestion="Periksa izin penulisan folder ~/.gemini.",
            backup_location=backup_location,
        )

      # 4b. google_accounts.json
      old_accounts_data = None
      try:
        old_accounts_data = self.gemini_files.read_google_accounts()
      except Exception:
        pass

      old_emails_list: List[str] = []
      old_active_email: Optional[str] = None
      if isinstance(old_accounts_data, dict):
        old_active_email = old_accounts_data.get("active")
        if isinstance(old_accounts_data.get("old"), list):
          old_emails_list.extend(str(e) for e in old_accounts_data["old"] if e)

      if old_active_email and old_active_email not in old_emails_list:
        old_emails_list.append(old_active_email)

      # Gabungan unik, tidak termasuk email baru
      clean_email = email.strip()
      unique_old: List[str] = []
      for e in old_emails_list:
        clean_e = e.strip()
        if clean_e.lower() != clean_email.lower() and clean_e not in unique_old:
          unique_old.append(clean_e)

      google_accounts_dict = {
          "active": clean_email,
          "old": unique_old,
      }
      try:
        self.gemini_files.write_google_accounts(google_accounts_dict)
      except Exception as gw_exc:
        logger.exception("Gagal menulis ~/.gemini/google_accounts.json")
        _perform_rollback()
        return ApplyResult(
            status=ApplyStatus.FAILED,
            code="gemini_write_failed",
            user_message=f"Gagal menulis ~/.gemini/google_accounts.json: {gw_exc}. Perubahan telah di-rollback.",
            action_suggestion="Periksa izin penulisan folder ~/.gemini.",
            backup_location=backup_location,
        )

    # 5. Verifikasi: baca ulang keyring dan file
    try:
      verified_kr = self.keyring.read(KEYRING_SERVICE, KEYRING_USERNAME)
      if not verified_kr:
        raise ValueError("Keyring kosong setelah penulisan")
      v_data = json.loads(verified_kr.decode("utf-8"))
      v_token = v_data.get("token", {})
      v_email = v_data.get("id_token_email")
      v_rt = v_token.get("refresh_token")
      if not v_email or v_email.strip().lower() != email.lower():
        raise ValueError(f"Email pada keyring ({v_email}) tidak cocok dengan {email}")
      if not v_rt or v_rt != refresh_token:
        raise ValueError("Refresh token pada keyring tidak cocok")

      if write_gemini_files:
        v_creds = self.gemini_files.read_oauth_creds()
        if not v_creds or v_creds.get("refresh_token") != refresh_token:
          raise ValueError("File oauth_creds.json tidak sinkron dengan refresh token baru")
        v_accs = self.gemini_files.read_google_accounts()
        if not v_accs or str(v_accs.get("active", "")).strip().lower() != email.lower():
          raise ValueError("File google_accounts.json tidak menunjuk email aktif yang sesuai")
    except Exception as vf_exc:
      logger.exception("Verifikasi hasil Apply CLI gagal")
      _perform_rollback()
      return ApplyResult(
          status=ApplyStatus.FAILED,
          code="verification_failed",
          user_message=f"Verifikasi pembacaan ulang gagal: {vf_exc}. Perubahan telah di-rollback.",
          action_suggestion="Coba jalankan Apply kembali atau periksa integritas keyring/file.",
          backup_location=backup_location,
      )

    # 6. Pembaruan refresh token hasil rotasi di DB (bila berbeda dari snapshot)
    orig_rt = (plan.account_snapshot.get("refresh_token") or "").strip()
    if account_id and refresh_token and refresh_token != orig_rt:
      try:
        pwd = kwargs.get("password", "")
        self.account_storage.update_refresh_token(account_id, refresh_token, password=pwd)
      except Exception as rot_exc:
        logger.warning("Gagal memperbarui refresh token hasil rotasi di database: %s", rot_exc)

    # 7. Tandai DB: applied_target='antigravity_cli' & last_applied_at=epoch detik
    applied_time = int(self.clock.now())
    try:
      if account_id:
        self.account_storage.mark_applied(account_id, TARGET_ANTIGRAVITY_CLI, applied_at=applied_time)
    except Exception as db_exc:
      logger.warning("Gagal menandai applied CLI di database: %s", db_exc)
      _perform_rollback()
      return ApplyResult(
          status=ApplyStatus.FAILED,
          code="db_mark_failed",
          user_message=f"Gagal memperbarui status di database: {db_exc}. Perubahan telah di-rollback.",
          action_suggestion="Periksa koneksi database.",
          backup_location=backup_location,
      )

    # 8. Bersihkan backup lama (retensi 30)
    cleanup_old_backups(max_keep=30)

    time_str = datetime.datetime.fromtimestamp(applied_time).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    return ApplyResult(
        status=ApplyStatus.SUCCESS,
        user_message=f"Akun {email} berhasil diterapkan ke Antigravity CLI pada {time_str}.\nLokasi backup: {backup_location}",
        email=email,
        backup_location=backup_location,
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
      if backup_dir:
        try:
          rollback_from_backup(
              backup_dir=backup_dir,
              keyring_port=self.keyring,
              gemini_dir=None,
              opencode_file_path=file_path,
          )
        except Exception as rb_exc:
          logger.error("Gagal melakukan rollback otomatis: %s", rb_exc)
      return ApplyResult(
          status=ApplyStatus.FAILED,
          code="write_failed",
          user_message=f"Gagal menulis file OpenCode: {exc}. Rollback otomatis telah dijalankan.",
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
      if backup_dir:
        try:
          rollback_from_backup(
              backup_dir=backup_dir,
              keyring_port=self.keyring,
              gemini_dir=None,
              opencode_file_path=file_path,
          )
        except Exception as rb_exc:
          logger.error("Gagal rollback otomatis setelah DB gagal: %s", rb_exc)
      return ApplyResult(
          status=ApplyStatus.FAILED,
          code="db_mark_failed",
          user_message=f"Gagal memperbarui database: {db_exc}. Perubahan telah di-rollback.",
          action_suggestion="Periksa koneksi database.",
          backup_location=backup_location,
      )

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

      # Baca ringkasan sesi agy untuk tooltip
      sessions_summary = None
      try:
        if hasattr(self.process_manager, "summarize_sessions"):
          sessions_summary = self.process_manager.summarize_sessions()
        elif hasattr(self.process_manager, "detect_sessions"):
          sessions = self.process_manager.detect_sessions()
          alive_cnt = sum(1 for s in sessions if getattr(s, "is_alive", True) and not getattr(s, "is_zombie", False))
          stopped_cnt = sum(1 for s in sessions if getattr(s, "is_stopped", False))
          zombie_cnt = sum(1 for s in sessions if getattr(s, "is_zombie", False))
          sessions_summary = {"alive": alive_cnt, "stopped": stopped_cnt, "zombie": zombie_cnt}
      except Exception as p_exc:
        logger.debug("Tidak dapat membaca ringkasan sesi agy: %s", p_exc)

      # Baca payload keyring
      try:
        kr_bytes = self.keyring.read(KEYRING_SERVICE, KEYRING_USERNAME)
      except Exception as kr_exc:
        logger.debug("Error saat membaca keyring untuk status CLI: %s", kr_exc)
        return TargetStatus(
            target=TARGET_ANTIGRAVITY_CLI,
            condition=TargetCondition.ERROR,
            message=f"Kesalahan membaca keyring: {kr_exc}",
            sessions_summary=sessions_summary,
            error=str(kr_exc),
        )

      if not kr_bytes:
        return TargetStatus(
            target=TARGET_ANTIGRAVITY_CLI,
            email=None,
            condition=TargetCondition.NONE,
            message="Belum login ke Antigravity CLI.",
            sessions_summary=sessions_summary,
        )

      try:
        kr_data = json.loads(kr_bytes.decode("utf-8"))
      except Exception as json_exc:
        return TargetStatus(
            target=TARGET_ANTIGRAVITY_CLI,
            email=None,
            condition=TargetCondition.ERROR,
            message=f"Payload keyring tidak valid: {json_exc}",
            sessions_summary=sessions_summary,
            error=str(json_exc),
        )

      if not isinstance(kr_data, dict):
        return TargetStatus(
            target=TARGET_ANTIGRAVITY_CLI,
            email=None,
            condition=TargetCondition.NONE,
            message="Belum login ke Antigravity CLI.",
            sessions_summary=sessions_summary,
        )

      # Ekstrak email aktif dari payload keyring
      keyring_email = kr_data.get("id_token_email")
      if not keyring_email and isinstance(kr_data.get("token"), dict):
        # Fallback decode id_token jika ada
        id_token = kr_data["token"].get("id_token")
        if id_token:
          keyring_email = _decode_id_token_email(id_token)

      if not keyring_email or not str(keyring_email).strip():
        return TargetStatus(
            target=TARGET_ANTIGRAVITY_CLI,
            email=None,
            condition=TargetCondition.NONE,
            message="Payload keyring tidak memiliki email aktif.",
            sessions_summary=sessions_summary,
        )

      keyring_email = str(keyring_email).strip()

      # Periksa sinkronisasi dengan ~/.gemini (drift check)
      # Status tetap menampilkan email keyring sebagai Active Account
      gemini_email = None
      if hasattr(self.gemini_files, "read_google_accounts"):
        try:
          g_accs = self.gemini_files.read_google_accounts()
          if isinstance(g_accs, dict) and g_accs.get("active"):
            gemini_email = str(g_accs["active"]).strip()
        except Exception as g_exc:
          logger.debug("Tidak dapat membaca google_accounts.json: %s", g_exc)

      is_drift = False
      if gemini_email and gemini_email.lower() != keyring_email.lower():
        is_drift = True

      if is_drift:
        return TargetStatus(
            target=TARGET_ANTIGRAVITY_CLI,
            email=keyring_email,
            condition=TargetCondition.DRIFT_GEMINI,
            message=f"Drift terdeteksi: Keyring ({keyring_email}) berbeda dengan ~/.gemini ({gemini_email}).",
            sessions_summary=sessions_summary,
        )

      # Periksa apakah email tercatat di database
      exists_in_db = False
      try:
        exists_in_db = self.account_storage.account_exists(keyring_email)
      except Exception as db_exc:
        logger.warning("Gagal memeriksa akun CLI di storage: %s", db_exc)

      if exists_in_db:
        return TargetStatus(
            target=TARGET_ANTIGRAVITY_CLI,
            email=keyring_email,
            condition=TargetCondition.ACTIVE,
            message=f"Aktif: {keyring_email}",
            sessions_summary=sessions_summary,
        )
      else:
        return TargetStatus(
            target=TARGET_ANTIGRAVITY_CLI,
            email=keyring_email,
            condition=TargetCondition.UNRECORDED,
            message="Akun aktif di Keyring tidak tercatat di database.",
            sessions_summary=sessions_summary,
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
    latest = get_latest_backup()
    if not latest:
      return RestoreResult(
          status=ApplyStatus.SUCCESS,
          message="Tidak ada backup yang ditemukan untuk dipulihkan.",
          restored_target=None,
          restored_email=None,
      )

    backup_dir, meta = latest
    target = meta.get("target")
    email = meta.get("email")

    # Dapatkan path opencode dan gemini
    opencode_path = None
    if hasattr(self.opencode_file, "get_file_path"):
      opencode_path = self.opencode_file.get_file_path()
    elif hasattr(self.opencode_file, "_get_file_path"):
      opencode_path = self.opencode_file._get_file_path()

    gemini_dir = getattr(self.gemini_files, "gemini_dir", None)
    if gemini_dir is None:
      gemini_dir = getattr(self, "gemini_dir", None)

    try:
      rollback_from_backup(
          backup_dir=backup_dir,
          keyring_port=self.keyring,
          gemini_dir=gemini_dir,
          opencode_file_path=opencode_path,
      )
    except Exception as exc:
      logger.exception("Gagal memulihkan backup dari %s", backup_dir)
      return RestoreResult(
          status=ApplyStatus.FAILED,
          message=f"Gagal memulihkan backup: {exc}",
          restored_target=target,
          restored_email=email,
          error=str(exc),
      )

    target_name = "OpenCode" if target == TARGET_OPENCODE else "Antigravity CLI"
    return RestoreResult(
        status=ApplyStatus.SUCCESS,
        message=f"Berhasil memulihkan backup terakhir untuk {email} pada target {target_name}.",
        restored_target=target,
        restored_email=email,
    )
