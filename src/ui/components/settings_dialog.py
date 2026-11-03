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
    QVBoxLayout,
)


class SettingsDialog(QDialog):
  """Dialog untuk mengatur folder Antigravity dan password enkripsi AES-256."""

  def __init__(self, parent=None):
    super().__init__(parent)
    self.settings = QSettings("OpenCodeApp", "AccountManager")
    self.init_ui()
    self.load_settings()

  def init_ui(self):
    self.setWindowTitle("Pengaturan")
    self.resize(520, 320)

    layout = QVBoxLayout(self)
    layout.setSpacing(16)

    # --- Group Folder Antigravity ---
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

    layout.addWidget(folder_group)

    # --- Group Enkripsi AES-256 ---
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

    layout.addWidget(crypto_group)

    # --- Action Buttons ---
    buttons_layout = QHBoxLayout()
    buttons_layout.addStretch()

    self.btn_cancel = QPushButton("Batal")
    self.btn_cancel.clicked.connect(self.reject)

    self.btn_save = QPushButton("Simpan Pengaturan")
    self.btn_save.setDefault(True)
    self.btn_save.setStyleSheet("font-weight: bold; padding: 6px 14px;")
    self.btn_save.clicked.connect(self._save_settings)

    buttons_layout.addWidget(self.btn_cancel)
    buttons_layout.addWidget(self.btn_save)
    layout.addLayout(buttons_layout)

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

  def load_settings(self):
    folder = self.settings.value("antigravity_folder", "")
    if not folder:
      # Kompatibilitas dengan konfigurasi sebelumnya jika ada
      folder = self.settings.value("opencode_folder", "")
    self.txt_folder_path.setText(folder)

    saved_password = self.settings.value("aes256_password", "")
    if saved_password:
      self.txt_password.setText(saved_password)
      self.txt_confirm_password.setText(saved_password)

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

    # Simpan ke QSettings
    self.settings.setValue("antigravity_folder", folder)
    self.settings.setValue("opencode_folder", folder)  # keep in sync
    self.settings.setValue("aes256_password", pwd)

    QMessageBox.information(
        self, "Sukses", "Pengaturan berhasil disimpan!"
    )
    self.accept()
