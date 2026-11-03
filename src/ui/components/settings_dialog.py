import os
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.turso_client import TursoClient


class SettingsDialog(QDialog):
  """Dialog untuk mengatur folder Antigravity, database Turso Cloud, dan password enkripsi AES-256."""

  def __init__(self, parent=None):
    super().__init__(parent)
    self.settings = QSettings("OpenCodeApp", "AccountManager")
    self.init_ui()
    self.load_settings()

  def init_ui(self):
    self.setWindowTitle("Pengaturan")
    self.resize(580, 620)

    main_layout = QVBoxLayout(self)
    main_layout.setContentsMargins(12, 12, 12, 12)
    main_layout.setSpacing(12)

    # Scroll area agar tampilan tetap nyaman pada berbagai resolusi layar
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

    container_widget = QWidget()
    content_layout = QVBoxLayout(container_widget)
    content_layout.setSpacing(16)
    content_layout.setContentsMargins(0, 0, 8, 0)

    # =========================================================================
    # 1. Group Folder Antigravity
    # =========================================================================
    folder_group = QGroupBox("Folder Antigravity / OpenCode Config")
    folder_layout = QVBoxLayout(folder_group)

    folder_desc = QLabel(
        "Tentukan folder tempat file <code>antigravity-accounts.json</code> berada:"
    )
    folder_desc.setWordWrap(True)
    folder_layout.addWidget(folder_desc)

    folder_picker_layout = QHBoxLayout()
    self.txt_folder_path = QLineEdit()
    self.txt_folder_path.setPlaceholderText("Pilih direktori folder Antigravity...")
    self.btn_browse = QPushButton("Pilih Folder...")
    self.btn_browse.clicked.connect(self._browse_folder)

    folder_picker_layout.addWidget(self.txt_folder_path)
    folder_picker_layout.addWidget(self.btn_browse)
    folder_layout.addLayout(folder_picker_layout)

    content_layout.addWidget(folder_group)

    # =========================================================================
    # 2. Group Database Turso (Cloud) vs Local
    # =========================================================================
    turso_group = QGroupBox("Penyimpanan Database (Turso Cloud / Local SQLite)")
    turso_layout = QVBoxLayout(turso_group)
    turso_layout.setSpacing(10)

    self.chk_use_turso = QCheckBox("Gunakan Turso Cloud Database (libSQL)")
    self.chk_use_turso.setStyleSheet("font-weight: bold; font-size: 13px;")
    self.chk_use_turso.toggled.connect(self._on_turso_toggled)
    turso_layout.addWidget(self.chk_use_turso)

    # Keterangan detail mengenai Turso
    self.lbl_turso_desc = QLabel(
        "<b>Keterangan:</b><br>"
        "• Secara default aplikasi menggunakan database lokal SQLite (<code>accounts_manager.db</code>).<br>"
        "• Jika opsi di atas <b>dicentang</b>, semua data akun akan disimpan dan disinkronkan ke <b>Turso Database Cloud</b>.<br>"
        "• <b>Turso Database URL:</b> Diperoleh via CLI <code>turso db show &lt;db-name&gt; --url</code> (contoh: <code>libsql://nama-db-org.turso.io</code> atau <code>https://...</code>).<br>"
        "• <b>Turso Auth Token:</b> Diperoleh via CLI <code>turso db tokens create &lt;db-name&gt;</code> atau melalui Dashboard Turso."
    )
    self.lbl_turso_desc.setWordWrap(True)
    self.lbl_turso_desc.setStyleSheet(
        "color: #444; background-color: rgba(0, 0, 0, 0.04); padding: 8px; border-radius: 4px; line-height: 140%;"
    )
    turso_layout.addWidget(self.lbl_turso_desc)

    self.turso_form_widget = QWidget()
    turso_form_layout = QFormLayout(self.turso_form_widget)
    turso_form_layout.setContentsMargins(0, 4, 0, 0)
    turso_form_layout.setSpacing(8)

    self.txt_turso_url = QLineEdit()
    self.txt_turso_url.setPlaceholderText("libsql://nama-database.turso.io atau https://...")

    self.txt_turso_token = QLineEdit()
    self.txt_turso_token.setEchoMode(QLineEdit.EchoMode.Password)
    self.txt_turso_token.setPlaceholderText("Masukkan Auth Token Turso (eyJhbGci...)")

    turso_form_layout.addRow("Database URL:", self.txt_turso_url)
    turso_form_layout.addRow("Auth Token:", self.txt_turso_token)

    turso_layout.addWidget(self.turso_form_widget)

    # Action bar Turso (Show Token & Test Connection)
    turso_actions_layout = QHBoxLayout()
    self.chk_show_turso_token = QCheckBox("Tampilkan Token")
    self.chk_show_turso_token.toggled.connect(self._toggle_show_turso_token)

    self.btn_test_turso = QPushButton("⚡ Tes Koneksi Turso")
    self.btn_test_turso.setStyleSheet("padding: 4px 12px; font-weight: bold;")
    self.btn_test_turso.clicked.connect(self._test_turso_connection)

    turso_actions_layout.addWidget(self.chk_show_turso_token)
    turso_actions_layout.addStretch()
    turso_actions_layout.addWidget(self.btn_test_turso)
    turso_layout.addLayout(turso_actions_layout)

    content_layout.addWidget(turso_group)

    # =========================================================================
    # 3. Group Enkripsi AES-256
    # =========================================================================
    crypto_group = QGroupBox("Enkripsi Akun (AES-256)")
    crypto_layout = QVBoxLayout(crypto_group)

    crypto_desc = QLabel(
        "Atur password master untuk mengamankan data akun menggunakan enkripsi AES-256."
    )
    crypto_desc.setWordWrap(True)
    crypto_layout.addWidget(crypto_desc)

    form_layout = QFormLayout()
    form_layout.setContentsMargins(0, 8, 0, 0)

    self.txt_password = QLineEdit()
    self.txt_password.setEchoMode(QLineEdit.EchoMode.Password)
    self.txt_password.setPlaceholderText("Masukkan password enkripsi")

    self.txt_confirm_password = QLineEdit()
    self.txt_confirm_password.setEchoMode(QLineEdit.EchoMode.Password)
    self.txt_confirm_password.setPlaceholderText("Ulangi password enkripsi")

    form_layout.addRow("Password Enkripsi:", self.txt_password)
    form_layout.addRow("Konfirmasi Password:", self.txt_confirm_password)
    crypto_layout.addLayout(form_layout)

    self.chk_show_password = QCheckBox("Tampilkan Password")
    self.chk_show_password.toggled.connect(self._toggle_show_password)
    crypto_layout.addWidget(self.chk_show_password)

    content_layout.addWidget(crypto_group)

    scroll_area.setWidget(container_widget)
    main_layout.addWidget(scroll_area)

    # =========================================================================
    # Tombol Simpan & Batal
    # =========================================================================
    buttons_layout = QHBoxLayout()
    buttons_layout.addStretch()

    self.btn_cancel = QPushButton("Batal")
    self.btn_cancel.clicked.connect(self.reject)

    self.btn_save = QPushButton("Simpan Pengaturan")
    self.btn_save.setDefault(True)
    self.btn_save.setStyleSheet("font-weight: bold; padding: 6px 16px;")
    self.btn_save.clicked.connect(self._save_settings)

    buttons_layout.addWidget(self.btn_cancel)
    buttons_layout.addWidget(self.btn_save)
    main_layout.addLayout(buttons_layout)

  def _on_turso_toggled(self, checked: bool):
    """Mengaktifkan/menonaktifkan input Turso sesuai status checkbox."""
    self.turso_form_widget.setEnabled(checked)
    self.chk_show_turso_token.setEnabled(checked)
    self.btn_test_turso.setEnabled(checked)

  def _browse_folder(self):
    current_dir = self.txt_folder_path.text().strip() or os.path.expanduser("~")
    folder = QFileDialog.getExistingDirectory(
        self, "Pilih Folder Antigravity", current_dir
    )
    if folder:
      self.txt_folder_path.setText(folder)

  def _toggle_show_password(self, checked: bool):
    mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
    self.txt_password.setEchoMode(mode)
    self.txt_confirm_password.setEchoMode(mode)

  def _toggle_show_turso_token(self, checked: bool):
    mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
    self.txt_turso_token.setEchoMode(mode)

  def _test_turso_connection(self):
    url = self.txt_turso_url.text().strip()
    token = self.txt_turso_token.text().strip()

    if not url:
      QMessageBox.warning(
          self, "URL Belum Diisi", "Silakan masukkan Turso Database URL terlebih dahulu!"
      )
      self.txt_turso_url.setFocus()
      return

    if not token:
      QMessageBox.warning(
          self, "Token Belum Diisi", "Silakan masukkan Turso Auth Token terlebih dahulu!"
      )
      self.txt_turso_token.setFocus()
      return

    client = TursoClient(url, token)
    success, msg = client.test_connection()

    if success:
      QMessageBox.information(
          self,
          "Koneksi Berhasil",
          f"<b>Berhasil terhubung ke Turso!</b><br><br>{msg}<br><br>"
          f"Database: <code>{client.extract_db_name(url)}</code>",
      )
    else:
      QMessageBox.critical(
          self,
          "Koneksi Gagal",
          f"<b>Gagal terhubung ke Turso!</b><br><br>{msg}",
      )

  def load_settings(self):
    folder = self.settings.value("antigravity_folder", "")
    if not folder:
      folder = self.settings.value("opencode_folder", "")
    self.txt_folder_path.setText(folder)

    saved_password = self.settings.value("aes256_password", "")
    if saved_password:
      self.txt_password.setText(saved_password)
      self.txt_confirm_password.setText(saved_password)

    # Memuat pengaturan Turso (default: False/Local)
    use_turso_val = self.settings.value("use_turso", False)
    # Konversi string/bool aman dari QSettings
    if isinstance(use_turso_val, str):
      use_turso = use_turso_val.lower() in ("true", "1")
    else:
      use_turso = bool(use_turso_val)

    self.chk_use_turso.setChecked(use_turso)
    self.txt_turso_url.setText(self.settings.value("turso_url", ""))
    self.txt_turso_token.setText(self.settings.value("turso_token", ""))
    self._on_turso_toggled(use_turso)

  def _save_settings(self):
    folder = self.txt_folder_path.text().strip()
    pwd = self.txt_password.text()
    confirm_pwd = self.txt_confirm_password.text()

    if pwd or confirm_pwd:
      if pwd != confirm_pwd:
        QMessageBox.warning(
            self,
            "Password Tidak Cocok",
            "Password enkripsi dan konfirmasi password tidak sama. Silakan periksa kembali!",
        )
        return

    use_turso = self.chk_use_turso.isChecked()
    turso_url = self.txt_turso_url.text().strip()
    turso_token = self.txt_turso_token.text().strip()

    if use_turso:
      if not turso_url:
        QMessageBox.warning(
            self,
            "Turso URL Kosong",
            "Opsi Turso Cloud diaktifkan, harap masukkan Database URL!",
        )
        self.txt_turso_url.setFocus()
        return
      if not turso_token:
        QMessageBox.warning(
            self,
            "Turso Auth Token Kosong",
            "Opsi Turso Cloud diaktifkan, harap masukkan Auth Token!",
        )
        self.txt_turso_token.setFocus()
        return

    # Simpan ke QSettings
    self.settings.setValue("antigravity_folder", folder)
    self.settings.setValue("opencode_folder", folder)
    self.settings.setValue("aes256_password", pwd)

    self.settings.setValue("use_turso", use_turso)
    self.settings.setValue("turso_url", turso_url)
    self.settings.setValue("turso_token", turso_token)

    QMessageBox.information(
        self, "Sukses", "Pengaturan berhasil disimpan!"
    )
    self.accept()
