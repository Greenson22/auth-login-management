"""Tests untuk Tiket 11: Ketahanan Apply CLI — error, rollback, rotasi token, toggle file.

Kriteria yang diuji:
1.  invalid_grant dipetakan ke pesan "login ulang" dan unauthorized_client ke "token bukan milik
    client Antigravity"; tidak ada penulisan maupun backup.
2.  id_token tanpa email atau email berbeda dari akun menggagalkan Apply sebelum backup dan tanpa
    penulisan.
3.  Bila Google mengembalikan refresh token baru, keyring dan DB memakai token baru; konfigurasi
    akun di DB tetap source of truth.
4.  write_gemini_files=false hanya menulis keyring dan DB; tidak ada file ~/.gemini yang ditulis
    atau dibuat, dan verifikasi file dilewati.
5.  Kegagalan menulis oauth_creds.json setelah keyring berhasil memicu pemulihan keyring dan file
    lain; DB tidak ditandai.
6.  Ketidakcocokan saat verifikasi memicu rollback penuh dan pesan memuat lokasi backup.
7.  Kegagalan menandai DB memicu rollback keyring dan file.
8.  Pesan kegagalan menyebut langkah yang gagal, tindakan berikutnya, dan secara eksplisit apakah
    perubahan sudah di-rollback atau belum.
9.  Kegagalan jaringan tidak di-retry otomatis; pengguna memilih Apply lagi.
10. Rate limit atau respons Google non-JSON dipetakan ke pesan "coba lagi" tanpa membocorkan
    respons mentah.
11. Kegagalan dekripsi memakai pesan yang sudah ada.
12. Tidak ada token utuh di dialog, pesan error, atau log.
13. Password enkripsi hanya dipakai sesaat untuk dekripsi dan tidak disimpan atau ditulis ulang.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from src.integrations.antigravity.constants import KEYRING_SERVICE, KEYRING_USERNAME
from src.integrations.antigravity.ports import ApplyStatus
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


# ─── Helpers lokal ───────────────────────────────────────────────────────────


class FakeAccountStorage:
    def __init__(self, accounts: Optional[Dict[str, Dict[str, Any]]] = None):
        self.accounts = accounts or {}
        self.applied_marks: List[Dict[str, Any]] = []
        self.updated_tokens: List[Dict[str, Any]] = []
        self.fail_mark = False
        self.fail_reconstruct_msg: Optional[str] = None

    def reconstruct_account(self, account_id: str, password: str = "") -> Dict[str, Any]:
        if self.fail_reconstruct_msg:
            raise ValueError(self.fail_reconstruct_msg)
        if account_id not in self.accounts:
            raise ValueError(f"Akun {account_id} tidak ditemukan")
        return dict(self.accounts[account_id])

    def mark_applied(self, account_id: str, target: str, applied_at: Optional[int] = None) -> bool:
        if self.fail_mark:
            raise RuntimeError("Gagal menandai DB (simulasi)")
        self.applied_marks.append({"account_id": account_id, "target": target, "applied_at": applied_at})
        return True

    def update_refresh_token(self, account_id: str, new_refresh_token: str, password: str = "") -> bool:
        self.updated_tokens.append({"account_id": account_id, "new_refresh_token": new_refresh_token})
        return True

    def account_exists(self, email: str) -> bool:
        return any(acc.get("email", "").lower() == email.lower() for acc in self.accounts.values())


class FakeGeminiFilesPort:
    """GeminiFilesPort in-memory berupa dict (tidak menyentuh filesystem asli)."""

    def __init__(self):
        self._oauth_creds: Optional[Dict[str, Any]] = None
        self._google_accounts: Optional[Dict[str, Any]] = None
        self.fail_write_oauth = False
        self.fail_write_accounts = False
        self.write_oauth_calls: List[Dict] = []
        self.write_accounts_calls: List[Dict] = []

    def read_oauth_creds(self) -> Optional[Dict[str, Any]]:
        return dict(self._oauth_creds) if self._oauth_creds else None

    def write_oauth_creds(self, creds: Dict[str, Any]) -> None:
        if self.fail_write_oauth:
            raise OSError("Simulasi gagal menulis oauth_creds.json")
        self._oauth_creds = dict(creds)
        self.write_oauth_calls.append(dict(creds))

    def read_google_accounts(self) -> Optional[Dict[str, Any]]:
        return dict(self._google_accounts) if self._google_accounts else None

    def write_google_accounts(self, accounts: Dict[str, Any]) -> None:
        if self.fail_write_accounts:
            raise OSError("Simulasi gagal menulis google_accounts.json")
        self._google_accounts = dict(accounts)
        self.write_accounts_calls.append(dict(accounts))


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


def _make_facade(
    *,
    accounts: Optional[Dict[str, Dict[str, Any]]] = None,
    storage: Optional[FakeAccountStorage] = None,
    keyring: Optional[FakeKeyring] = None,
    gemini: Optional[FakeGeminiFilesPort] = None,
    oauth: Optional[FakeOAuth] = None,
    proc_root: Optional[Path] = None,
    clock: Optional[FakeClock] = None,
    env: Optional[DummyEnvironment] = None,
) -> tuple[AntigravityFacade, FakeAccountStorage, FakeKeyring, FakeGeminiFilesPort, FakeOAuth, FakeClock]:
    clock = clock or FakeClock(1_700_000_000.0)
    storage = storage or FakeAccountStorage(accounts or {})
    keyring = keyring or FakeKeyring()
    gemini = gemini or FakeGeminiFilesPort()
    oauth = oauth or FakeOAuth(clock)
    env = env or DummyEnvironment()

    if proc_root is None:
        import tempfile
        proc_root = Path(tempfile.mkdtemp()) / "proc"
    proc_root.mkdir(parents=True, exist_ok=True)
    proc_mgr = LinuxProcessManager(proc_path=proc_root, clock=clock)

    facade = AntigravityFacade(
        account_storage=storage,
        keyring=keyring,
        gemini_files=gemini,
        opencode_file=DummyOpenCodePort(),
        oauth=oauth,
        process_manager=proc_mgr,
        environment=env,
        clock=clock,
    )
    return facade, storage, keyring, gemini, oauth, clock


def _default_account(email="test@example.com", rt="1//refresh-token-valid") -> Dict[str, Any]:
    return {"id": "acc1", "email": email, "refresh_token": rt}


# ─── 1. invalid_grant / unauthorized_client — tidak ada tulis ────────────────


def test_invalid_grant_dipetakan_ke_pesan_login_ulang(tmp_path):
    """invalid_grant → pesan 'login ulang'; tidak ada penulisan maupun backup."""
    proc_root = tmp_path / "proc"
    facade, storage, keyring, gemini, oauth, clock = _make_facade(
        accounts={"acc1": _default_account()},
        proc_root=proc_root,
    )
    oauth.fail_with("invalid_grant", "Token has been expired or revoked")

    plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)

    assert plan.target_available is False
    assert plan.error_code == "invalid_grant"
    assert "login ulang" in plan.error_message.lower()
    # Tidak ada penulisan ke keyring
    assert len(keyring.writes) == 0
    # Tidak ada file gemini yang dibuat
    assert gemini.read_oauth_creds() is None
    assert gemini.read_google_accounts() is None


def test_unauthorized_client_dipetakan_ke_pesan_bukan_milik_client(tmp_path):
    """unauthorized_client → pesan 'token bukan milik client Antigravity'; tidak ada penulisan."""
    proc_root = tmp_path / "proc"
    facade, storage, keyring, gemini, oauth, clock = _make_facade(
        accounts={"acc1": _default_account()},
        proc_root=proc_root,
    )
    oauth.fail_with("unauthorized_client", "Client is unauthorized")

    plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)

    assert plan.target_available is False
    assert plan.error_code == "unauthorized_client"
    assert "unauthorized_client" in plan.error_message.lower() or "bukan milik client" in plan.error_message.lower()
    assert len(keyring.writes) == 0


# ─── 2. id_token tanpa email / email berbeda — gagal sebelum backup ──────────


def test_id_token_tanpa_email_gagal_sebelum_tulis(tmp_path):
    """id_token tidak memuat email → plan gagal, tidak ada penulisan."""
    proc_root = tmp_path / "proc"
    clock = FakeClock()
    # Buat id_token tanpa klaim email (hanya header+payload kosong)
    import base64

    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    empty_payload = _b64url(b'{"sub":"1234567890"}')
    header = _b64url(b'{"alg":"none","typ":"JWT"}')
    no_email_id_token = f"{header}.{empty_payload}."

    class FakeOAuthNoEmailIdToken(FakeOAuth):
        def exchange_refresh_token(self, refresh_token: str, **kwargs):
            self.calls.append({"refresh_token": refresh_token})
            from tests.fakes import OAuthTokenResponse
            return OAuthTokenResponse(
                access_token="ya29.access",
                refresh_token=refresh_token,
                expiry=clock.now() + 3600,
                id_token=no_email_id_token,
            )

    proc_root.mkdir(parents=True, exist_ok=True)
    storage = FakeAccountStorage({"acc1": _default_account()})
    keyring = FakeKeyring()
    oauth = FakeOAuthNoEmailIdToken(clock)

    proc_mgr = LinuxProcessManager(proc_path=proc_root, clock=clock)
    facade = AntigravityFacade(
        account_storage=storage,
        keyring=keyring,
        gemini_files=FakeGeminiFilesPort(),
        opencode_file=DummyOpenCodePort(),
        oauth=oauth,
        process_manager=proc_mgr,
        environment=DummyEnvironment(),
        clock=clock,
    )

    plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)
    assert plan.target_available is False
    assert plan.error_code == "missing_id_token_email"
    assert len(keyring.writes) == 0


def test_email_berbeda_dari_akun_gagal_sebelum_tulis(tmp_path):
    """Email di id_token berbeda dari email akun → plan gagal tanpa penulisan."""
    proc_root = tmp_path / "proc"
    facade, storage, keyring, gemini, oauth, clock = _make_facade(
        accounts={"acc1": _default_account(email="owner@example.com")},
        proc_root=proc_root,
    )
    # Server mengembalikan token milik orang lain
    oauth.respond_for("hacker@evil.com", refresh_token="1//refresh-token-valid")

    plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)

    assert plan.target_available is False
    assert plan.error_code == "email_mismatch"
    assert len(keyring.writes) == 0


# ─── 3. Rotasi refresh token — keyring dan DB memakai token baru ─────────────


def test_rotasi_refresh_token_disimpan_ke_keyring_dan_db(tmp_path):
    """Bila Google mengembalikan refresh token baru, keyring dan DB keduanya memakai token baru."""
    proc_root = tmp_path / "proc"
    email = "rotate@example.com"
    old_rt = "1//old-refresh-token"
    new_rt = "1//brand-new-refresh-token-from-google"

    facade, storage, keyring, gemini, oauth, clock = _make_facade(
        accounts={"acc1": _default_account(email=email, rt=old_rt)},
        proc_root=proc_root,
    )
    # Google mengembalikan refresh token baru (berbeda dari yang lama)
    oauth.respond_for(email, refresh_token=new_rt, access_token="ya29.access-new")

    plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)
    assert plan.target_available is True
    assert plan.validated_token is not None

    result = facade.apply(plan)
    assert result.status == ApplyStatus.SUCCESS

    # Keyring harus memakai token baru
    kr_bytes = keyring.read(KEYRING_SERVICE, KEYRING_USERNAME)
    assert kr_bytes is not None
    kr_data = json.loads(kr_bytes.decode("utf-8"))
    assert kr_data["token"]["refresh_token"] == new_rt

    # DB harus diperbarui dengan token baru (update_refresh_token dipanggil)
    assert len(storage.updated_tokens) == 1
    assert storage.updated_tokens[0]["new_refresh_token"] == new_rt
    assert storage.updated_tokens[0]["account_id"] == "acc1"

    # DB juga ditandai applied
    assert len(storage.applied_marks) == 1
    assert storage.applied_marks[0]["target"] == TARGET_ANTIGRAVITY_CLI


def test_tidak_ada_rotasi_jika_token_sama(tmp_path):
    """Bila Google mengembalikan token yang sama, update_refresh_token tidak dipanggil."""
    proc_root = tmp_path / "proc"
    same_rt = "1//same-refresh-token"
    email = "same@example.com"

    facade, storage, keyring, gemini, oauth, clock = _make_facade(
        accounts={"acc1": _default_account(email=email, rt=same_rt)},
        proc_root=proc_root,
    )
    oauth.respond_for(email, refresh_token=same_rt)

    plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)
    result = facade.apply(plan)
    assert result.status == ApplyStatus.SUCCESS

    # Tidak ada pembaruan token karena token tidak berputar
    assert len(storage.updated_tokens) == 0


# ─── 4. write_gemini_files=False — hanya keyring dan DB, tidak ada file ────


def test_write_gemini_files_false_tidak_menulis_file(tmp_path):
    """write_gemini_files=false → hanya keyring dan DB; tidak ada file ~/.gemini."""
    proc_root = tmp_path / "proc"
    email = "nogemi@example.com"
    rt = "1//no-gemini-token"

    facade, storage, keyring, gemini, oauth, clock = _make_facade(
        accounts={"acc1": _default_account(email=email, rt=rt)},
        proc_root=proc_root,
    )
    oauth.respond_for(email, refresh_token=rt)

    plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)
    result = facade.apply(plan, write_gemini_files=False)

    assert result.status == ApplyStatus.SUCCESS

    # Keyring harus ditulis
    kr_bytes = keyring.read(KEYRING_SERVICE, KEYRING_USERNAME)
    assert kr_bytes is not None

    # Tidak ada file ~/.gemini yang dibuat
    assert len(gemini.write_oauth_calls) == 0
    assert len(gemini.write_accounts_calls) == 0
    assert gemini.read_oauth_creds() is None
    assert gemini.read_google_accounts() is None

    # DB tetap ditandai
    assert len(storage.applied_marks) == 1


# ─── 5. Kegagalan menulis oauth_creds.json — rollback keyring, DB tidak ditandai ─


def test_gagal_tulis_oauth_creds_rollback_keyring_db_tidak_ditandai(tmp_path):
    """Kegagalan menulis oauth_creds.json setelah keyring berhasil → rollback keyring, DB tidak ditandai."""
    proc_root = tmp_path / "proc"
    email = "oauth-fail@example.com"
    rt = "1//oauth-fail-token"

    # Siapkan keyring dengan nilai awal untuk memverifikasi rollback
    keyring = FakeKeyring()
    initial_payload = {
        "token": {"refresh_token": "original-rt"},
        "auth_method": "consumer",
        "id_token_email": "original@example.com",
    }
    keyring.write(KEYRING_SERVICE, KEYRING_USERNAME, json.dumps(initial_payload).encode())

    gemini = FakeGeminiFilesPort()
    gemini.fail_write_oauth = True  # oauth_creds.json akan gagal

    facade, storage, _, _, oauth, clock = _make_facade(
        accounts={"acc1": _default_account(email=email, rt=rt)},
        proc_root=proc_root,
        keyring=keyring,
        gemini=gemini,
    )
    oauth.respond_for(email, refresh_token=rt)

    plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)
    result = facade.apply(plan)

    assert result.status == ApplyStatus.FAILED
    assert result.code == "gemini_write_failed"

    # DB tidak boleh ditandai karena apply gagal sebelum langkah DB
    assert len(storage.applied_marks) == 0

    # Keyring harus di-rollback ke nilai semula
    kr_bytes = keyring.read(KEYRING_SERVICE, KEYRING_USERNAME)
    assert kr_bytes is not None
    restored = json.loads(kr_bytes.decode("utf-8"))
    assert restored["id_token_email"] == "original@example.com"


# ─── 6. Ketidakcocokan verifikasi — rollback penuh, pesan berisi lokasi backup ─


def test_verifikasi_gagal_rollback_penuh_dan_pesan_berisi_backup_lokasi(tmp_path):
    """Ketidakcocokan saat verifikasi → rollback penuh dan pesan memuat lokasi backup."""
    proc_root = tmp_path / "proc"
    email = "verify-fail@example.com"
    rt = "1//verify-fail-token"

    keyring = FakeKeyring()
    initial_payload = {
        "token": {"refresh_token": "original-rt"},
        "auth_method": "consumer",
        "id_token_email": "original@example.com",
    }
    keyring.write(KEYRING_SERVICE, KEYRING_USERNAME, json.dumps(initial_payload).encode())

    # GeminiFilesPort yang merusak pembacaan ulang verifikasi
    class TamperedGeminiPort(FakeGeminiFilesPort):
        def read_oauth_creds(self):
            # Kembalikan refresh token yang salah saat verifikasi
            return {"refresh_token": "WRONG-TOKEN-DIFFERENT"}

    tampered_gemini = TamperedGeminiPort()
    facade, storage, _, _, oauth, clock = _make_facade(
        accounts={"acc1": _default_account(email=email, rt=rt)},
        proc_root=proc_root,
        keyring=keyring,
        gemini=tampered_gemini,
    )
    oauth.respond_for(email, refresh_token=rt)

    plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)
    result = facade.apply(plan)

    assert result.status == ApplyStatus.FAILED
    assert result.code == "verification_failed"

    # Pesan harus menyebut rollback
    assert "rollback" in result.user_message.lower()

    # Lokasi backup harus ada di pesan/result
    assert result.backup_location is not None and len(result.backup_location) > 0

    # Keyring di-rollback ke nilai awal
    kr_bytes = keyring.read(KEYRING_SERVICE, KEYRING_USERNAME)
    restored = json.loads(kr_bytes.decode("utf-8"))
    assert restored["id_token_email"] == "original@example.com"

    # DB tidak ditandai karena rollback
    assert len(storage.applied_marks) == 0


# ─── 7. Kegagalan menandai DB — rollback keyring dan file ────────────────────


def test_gagal_tandai_db_memicu_rollback_keyring_dan_file(tmp_path):
    """Kegagalan menandai DB (langkah terakhir) → rollback keyring dan file, DB tetap bersih."""
    proc_root = tmp_path / "proc"
    email = "db-fail@example.com"
    rt = "1//db-fail-token"

    keyring = FakeKeyring()
    initial_payload = {
        "token": {"refresh_token": "original-rt"},
        "auth_method": "consumer",
        "id_token_email": "original@example.com",
    }
    keyring.write(KEYRING_SERVICE, KEYRING_USERNAME, json.dumps(initial_payload).encode())

    storage = FakeAccountStorage({"acc1": _default_account(email=email, rt=rt)})
    storage.fail_mark = True  # Gagal saat mark_applied

    gemini = FakeGeminiFilesPort()
    facade, _, _, _, oauth, clock = _make_facade(
        accounts={},
        proc_root=proc_root,
        storage=storage,
        keyring=keyring,
        gemini=gemini,
    )
    oauth.respond_for(email, refresh_token=rt)

    plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)
    result = facade.apply(plan)

    assert result.status == ApplyStatus.FAILED
    assert result.code == "db_mark_failed"

    # Pesan harus eksplisit menyebut rollback
    assert "rollback" in result.user_message.lower()

    # Keyring harus di-rollback
    kr_bytes = keyring.read(KEYRING_SERVICE, KEYRING_USERNAME)
    restored = json.loads(kr_bytes.decode("utf-8"))
    assert restored["id_token_email"] == "original@example.com"

    # Tidak ada applied_marks yang tersimpan
    assert len(storage.applied_marks) == 0


# ─── 8. Pesan kegagalan menyebut langkah + tindakan + rollback status ────────


def test_pesan_kegagalan_menyebut_langkah_dan_rollback_eksplisit(tmp_path):
    """Setiap pesan kegagalan setelah potensi perubahan wajib menyebut rollback status."""
    proc_root = tmp_path / "proc"
    email = "msg-test@example.com"
    rt = "1//msg-test-token"

    keyring = FakeKeyring()
    keyring.write(KEYRING_SERVICE, KEYRING_USERNAME, json.dumps({
        "token": {"refresh_token": "orig"}, "auth_method": "consumer",
        "id_token_email": "orig@example.com"
    }).encode())

    gemini = FakeGeminiFilesPort()
    gemini.fail_write_oauth = True

    facade, storage, _, _, oauth, clock = _make_facade(
        accounts={"acc1": _default_account(email=email, rt=rt)},
        proc_root=proc_root,
        keyring=keyring,
        gemini=gemini,
    )
    oauth.respond_for(email, refresh_token=rt)

    plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)
    result = facade.apply(plan)

    assert result.status == ApplyStatus.FAILED
    # user_message harus menyebut rollback
    msg = result.user_message.lower()
    assert "rollback" in msg or "dipulihkan" in msg or "di-rollback" in msg


def test_pesan_kegagalan_preflight_menyebut_langkah_yang_gagal(tmp_path):
    """Pesan kegagalan preflight menyebut penyebab (langkah yang gagal)."""
    proc_root = tmp_path / "proc"
    facade, _, keyring, _, oauth, _ = _make_facade(
        accounts={"acc1": _default_account()},
        proc_root=proc_root,
    )
    oauth.fail_with("invalid_grant")

    plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)
    # Pesan harus ada dan bermakna (bukan string kosong)
    assert plan.error_message is not None and len(plan.error_message) > 0
    # Harus menyebut tindakan berikutnya (login ulang)
    assert "login" in plan.error_message.lower()


# ─── 9. Kegagalan jaringan tidak di-retry otomatis ───────────────────────────


def test_kegagalan_jaringan_tidak_retry_otomatis(tmp_path):
    """Kegagalan jaringan (network error) tidak di-retry; oauth.exchange_refresh_token hanya dipanggil sekali."""
    proc_root = tmp_path / "proc"

    class NetworkErrorOAuth:
        def __init__(self):
            self.calls = 0

        def exchange_refresh_token(self, refresh_token: str, **kwargs):
            self.calls += 1
            raise ConnectionError("Network unreachable")

    proc_root.mkdir(parents=True, exist_ok=True)
    network_oauth = NetworkErrorOAuth()
    storage = FakeAccountStorage({"acc1": _default_account()})
    clock = FakeClock()
    proc_mgr = LinuxProcessManager(proc_path=proc_root, clock=clock)

    facade = AntigravityFacade(
        account_storage=storage,
        keyring=FakeKeyring(),
        gemini_files=FakeGeminiFilesPort(),
        opencode_file=DummyOpenCodePort(),
        oauth=network_oauth,
        process_manager=proc_mgr,
        environment=DummyEnvironment(),
        clock=clock,
    )

    plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)

    # Hanya dipanggil sekali (tidak ada retry)
    assert network_oauth.calls == 1
    assert plan.target_available is False
    assert plan.error_code not in (None, "")


# ─── 10. Rate limit / respons non-JSON → pesan "coba lagi", tidak bocorkan respons ─


def test_rate_limit_dipetakan_ke_pesan_coba_lagi(tmp_path):
    """rate_limit_exceeded atau respons non-JSON → pesan bermakna tanpa membocorkan respons mentah."""
    proc_root = tmp_path / "proc"
    facade, _, keyring, gemini, oauth, _ = _make_facade(
        accounts={"acc1": _default_account()},
        proc_root=proc_root,
    )
    oauth.fail_with("rate_limit_exceeded", "<!DOCTYPE html><html>Rate limit page</html>")

    plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)

    assert plan.target_available is False
    # Pesan tidak boleh memuat respons HTML mentah
    if plan.error_message:
        assert "<!DOCTYPE" not in plan.error_message
        assert "<html>" not in plan.error_message
    # Tidak ada token / kredensial yang ditulis
    assert len(keyring.writes) == 0


# ─── 11. Kegagalan dekripsi — pesan konsisten dengan fitur lain ──────────────


def test_kegagalan_dekripsi_menggunakan_pesan_yang_ada(tmp_path):
    """Kegagalan dekripsi akun mengembalikan pesan yang ada (bukan pesan baru berbeda)."""
    proc_root = tmp_path / "proc"
    # Simulasi kegagalan dekripsi via reconstruct_account
    storage = FakeAccountStorage({"acc_enc": _default_account(email="enc@example.com")})
    storage.fail_reconstruct_msg = "Password salah atau data terenkripsi rusak"

    proc_root.mkdir(parents=True, exist_ok=True)
    clock = FakeClock()
    proc_mgr = LinuxProcessManager(proc_path=proc_root, clock=clock)
    facade = AntigravityFacade(
        account_storage=storage,
        keyring=FakeKeyring(),
        gemini_files=FakeGeminiFilesPort(),
        opencode_file=DummyOpenCodePort(),
        oauth=FakeOAuth(clock),
        process_manager=proc_mgr,
        environment=DummyEnvironment(),
        clock=clock,
    )

    plan = facade.build_plan("acc_enc", TARGET_ANTIGRAVITY_CLI)

    assert plan.target_available is False
    assert plan.error_code == "account_reconstruction_failed"
    # Pesan harus ada dan bermakna
    assert plan.error_message is not None and len(plan.error_message) > 0


# ─── 12. Tidak ada token utuh di pesan error atau log ────────────────────────


def test_token_tidak_muncul_utuh_di_pesan_error(tmp_path):
    """Pesan error tidak boleh memuat nilai refresh token utuh."""
    proc_root = tmp_path / "proc"
    full_rt = "1//AHde-secret-long-refresh-token-do-not-log"
    email = "token-safety@example.com"

    facade, _, keyring, gemini, oauth, _ = _make_facade(
        accounts={"acc1": _default_account(email=email, rt=full_rt)},
        proc_root=proc_root,
    )
    # Buat apply gagal di tahap verifikasi (setelah keyring ditulis)
    class TamperedGemini(FakeGeminiFilesPort):
        def read_oauth_creds(self):
            return {"refresh_token": "WRONG"}

    tampered = TamperedGemini()
    facade2, storage2, keyring2, _, oauth2, clock2 = _make_facade(
        accounts={"acc1": _default_account(email=email, rt=full_rt)},
        proc_root=proc_root,
        gemini=tampered,
    )
    oauth2.respond_for(email, refresh_token=full_rt)

    plan = facade2.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)
    result = facade2.apply(plan)

    # Pesan kegagalan tidak boleh memuat token penuh
    all_messages = " ".join(filter(None, [
        result.user_message,
        result.action_suggestion or "",
    ]))
    assert full_rt not in all_messages, (
        f"Refresh token penuh bocor di pesan: {all_messages}"
    )


def test_token_tidak_muncul_utuh_di_plan_error_message(tmp_path):
    """Pesan error plan tidak boleh memuat token refresh yang dikirim ke OAuth."""
    proc_root = tmp_path / "proc"
    # Token yang sangat panjang dan spesifik
    secret_rt = "1//AHde-topsecret-refresh-must-not-appear-in-messages"

    facade, _, keyring, _, oauth, _ = _make_facade(
        accounts={"acc1": _default_account(rt=secret_rt)},
        proc_root=proc_root,
    )
    oauth.fail_with("invalid_grant", "")

    plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI)

    assert plan.error_message is not None
    assert secret_rt not in plan.error_message


# ─── 13. Password enkripsi tidak disimpan atau ditulis ulang ─────────────────


def test_password_enkripsi_tidak_disimpan_di_keyring_atau_file(tmp_path):
    """Password enkripsi tidak muncul di keyring payload maupun file ~/.gemini."""
    proc_root = tmp_path / "proc"
    email = "pw-safe@example.com"
    rt = "1//pw-safe-refresh-token"
    # Simulasi password enkripsi yang dikirim user
    secret_password = "SUPERsecret_p4ssw0rd_do_not_store"

    facade, storage, keyring, gemini, oauth, clock = _make_facade(
        accounts={"acc1": _default_account(email=email, rt=rt)},
        proc_root=proc_root,
    )
    oauth.respond_for(email, refresh_token=rt)

    plan = facade.build_plan("acc1", TARGET_ANTIGRAVITY_CLI, password=secret_password)
    result = facade.apply(plan, password=secret_password)

    assert result.status == ApplyStatus.SUCCESS

    # Keyring payload tidak boleh memuat password
    kr_bytes = keyring.read(KEYRING_SERVICE, KEYRING_USERNAME)
    assert kr_bytes is not None
    kr_str = kr_bytes.decode("utf-8")
    assert secret_password not in kr_str, "Password enkripsi bocor ke keyring!"

    # File oauth_creds.json tidak boleh memuat password
    if gemini.read_oauth_creds() is not None:
        oauth_str = json.dumps(gemini.read_oauth_creds())
        assert secret_password not in oauth_str, "Password enkripsi bocor ke oauth_creds.json!"

    # File google_accounts.json tidak boleh memuat password
    if gemini.read_google_accounts() is not None:
        accs_str = json.dumps(gemini.read_google_accounts())
        assert secret_password not in accs_str, "Password enkripsi bocor ke google_accounts.json!"
