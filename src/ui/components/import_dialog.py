"""Dialog untuk mengimpor akun aktif dari Antigravity CLI (Keyring).

Menampilkan data hasil pembacaan keyring (email, refresh token, project_id, kategori),
memungkinkan pengguna mengedit kategori dan project ID sebelum menyimpan.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.database import AccountDatabase
from src.integrations.antigravity.errors import (
    KeyringItemNotFoundError,
    KeyringLockedError,
    KeyringParseError,
    KeyringUnavailableError,
)
from src.integrations.antigravity.keyring_reader import KeyringImportData, KeyringReader
from src.integrations.antigravity.ports import KeyringPort, OAuthPort
from src.ui.components.secure_line_edit import SecureLineEdit

logger = logging.getLogger(__name__)


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

        self.setWindowTitle("Import dari Antigravity CLI")
        self.resize(500, 320)
        self.setModal(True)

        # Coba baca keyring terlebih dahulu
        if not self._load_keyring_data():
            # Bila gagal baca, dialog tidak perlu diinisialisasi lebih lanjut
            return

        self._init_ui()

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

        # 3. Field Project ID (Editable)
        self.project_id_input = QLineEdit()
        self.project_id_input.setText(self.import_data.project_id or "")
        self.project_id_input.setPlaceholderText("(Opsional) Project ID Google Cloud")
        form_layout.addRow("Project ID:", self.project_id_input)

        # 4. Field Kategori (Editable Combobox)
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self._populate_categories()
        form_layout.addRow("Kategori:", self.category_combo)

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
        self.btn_save.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_save)

        main_layout.addLayout(btn_layout)

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

    def exec(self) -> int:
        """Override exec: jika pembacaan keyring gagal di __init__, jangan tampilkan dialog."""
        if self.import_data is None:
            return QDialog.DialogCode.Rejected
        return super().exec()
