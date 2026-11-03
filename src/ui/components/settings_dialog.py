import os
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.turso_client import TursoClient
from src.ui.components.secure_line_edit import SecureLineEdit

# Sentinel yang ditampilkan di field password saat sudah ada password tersimpan
_PASSWORD_PLACEHOLDER = "••••••••"


class SettingsDialog(QDialog):
  """Dialog untuk mengatur folder Antigravity, database Turso Cloud, dan password enkripsi AES-256."""

  def __init__(self, parent=None):
    super().__init__(parent)
    self.settings = QSettings("OpenCodeApp", "AccountManager")
    # Lacak apakah password sudah tersimpan (tampilkan placeholder, bukan nilai asli)
    self._password_already_saved = False
    self._turso_url_already_saved = False
    self._turso_token_already_saved = False
    self._is_loading = True
    self.init_ui()
    self.load_settings()

  def init_ui(self):
    self.setWindowTitle("Pengaturan")
    self.resize(580, 680)

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

    # URL: SecureLineEdit — tidak bisa dicopy
    url_row = QHBoxLayout()
    self.txt_turso_url = SecureLineEdit()
    self.txt_turso_url.setPlaceholderText("libsql://nama-database.turso.io atau https://...")
    self.btn_edit_url = QPushButton("✏ Ubah")
    self.btn_edit_url.setFixedWidth(70)
    self.btn_edit_url.setToolTip("Klik untuk mengubah Database URL")
    self.btn_edit_url.clicked.connect(self._edit_turso_url)
    url_row.addWidget(self.txt_turso_url)
    url_row.addWidget(self.btn_edit_url)

    # Token: SecureLineEdit, selalu Password mode — tidak bisa dicopy & tidak bisa ditampilkan
    token_row = QHBoxLayout()
    self.txt_turso_token = SecureLineEdit()
    self.txt_turso_token.setEchoMode(QLineEdit.EchoMode.Password)
    self.txt_turso_token.setPlaceholderText("Masukkan Auth Token Turso (eyJhbGci...)")
    self.btn_edit_token = QPushButton("✏ Ubah")
    self.btn_edit_token.setFixedWidth(70)
    self.btn_edit_token.setToolTip("Klik untuk mengubah Auth Token")
    self.btn_edit_token.clicked.connect(self._edit_turso_token)
    token_row.addWidget(self.txt_turso_token)
    token_row.addWidget(self.btn_edit_token)

    turso_form_layout.addRow("Database URL:", url_row)
    turso_form_layout.addRow("Auth Token:", token_row)

    turso_layout.addWidget(self.turso_form_widget)

    # Action bar Turso (hanya Tes Koneksi — tanpa "Tampilkan Token")
    turso_actions_layout = QHBoxLayout()
    turso_actions_layout.addStretch()
    self.btn_test_turso = QPushButton("⚡ Tes Koneksi Turso")
    self.btn_test_turso.setStyleSheet("padding: 4px 12px; font-weight: bold;")
    self.btn_test_turso.clicked.connect(self._test_turso_connection)
    turso_actions_layout.addWidget(self.btn_test_turso)
    turso_layout.addLayout(turso_actions_layout)

    content_layout.addWidget(turso_group)

    # =========================================================================
    # 3. Group Enkripsi AES-256
    # =========================================================================
    crypto_group = QGroupBox("Enkripsi Akun (AES-256)")
    crypto_layout = QVBoxLayout(crypto_group)
    crypto_layout.setSpacing(10)

    self.chk_enable_crypto = QCheckBox("Aktifkan Enkripsi Akun (AES-256)")
    self.chk_enable_crypto.setStyleSheet("font-weight: bold; font-size: 13px;")
    self.chk_enable_crypto.toggled.connect(self._on_crypto_toggled)
    crypto_layout.addWidget(self.chk_enable_crypto)

    crypto_desc = QLabel(
        "Jika diaktifkan, data kredensial akun yang dimasukkan via Paste JSON "
        "akan disimpan ke database dalam bentuk terenkripsi AES-256 menggunakan password master di bawah."
    )
    crypto_desc.setWordWrap(True)
    crypto_desc.setStyleSheet(
        "color: #444; background-color: rgba(0, 0, 0, 0.04); padding: 8px; border-radius: 4px; line-height: 140%;"
    )
    crypto_layout.addWidget(crypto_desc)

    self.crypto_form_widget = QWidget()
    form_layout = QFormLayout(self.crypto_form_widget)
    form_layout.setContentsMargins(0, 4, 0, 0)
    form_layout.setSpacing(8)

    # Password: SecureLineEdit, selalu Password mode — tidak bisa dicopy & tidak bisa ditampilkan
    self.txt_password = SecureLineEdit()
    self.txt_password.setEchoMode(QLineEdit.EchoMode.Password)
    self.txt_password.setPlaceholderText("Masukkan password master enkripsi...")
    self.txt_password.textChanged.connect(self._on_password_changed)

    self.txt_confirm_password = SecureLineEdit()
    self.txt_confirm_password.setEchoMode(QLineEdit.EchoMode.Password)
    self.txt_confirm_password.setPlaceholderText("Ulangi konfirmasi password master...")
    self.txt_confirm_password.textChanged.connect(self._on_password_changed)

    form_layout.addRow("Password Enkripsi:", self.txt_password)
    form_layout.addRow("Konfirmasi Password:", self.txt_confirm_password)
    crypto_layout.addWidget(self.crypto_form_widget)

    # Label info password tersimpan
    self.lbl_password_info = QLabel(
        "🔒 Password enkripsi sudah tersimpan. Kosongkan kedua field di atas untuk mempertahankan password lama, "
        "atau isi keduanya untuk mengganti password."
    )
    self.lbl_password_info.setWordWrap(True)
    self.lbl_password_info.setStyleSheet(
        "color: #1a73e8; background-color: #e8f0fe; padding: 6px 8px; border-radius: 4px; font-size: 11px;"
    )
    self.lbl_password_info.setVisible(False)
    crypto_layout.addWidget(self.lbl_password_info)

    # Tombol hapus enkripsi di database
    decrypt_db_layout = QHBoxLayout()
    self.btn_decrypt_db = QPushButton("🔓 Hapus Enkripsi dari Database")
    self.btn_decrypt_db.setStyleSheet(
        "padding: 5px 14px; font-weight: bold; color: #c5221f;"
        " border: 1px solid #ea4335; border-radius: 4px;"
    )
    self.btn_decrypt_db.setToolTip(
        "Dekripsi semua akun di database menggunakan password saat ini, lalu simpan kembali sebagai plaintext.\n"
        "Gunakan ini sebelum mengganti password enkripsi."
    )
    self.btn_decrypt_db.clicked.connect(self._decrypt_all_in_db)
    decrypt_db_layout.addStretch()
    decrypt_db_layout.addWidget(self.btn_decrypt_db)
    crypto_layout.addLayout(decrypt_db_layout)

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

  # ─── Slot toggle & interaksi ───

  def _update_crypto_field_lock_state(self):
    """Mengatur status kunci (read-only) pada field password sesuai status centang enkripsi."""
    is_enc_enabled = self.chk_enable_crypto.isChecked()

    if is_enc_enabled:
      self.crypto_form_widget.setEnabled(True)
      self.btn_decrypt_db.setEnabled(True)
      if self._password_already_saved:
        # Jika enkripsi aktif dan password sudah tersimpan, kunci field password agar tidak bisa diisi
        self.txt_password.setReadOnly(True)
        self.txt_confirm_password.setReadOnly(True)
        self.txt_password.clear()
        self.txt_confirm_password.clear()
        self.txt_password.setPlaceholderText("🔒 Terkunci: Nonaktifkan centang untuk mengubah password")
        self.txt_confirm_password.setPlaceholderText("🔒 Terkunci: Nonaktifkan centang untuk mengubah password")
        self.txt_password.setStyleSheet(
            "QLineEdit { background-color: rgba(128, 128, 128, 0.12); color: #777; }"
        )
        self.txt_confirm_password.setStyleSheet(
            "QLineEdit { background-color: rgba(128, 128, 128, 0.12); color: #777; }"
        )
        self.lbl_password_info.setText(
            "🔒 <b>Password Enkripsi Terkunci:</b> Enkripsi AES-256 aktif. "
            "Untuk mencegah korupsi data, field password tidak dapat diisi/diubah secara langsung. "
            "Nonaktifkan centang di atas jika ingin mengubah konfigurasi."
        )
        self.lbl_password_info.setVisible(True)
      else:
        self.txt_password.setReadOnly(False)
        self.txt_confirm_password.setReadOnly(False)
        self.txt_password.setStyleSheet("")
        self.txt_confirm_password.setStyleSheet("")
        self.txt_password.setPlaceholderText("Masukkan password master enkripsi...")
        self.txt_confirm_password.setPlaceholderText("Ulangi konfirmasi password master...")
        self.lbl_password_info.setVisible(False)
    else:
      # Centang nonaktif: field password bisa diisi untuk mengatur password baru jika ingin mengaktifkan nanti
      self.crypto_form_widget.setEnabled(True)
      self.btn_decrypt_db.setEnabled(True)
      self.txt_password.setReadOnly(False)
      self.txt_confirm_password.setReadOnly(False)
      self.txt_password.setStyleSheet("")
      self.txt_confirm_password.setStyleSheet("")
      self.txt_password.setPlaceholderText("Masukkan password jika ingin mengaktifkan nanti...")
      self.txt_confirm_password.setPlaceholderText("Ulangi konfirmasi password master...")
      self.lbl_password_info.setVisible(False)

  def _on_crypto_toggled(self, checked: bool):
    """Menangani aktivasi dan deaktivasi enkripsi dengan konfirmasi ketat dan verifikasi password."""
    if self._is_loading:
      self._update_crypto_field_lock_state()
      return

    if checked:
      # User ingin mengaktifkan enkripsi
      confirm = QMessageBox.warning(
          self,
          "Konfirmasi Mengaktifkan Enkripsi",
          "<b>PERHATIAN: Mengaktifkan Enkripsi Akun (AES-256)</b><br><br>"
          "Data akun baru yang dimasukkan via Paste JSON akan disimpan dalam kondisi <b>terenkripsi penuh</b>.<br><br>"
          "⚠️ <b>Penting:</b> Pastikan Anda mengingat atau mencatat password enkripsi ini.<br>"
          "Jika password hilang atau lupa, data tidak akan bisa didekripsi atau dipulihkan kembali!<br><br>"
          "Apakah Anda yakin ingin mengaktifkan enkripsi?",
          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
          QMessageBox.StandardButton.No,
      )
      if confirm != QMessageBox.StandardButton.Yes:
        self.chk_enable_crypto.blockSignals(True)
        self.chk_enable_crypto.setChecked(False)
        self.chk_enable_crypto.blockSignals(False)
        self._update_crypto_field_lock_state()
        return

      self._update_crypto_field_lock_state()

    else:
      # User ingin menonaktifkan enkripsi (beralih ke plaintext)
      saved_password = self.settings.value("aes256_password", "")
      if saved_password:
        entered_pwd, ok = QInputDialog.getText(
            self,
            "Verifikasi Password Enkripsi",
            "Masukkan password enkripsi saat ini untuk menonaktifkan enkripsi:\n"
            "(Diperlukan demi mencegah korupsi data)",
            QLineEdit.EchoMode.Password,
            "",
        )
        if not ok or not entered_pwd:
          # Batal dinonaktifkan
          self.chk_enable_crypto.blockSignals(True)
          self.chk_enable_crypto.setChecked(True)
          self.chk_enable_crypto.blockSignals(False)
          return

        if entered_pwd != saved_password:
          QMessageBox.critical(
              self,
              "Password Salah",
              "<b>Password enkripsi yang dimasukkan salah!</b><br><br>"
              "Centang enkripsi tidak dapat dinonaktifkan demi menjaga keutuhan data.",
          )
          self.chk_enable_crypto.blockSignals(True)
          self.chk_enable_crypto.setChecked(True)
          self.chk_enable_crypto.blockSignals(False)
          return

      # Tampilkan peringatan konfirmasi bahaya data korup
      confirm = QMessageBox.warning(
          self,
          "Peringatan Menonaktifkan Enkripsi",
          "<b>PERHATIAN: Anda akan menonaktifkan enkripsi akun!</b><br><br>"
          "• Data akun baru yang dimasukkan setelah ini akan disimpan sebagai <b>PLAINTEXT</b>.<br>"
          "• <b>Penting:</b> Data yang sudah terenkripsi di database <b>TIDAK</b> otomatis menjadi plaintext "
          "kecuali Anda memilih <i>'Hapus Enkripsi dari Database'</i>.<br>"
          "• Mengabaikan hal ini dapat memicu ketidakkonsistenan data (corrupt data).<br><br>"
          "Apakah Anda yakin ingin melanjutkan menonaktifkan enkripsi?",
          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
          QMessageBox.StandardButton.No,
      )
      if confirm != QMessageBox.StandardButton.Yes:
        self.chk_enable_crypto.blockSignals(True)
        self.chk_enable_crypto.setChecked(True)
        self.chk_enable_crypto.blockSignals(False)
        return

      self._update_crypto_field_lock_state()

  def _on_turso_toggled(self, checked: bool):
    """Mengaktifkan/menonaktifkan input Turso sesuai status checkbox."""
    self.turso_form_widget.setEnabled(checked)
    self.btn_test_turso.setEnabled(checked)

  def _on_password_changed(self):
    """Saat user mulai mengetik, sembunyikan info label placeholder."""
    if self.txt_password.text() or self.txt_confirm_password.text():
      self.lbl_password_info.setVisible(False)
    elif self._password_already_saved and self.chk_enable_crypto.isChecked():
      self.lbl_password_info.setVisible(True)

  def _browse_folder(self):
    current_dir = self.txt_folder_path.text().strip() or os.path.expanduser("~")
    folder = QFileDialog.getExistingDirectory(
        self, "Pilih Folder Antigravity", current_dir
    )
    if folder:
      self.txt_folder_path.setText(folder)

  def _edit_turso_url(self):
    """Buka dialog input untuk mengubah Database URL."""
    from PyQt6.QtWidgets import QInputDialog
    new_url, ok = QInputDialog.getText(
        self,
        "Ubah Database URL",
        "Masukkan Turso Database URL baru:\n(libsql://... atau https://...)",
        QLineEdit.EchoMode.Normal,
        "",
    )
    if ok and new_url.strip():
      self.txt_turso_url.setText(new_url.strip())
      self._turso_url_already_saved = False
    elif ok and not new_url.strip():
      # Dikosongkan → reset
      self.txt_turso_url.clear()
      self._turso_url_already_saved = False

  def _edit_turso_token(self):
    """Buka dialog input untuk mengubah Auth Token."""
    from PyQt6.QtWidgets import QInputDialog
    new_token, ok = QInputDialog.getText(
        self,
        "Ubah Auth Token",
        "Masukkan Turso Auth Token baru:",
        QLineEdit.EchoMode.Password,
        "",
    )
    if ok and new_token.strip():
      self.txt_turso_token.setText(new_token.strip())
      self._turso_token_already_saved = False
    elif ok and not new_token.strip():
      self.txt_turso_token.clear()
      self._turso_token_already_saved = False

  def _test_turso_connection(self):
    # Ambil URL: jika placeholder tersimpan, gunakan nilai dari QSettings
    if self._turso_url_already_saved:
      url = self.settings.value("turso_url", "")
    else:
      url = self.txt_turso_url.text().strip()

    if self._turso_token_already_saved:
      token = self.settings.value("turso_token", "")
    else:
      token = self.txt_turso_token.text().strip()

    if not url:
      QMessageBox.warning(
          self, "URL Belum Diisi", "Silakan masukkan Turso Database URL terlebih dahulu!"
      )
      return

    if not token:
      QMessageBox.warning(
          self, "Token Belum Diisi", "Silakan masukkan Turso Auth Token terlebih dahulu!"
      )
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

  def _decrypt_all_in_db(self):
    """Mendekripsi semua akun terenkripsi di database menjadi plaintext setelah verifikasi password."""
    saved_password = self.settings.value("aes256_password", "")

    # Pengguna wajib memasukkan password enkripsi terlebih dahulu
    entered_password, ok = QInputDialog.getText(
        self,
        "Verifikasi Password Dekripsi",
        "Masukkan password enkripsi akun untuk mendekripsi semua data di database:",
        QLineEdit.EchoMode.Password,
        "",
    )
    if not ok or not entered_password:
      return

    if saved_password and entered_password != saved_password:
      QMessageBox.critical(
          self,
          "Password Salah",
          "<b>Password enkripsi yang dimasukkan salah!</b><br><br>"
          "Operasi dekripsi dibatalkan demi keamanan agar data tidak korup.",
      )
      return

    confirm = QMessageBox.question(
        self,
        "Konfirmasi Hapus Enkripsi",
        "<b>Hapus enkripsi dari semua akun di database?</b><br><br>"
        "Seluruh data akun yang terenkripsi akan didekripsi menggunakan password yang dimasukkan "
        "dan disimpan kembali sebagai <b>plaintext</b>.<br><br>"
        "Apakah Anda yakin ingin melanjutkan?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if confirm != QMessageBox.StandardButton.Yes:
      return

    # Import di sini untuk menghindari circular import
    from src.database import AccountDatabase
    from PyQt6.QtCore import QSettings

    s = QSettings("OpenCodeApp", "AccountManager")
    use_turso_val = s.value("use_turso", False)
    use_turso = (
        use_turso_val.lower() in ("true", "1")
        if isinstance(use_turso_val, str)
        else bool(use_turso_val)
    )
    turso_url = s.value("turso_url", "")
    turso_token = s.value("turso_token", "")

    try:
      db = AccountDatabase(
          use_turso=use_turso,
          turso_url=turso_url,
          turso_token=turso_token,
      )
      count = db.decrypt_all_accounts(entered_password)
      QMessageBox.information(
          self,
          "Enkripsi Dihapus",
          f"Berhasil mendekripsi <b>{count}</b> akun dari database.<br><br>"
          "Semua data akun kini tersimpan sebagai <b>plaintext</b>.<br>"
          "Anda sekarang dapat mengganti password enkripsi dengan aman.",
      )
    except Exception as e:
      QMessageBox.critical(
          self,
          "Gagal Mendekripsi",
          f"Terjadi kesalahan saat mendekripsi database:<br><br>{str(e)}",
      )

  # ─── Load & Save Settings ───

  def load_settings(self):
    self._is_loading = True
    folder = self.settings.value("antigravity_folder", "")
    if not folder:
      folder = self.settings.value("opencode_folder", "")
    self.txt_folder_path.setText(folder)

    # Password tersimpan check
    saved_password = self.settings.value("aes256_password", "")
    self._password_already_saved = bool(saved_password)

    # Enkripsi
    enable_crypto_val = self.settings.value("enable_encryption", False)
    if isinstance(enable_crypto_val, str):
      enable_crypto = enable_crypto_val.lower() in ("true", "1")
    else:
      enable_crypto = bool(enable_crypto_val)

    self.chk_enable_crypto.setChecked(enable_crypto)
    self._update_crypto_field_lock_state()

    # Turso
    use_turso_val = self.settings.value("use_turso", False)
    if isinstance(use_turso_val, str):
      use_turso = use_turso_val.lower() in ("true", "1")
    else:
      use_turso = bool(use_turso_val)

    self.chk_use_turso.setChecked(use_turso)

    # Jika URL sudah tersimpan, tampilkan teks masked — tidak isi dengan nilai asli
    saved_url = self.settings.value("turso_url", "")
    if saved_url:
      self._turso_url_already_saved = True
      self.txt_turso_url.setPlaceholderText("✔ URL sudah tersimpan — klik Ubah untuk mengganti")
      self.txt_turso_url.setReadOnly(True)
      self.txt_turso_url.setStyleSheet(
          "QLineEdit { background-color: rgba(0,128,0,0.07); color: #137333; font-style: italic; }"
      )
    else:
      self._turso_url_already_saved = False

    saved_token = self.settings.value("turso_token", "")
    if saved_token:
      self._turso_token_already_saved = True
      self.txt_turso_token.setPlaceholderText("✔ Auth Token sudah tersimpan — klik Ubah untuk mengganti")
      self.txt_turso_token.setReadOnly(True)
      self.txt_turso_token.setStyleSheet(
          "QLineEdit { background-color: rgba(0,128,0,0.07); color: #137333; font-style: italic; }"
      )
    else:
      self._turso_token_already_saved = False

    self._on_turso_toggled(use_turso)
    self._is_loading = False

  def _save_settings(self):
    folder = self.txt_folder_path.text().strip()
    enable_crypto = self.chk_enable_crypto.isChecked()

    # Tentukan password yang akan disimpan:
    # - Jika field kosong & ada password lama → pertahankan password lama
    # - Jika field diisi → gunakan nilai baru (wajib cocok)
    new_pwd = self.txt_password.text()
    new_confirm = self.txt_confirm_password.text()

    if enable_crypto:
      if not new_pwd and self._password_already_saved:
        # Pertahankan password lama
        pwd_to_save = self.settings.value("aes256_password", "")
      elif not new_pwd:
        QMessageBox.warning(
            self,
            "Password Enkripsi Kosong",
            "Enkripsi akun diaktifkan, harap masukkan Password Enkripsi!",
        )
        self.txt_password.setFocus()
        return
      else:
        if new_pwd != new_confirm:
          QMessageBox.warning(
              self,
              "Password Tidak Cocok",
              "Password enkripsi dan konfirmasi password tidak sama. Silakan periksa kembali!",
          )
          self.txt_confirm_password.setFocus()
          return
        pwd_to_save = new_pwd
    else:
      # Enkripsi nonaktif — tetap simpan password jika ada (untuk referensi dekripsi data lama)
      if new_pwd and new_pwd != new_confirm:
        QMessageBox.warning(
            self,
            "Password Tidak Cocok",
            "Password enkripsi dan konfirmasi password tidak sama. Silakan periksa kembali!",
        )
        return
      pwd_to_save = new_pwd if new_pwd else self.settings.value("aes256_password", "")

    # Tentukan URL & Token Turso yang akan disimpan
    use_turso = self.chk_use_turso.isChecked()

    if self._turso_url_already_saved and not self.txt_turso_url.text().strip():
      turso_url = self.settings.value("turso_url", "")
    else:
      turso_url = self.txt_turso_url.text().strip()

    if self._turso_token_already_saved and not self.txt_turso_token.text().strip():
      turso_token = self.settings.value("turso_token", "")
    else:
      turso_token = self.txt_turso_token.text().strip()

    if use_turso:
      if not turso_url:
        QMessageBox.warning(
            self,
            "Turso URL Kosong",
            "Opsi Turso Cloud diaktifkan, harap masukkan Database URL!",
        )
        return
      if not turso_token:
        QMessageBox.warning(
            self,
            "Turso Auth Token Kosong",
            "Opsi Turso Cloud diaktifkan, harap masukkan Auth Token!",
        )
        return

    # Simpan ke QSettings
    self.settings.setValue("antigravity_folder", folder)
    self.settings.setValue("opencode_folder", folder)
    self.settings.setValue("enable_encryption", enable_crypto)
    self.settings.setValue("aes256_password", pwd_to_save)

    self.settings.setValue("use_turso", use_turso)
    self.settings.setValue("turso_url", turso_url)
    self.settings.setValue("turso_token", turso_token)

    QMessageBox.information(
        self, "Sukses", "Pengaturan berhasil disimpan!"
    )
    self.accept()
