"""Dialog untuk mengimpor akun aktif dari Antigravity CLI (Keyring).

Menampilkan data hasil pembacaan keyring (email, refresh token, project_id, kategori),
memungkinkan pengguna mengedit kategori dan project ID sebelum menyimpan.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from src.database import AccountDatabase
from src.integrations.antigravity.errors import (
    KeyringItemNotFoundError,
    KeyringLockedError,
    KeyringParseError,
    KeyringUnavailableError,
    OAuthError,
)
from src.integrations.antigravity.keyring_reader import KeyringImportData, KeyringReader
from src.integrations.antigravity.ports import KeyringPort, OAuthPort
from src.integrations.antigravity.quota_service import fetch_account_quota
from src.ui.components.loading_dialog import WorkerThread
from src.ui.components.secure_line_edit import SecureLineEdit
from src.ui.utils import parse_quota_info

logger = logging.getLogger(__name__)


# Gaya badge status validasi token
BADGE_STYLE_VALIDATING = (
    "background-color: #f1f3f4; color: #5f6368; border: 1px solid #dadce0;"
    " border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: bold;"
)
BADGE_STYLE_VALID = (
    "background-color: #e6f4ea; color: #137333; border: 1px solid #ceead6;"
    " border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: bold;"
)
BADGE_STYLE_INVALID = (
    "background-color: #fce8e6; color: #c5221f; border: 1px solid #fad2cf;"
    " border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: bold;"
)
BADGE_STYLE_NETWORK_ERROR = (
    "background-color: #fef7e0; color: #b06000; border: 1px solid #feefc3;"
    " border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: bold;"
)


class ImportDialog(QDialog):
    """Dialog import akun dari Antigravity CLI."""

    def __init__(
        self,
        keyring: KeyringPort,
        oauth: OAuthPort,
        db: AccountDatabase,
        password: str = "",
        parent: Optional[QWidget] = None,
        reader: Optional[KeyringReader] = None,
    ):
        super().__init__(parent)
        self.keyring = keyring
        self.oauth = oauth
        self.db = db
        self.password = password
        self.reader = reader or KeyringReader()

        self.import_data: Optional[KeyringImportData] = None
        self._validation_worker: Optional[WorkerThread] = None
        self._quota_worker: Optional[WorkerThread] = None
        self.cached_quota: Optional[dict] = None
        self.existing_account_id: Optional[str] = None
        self.existing_account_email: Optional[str] = None

        self.setWindowTitle("Import dari Antigravity CLI")
        self.resize(520, 480)
        self.setModal(True)

        # Coba baca keyring terlebih dahulu
        if not self._load_keyring_data():
            # Bila gagal baca, dialog tidak perlu diinisialisasi lebih lanjut
            return

        self._check_duplicate_email()
        self._init_ui()
        self._start_token_validation()

    def _check_duplicate_email(self) -> None:
        """Cek apakah email akun dari keyring sudah ada di database (case-insensitive)."""
        if not self.db or not self.import_data or not self.import_data.email:
            return

        target_email = self.import_data.email.strip().lower()
        if hasattr(self.db, "fetch_accounts_summary"):
            try:
                rows = self.db.fetch_accounts_summary()
                for row in (rows or []):
                    # Kolom row: 0=id, 1=email, ...
                    if len(row) > 1 and row[1]:
                        if str(row[1]).strip().lower() == target_email:
                            self.existing_account_id = str(row[0])
                            self.existing_account_email = str(row[1])
                            break
            except Exception as exc:
                logger.debug("Gagal memeriksa duplikat email di DB: %s", exc)

    def _load_keyring_data(self) -> bool:
        """Baca item keyring. Jika gagal, tampilkan QMessageBox dan kembalikan False."""
        try:
            self.import_data = self.reader.read_and_parse(self.keyring)
            return True
        except KeyringItemNotFoundError as exc:
            QMessageBox.warning(
                self.parent() or self,
                "Item Keyring Tidak Ditemukan",
                "Akun aktif Antigravity CLI tidak ditemukan di keyring.\n"
                "Pastikan Anda sudah login di Antigravity CLI (`agy auth login`).",
            )
            return False
        except KeyringLockedError as exc:
            QMessageBox.warning(
                self.parent() or self,
                "Keyring Terkunci",
                "GNOME Keyring / Secret Service dalam keadaan terkunci.\n"
                "Silakan buka kunci keyring Anda terlebih dahulu lalu coba lagi.",
            )
            return False
        except KeyringUnavailableError as exc:
            QMessageBox.critical(
                self.parent() or self,
                "Keyring Tidak Tersedia",
                f"Tidak dapat mengakses Keyring / D-Bus Secret Service:\n{exc}",
            )
            return False
        except KeyringParseError as exc:
            QMessageBox.critical(
                self.parent() or self,
                "Format Data Keyring Tidak Valid",
                f"Gagal memproses data dari keyring:\n{exc}",
            )
            return False
        except Exception as exc:
            QMessageBox.critical(
                self.parent() or self,
                "Kesalahan Membaca Keyring",
                f"Terjadi kesalahan yang tidak terduga saat membaca keyring:\n{exc}",
            )
            return False

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 0. Banner Duplikat jika email sudah ada di DB
        if self.existing_account_id:
            banner_widget = QWidget()
            banner_widget.setStyleSheet(
                "background-color: #fef7e0; border: 1px solid #f9ab00; border-radius: 6px; padding: 10px;"
            )
            banner_layout = QVBoxLayout(banner_widget)
            banner_layout.setContentsMargins(6, 6, 6, 6)
            banner_layout.setSpacing(6)

            self.banner_label = QLabel(
                f"⚠️ <b>Email Sudah Ada di Database:</b> Akun dengan email "
                f"<b>{self.existing_account_email}</b> sudah terdaftar (ID: <code>{self.existing_account_id}</code>)."
            )
            self.banner_label.setWordWrap(True)
            self.banner_label.setStyleSheet("color: #202124; font-size: 12px;")
            banner_layout.addWidget(self.banner_label)

            choice_label = QLabel("Pilih tindakan yang ingin dilakukan:")
            choice_label.setStyleSheet("color: #3c4043; font-weight: bold; font-size: 11px;")
            banner_layout.addWidget(choice_label)

            choices_layout = QHBoxLayout()
            self.radio_update = QRadioButton("Perbarui Token")
            self.radio_update.setToolTip("Perbarui refresh token pada akun yang sudah ada")
            self.radio_new_entry = QRadioButton("Tambah sebagai Entri Baru")
            self.radio_new_entry.setToolTip("Simpan sebagai entri akun baru di database")

            self.action_btn_group = QButtonGroup(self)
            self.action_btn_group.addButton(self.radio_update)
            self.action_btn_group.addButton(self.radio_new_entry)
            self.action_btn_group.buttonClicked.connect(self._on_duplicate_choice_changed)

            choices_layout.addWidget(self.radio_update)
            choices_layout.addWidget(self.radio_new_entry)
            choices_layout.addStretch()
            banner_layout.addLayout(choices_layout)

            main_layout.addWidget(banner_widget)

        form_layout = QFormLayout()
        form_layout.setSpacing(8)

        # 1. Field Email (Read-Only)
        self.email_input = QLineEdit()
        self.email_input.setReadOnly(True)
        self.email_input.setText(self.import_data.email or "")
        self.email_input.setPlaceholderText("(Email tidak tersedia di token)")
        form_layout.addRow("Email:", self.email_input)

        # 2. Field Refresh Token (SecureLineEdit + reveal toggle)
        token_container = QWidget()
        token_layout = QHBoxLayout(token_container)
        token_layout.setContentsMargins(0, 0, 0, 0)
        token_layout.setSpacing(6)

        self.token_input = SecureLineEdit()
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.setText(self.import_data.refresh_token or "")
        token_layout.addWidget(self.token_input)

        self.reveal_btn = QPushButton("👁")
        self.reveal_btn.setToolTip("Tampilkan / Sembunyikan Refresh Token")
        self.reveal_btn.setFixedWidth(36)
        self.reveal_btn.clicked.connect(self._toggle_token_visibility)
        token_layout.addWidget(self.reveal_btn)

        form_layout.addRow("Refresh Token:", token_container)

        # 3. Badge Status Token
        self.token_status_badge = QLabel("⏳ Memvalidasi…")
        self.token_status_badge.setStyleSheet(BADGE_STYLE_VALIDATING)
        form_layout.addRow("Status Token:", self.token_status_badge)

        # 4. Field Project ID (Editable)
        self.project_id_input = QLineEdit()
        self.project_id_input.setText(self.import_data.project_id or "")
        self.project_id_input.setPlaceholderText("(Opsional) Project ID Google Cloud")
        form_layout.addRow("Project ID:", self.project_id_input)

        # 5. Field Kategori (Editable Combobox)
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self._populate_categories()
        form_layout.addRow("Kategori:", self.category_combo)

        # 6. Bagian Kuota (Read-Only)
        self.lbl_quota_gemini = QLabel("-")
        form_layout.addRow("Kuota Gemini:", self.lbl_quota_gemini)

        self.lbl_quota_claude = QLabel("-")
        form_layout.addRow("Kuota Claude:", self.lbl_quota_claude)

        self.lbl_quota_status = QLabel("")
        self.lbl_quota_status.setStyleSheet("color: #5f6368; font-size: 11px; font-style: italic;")
        form_layout.addRow("", self.lbl_quota_status)

        main_layout.addLayout(form_layout)

        # Spacer / info
        main_layout.addStretch()

        # 5. Tombol Aksi (Simpan & Batal)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Batal")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("Simpan")
        self.btn_save.setDefault(True)
        # Jika terdapat duplikat email, tombol simpan dinonaktifkan sampai user memilih tindakan
        if self.existing_account_id:
            self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._on_save_clicked)
        btn_layout.addWidget(self.btn_save)

        main_layout.addLayout(btn_layout)

    def _on_duplicate_choice_changed(self) -> None:
        """Aktifkan tombol simpan setelah salah satu tindakan dipilih."""
        if hasattr(self, "btn_save"):
            self.btn_save.setEnabled(True)

    def _on_save_clicked(self) -> None:
        """Simpan akun ke database sesuai pilihan pengguna."""
        if not self.db:
            self.accept()
            return

        refresh_token = self.token_input.text().strip()
        email = self.email_input.text().strip()
        project_id = self.project_id_input.text().strip()
        category = self.category_combo.currentText().strip()
        encrypt = bool(self.password)

        try:
            # Skenario 1: Duplikat & Pengguna memilih Perbarui Token
            if self.existing_account_id and hasattr(self, "radio_update") and self.radio_update.isChecked():
                self.db.update_refresh_token(
                    self.existing_account_id,
                    refresh_token,
                    password=self.password,
                )
                if self.cached_quota and hasattr(self.db, "update_account_quotas"):
                    self.db.update_account_quotas(
                        self.existing_account_id,
                        self.cached_quota,
                        password=self.password,
                    )
                if category and hasattr(self.db, "update_account_category"):
                    self.db.update_account_category(self.existing_account_id, category)

            # Skenario 2: Tambah Baru (baik tanpa duplikat atau duplikat tapi pilih Tambah Baru)
            else:
                new_acc_id = str(uuid.uuid4())
                now_epoch = int(time.time())
                account_dict = {
                    "id": new_acc_id,
                    "email": email,
                    "refreshToken": refresh_token,
                    "refresh_token": refresh_token,
                    "projectId": project_id or None,
                    "addedAt": now_epoch,
                    "category": category,
                }
                if self.cached_quota:
                    account_dict["cachedQuota"] = self.cached_quota
                    account_dict["cachedQuotaUpdatedAt"] = now_epoch

                json_payload = json.dumps({"accounts": [account_dict]})
                self.db.insert_or_update_json(
                    json_payload,
                    encrypt=encrypt,
                    password=self.password,
                    category=category,
                )

            self.accept()
        except Exception as exc:
            logger.error("Gagal menyimpan akun ke database: %s", exc)
            QMessageBox.critical(
                self,
                "Gagal Menyimpan",
                f"Terjadi kesalahan saat menyimpan akun ke database:\n{exc}",
            )

    def _toggle_token_visibility(self) -> None:
        """Toggle antara mode password (tersembunyi) dan normal (terbuka)."""
        if self.token_input.echoMode() == QLineEdit.EchoMode.Password:
            self.token_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.reveal_btn.setText("🔒")
        else:
            self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.reveal_btn.setText("👁")

    def _populate_categories(self) -> None:
        """Isi opsi kategori dari database."""
        self.category_combo.clear()
        if self.db and hasattr(self.db, "fetch_categories"):
            try:
                cats = self.db.fetch_categories()
                for cat in cats:
                    if cat:
                        self.category_combo.addItem(cat)
            except Exception as exc:
                logger.debug("Gagal memuat kategori dari DB: %s", exc)

    def _start_token_validation(self) -> None:
        """Jalankan validasi refresh token di background thread tanpa membekukan UI."""
        if not self.oauth or not self.import_data or not self.import_data.refresh_token:
            return

        token_to_validate = self.import_data.refresh_token

        def task():
            return self.oauth.exchange_refresh_token(token_to_validate)

        self._validation_worker = WorkerThread(task)
        self._validation_worker.success.connect(self._on_validation_success)
        self._validation_worker.failed.connect(self._on_validation_failed)
        self._validation_worker.start()

    def _on_validation_success(self, response: Any) -> None:
        """Dipanggil saat exchange refresh token berhasil."""
        self.token_status_badge.setText("✅ Token Valid")
        self.token_status_badge.setStyleSheet(BADGE_STYLE_VALID)

        # Jika Google mengembalikan refresh_token baru (rotasi token), perbarui form
        new_token = getattr(response, "refresh_token", None)
        if new_token and isinstance(new_token, str) and new_token != self.token_input.text():
            self.token_input.setText(new_token)

        # Jika email di form masih kosong, coba perbarui dari id_token respons
        if not self.email_input.text():
            new_email = getattr(response, "email", None)
            if new_email and isinstance(new_email, str):
                self.email_input.setText(new_email)

        # Token valid: mulai fetch kuota di background
        self._start_quota_fetch()

    def _start_quota_fetch(self) -> None:
        """Fetch kuota akun dari API secara async di background."""
        token = self.token_input.text().strip()
        if not token:
            return

        project_id = self.project_id_input.text().strip() or "aicode-consumers"

        self.lbl_quota_status.setText("Mengambil kuota…")
        self.lbl_quota_status.setStyleSheet("color: #5f6368; font-size: 11px; font-style: italic;")

        def task():
            return fetch_account_quota(token, project_id=project_id)

        self._quota_worker = WorkerThread(task)
        self._quota_worker.success.connect(self._on_quota_success)
        self._quota_worker.failed.connect(self._on_quota_failed)
        self._quota_worker.start()

    def _on_quota_success(self, quota_data: dict) -> None:
        """Dipanggil saat fetch kuota berhasil."""
        self.cached_quota = quota_data
        self.lbl_quota_status.setText("")

        # Format tampilan kuota Gemini
        gemini_item = quota_data.get("gemini-flash") or quota_data.get("gemini-pro") or {}
        g_frac = gemini_item.get("remainingFraction")
        g_reset = gemini_item.get("resetTime")
        g_text, _, _, _, _ = parse_quota_info(g_frac, g_reset)
        self.lbl_quota_gemini.setText(g_text)

        # Format tampilan kuota Claude
        claude_item = quota_data.get("claude", {})
        c_frac = claude_item.get("remainingFraction")
        c_reset = claude_item.get("resetTime")
        c_text, _, _, _, _ = parse_quota_info(c_frac, c_reset)
        self.lbl_quota_claude.setText(c_text)

    def _on_quota_failed(self, error: Exception) -> None:
        """Dipanggil saat fetch kuota gagal."""
        logger.debug("Fetch kuota gagal: %s", error)
        self.cached_quota = None
        self.lbl_quota_gemini.setText("-")
        self.lbl_quota_claude.setText("-")
        self.lbl_quota_status.setText("Kuota tidak berhasil diambil")
        self.lbl_quota_status.setStyleSheet("color: #b06000; font-size: 11px; font-style: italic;")

    def _on_validation_failed(self, error: Exception) -> None:
        """Dipanggil saat exchange refresh token gagal."""
        # Cek apakah error merupakan error respons OAuth (mis. invalid_grant)
        error_code = getattr(error, "code", None)

        if error_code:
            # Error OAuth (misalnya invalid_grant, invalid_request, dsb)
            # PERHATIAN: refresh token tidak pernah ditampilkan di teks badge
            self.token_status_badge.setText(f"❌ Token Tidak Valid: {error_code}")
            self.token_status_badge.setStyleSheet(BADGE_STYLE_INVALID)
        else:
            # Gagal koneksi / timeout / jaringan
            self.token_status_badge.setText("⚠️ Validasi gagal (timeout/jaringan)")
            self.token_status_badge.setStyleSheet(BADGE_STYLE_NETWORK_ERROR)

    def exec(self) -> int:
        """Override exec: jika pembacaan keyring gagal di __init__, jangan tampilkan dialog."""
        if self.import_data is None:
            return QDialog.DialogCode.Rejected
        return super().exec()
