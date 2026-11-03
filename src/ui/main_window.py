import json
import os

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.database import AccountDatabase
from src.turso_client import TursoClient
from src.ui.components import (
    AccountTableWidget,
    ConfigBarWidget,
    JsonInputWidget,
    SettingsDialog,
)


class MainWindow(QMainWindow):

  def __init__(self):
    super().__init__()
    self.settings = QSettings("OpenCodeApp", "AccountManager")
    self.db = None
    self.init_ui()
    self.load_settings()
    self.init_database_connection()
    self.reload_accounts()

  def init_ui(self):
    self.setWindowTitle("JSON Account Manager (PyQt6)")
    self.resize(1100, 700)

    main_widget = QWidget()
    self.setCentralWidget(main_widget)
    main_layout = QVBoxLayout(main_widget)

    # Inisialisasi komponen-komponen terpisah
    self.config_bar = ConfigBarWidget()
    self.json_input = JsonInputWidget()
    self.account_table = AccountTableWidget()

    # Layout penyusunan komponen
    main_layout.addWidget(self.config_bar)

    splitter = QSplitter(Qt.Orientation.Vertical)
    splitter.addWidget(self.json_input)
    splitter.addWidget(self.account_table)
    splitter.setSizes([150, 450])
    main_layout.addWidget(splitter)

    # Menghubungkan sinyal-sinyal komponen
    self.config_bar.settings_requested.connect(self.open_settings_dialog)
    self.json_input.json_submitted.connect(self.process_json)

    self.account_table.sort_mode_changed.connect(self._on_sort_mode_changed)
    self.account_table.copy_requested.connect(self.copy_account_json)
    self.account_table.update_file_requested.connect(self.update_antigravity_file)
    self.account_table.update_db_requested.connect(self.update_db_from_antigravity)
    self.account_table.delete_requested.connect(self.delete_account_with_confirmation)

    # Inisialisasi Menu Bar
    self._init_menu_bar()

  def _init_menu_bar(self):
    menu_bar = self.menuBar()
    
    settings_menu = menu_bar.addMenu("&Pengaturan")

    settings_action = QAction("&Buka Pengaturan...", self)
    settings_action.setShortcut(QKeySequence("Ctrl+,"))
    settings_action.setStatusTip("Atur folder Antigravity dan password enkripsi AES-256")
    settings_action.triggered.connect(self.open_settings_dialog)

    settings_menu.addAction(settings_action)

  def open_settings_dialog(self):
    dialog = SettingsDialog(self)
    if dialog.exec() == SettingsDialog.DialogCode.Accepted:
      # Muat ulang folder di UI dari pengaturan terbaru
      folder = self.settings.value("antigravity_folder", "") or self.settings.value("opencode_folder", "")
      self.config_bar.set_folder_path(folder)
      # Inisialisasi ulang database dan segarkan akun
      self.init_database_connection()
      self.reload_accounts()

  def init_database_connection(self):
    """Menginisialisasi koneksi database (Local SQLite atau Turso Cloud) dan mengupdate indikator UI."""
    use_turso_val = self.settings.value("use_turso", False)
    if isinstance(use_turso_val, str):
      use_turso = use_turso_val.lower() in ("true", "1")
    else:
      use_turso = bool(use_turso_val)

    turso_url = self.settings.value("turso_url", "")
    turso_token = self.settings.value("turso_token", "")

    if use_turso:
      db_name = TursoClient.extract_db_name(turso_url)
      client = TursoClient(turso_url, turso_token)
      connected, msg = client.test_connection()
      try:
        self.db = AccountDatabase(
            use_turso=True, turso_url=turso_url, turso_token=turso_token
        )
      except Exception as e:
        connected = False
        msg = str(e)

      self.config_bar.set_db_status(
          use_turso=True,
          is_connected=connected,
          db_name=db_name,
          error_msg="" if connected else msg,
      )
    else:
      self.db = AccountDatabase(use_turso=False)
      self.config_bar.set_db_status(use_turso=False)

  def load_settings(self):
    """Memuat folder dan preferensi sorting yang tersimpan dari QSettings."""
    saved_folder = self.settings.value("antigravity_folder", "") or self.settings.value("opencode_folder", "")
    self.config_bar.set_folder_path(saved_folder)

    saved_sort = self.settings.value("sort_mode_index", 0, type=int)
    self.account_table.set_sort_index(saved_sort)

  def _on_sort_mode_changed(self, index: int):
    self.settings.setValue("sort_mode_index", index)

  def reload_accounts(self):
    """Mengambil data akun terbaru dari database dan meneruskannya ke AccountTableWidget."""
    try:
      rows = self.db.fetch_accounts_summary() if self.db else []
      self.account_table.set_accounts_data(rows)
    except Exception as e:
      self.account_table.set_accounts_data([])
      use_turso_val = self.settings.value("use_turso", False)
      use_turso = bool(use_turso_val) if not isinstance(use_turso_val, str) else use_turso_val.lower() in ("true", "1")
      if use_turso:
        db_name = TursoClient.extract_db_name(self.settings.value("turso_url", ""))
        self.config_bar.set_db_status(
            use_turso=True,
            is_connected=False,
            db_name=db_name,
            error_msg=str(e),
        )

  def process_json(self, raw_text: str):
    """Handler saat menyimpan JSON baru."""
    if not raw_text:
      QMessageBox.warning(self, "Peringatan", "Area teks JSON masih kosong!")
      return

    try:
      count = self.db.insert_or_update_json(raw_text)
      QMessageBox.information(
          self, "Sukses", f"Berhasil menyimpan {count} akun!"
      )
      self.json_input.clear_input()
      self.reload_accounts()
    except json.JSONDecodeError as e:
      QMessageBox.critical(
          self, "Error JSON", f"Format JSON tidak valid!\n\n{str(e)}"
      )
    except Exception as e:
      QMessageBox.critical(
          self, "Database Error", f"Terjadi kesalahan:\n\n{str(e)}"
      )

  def copy_account_json(self, account_id: str):
    json_str = self.db.reconstruct_json_by_id(account_id)
    if json_str:
      QApplication.clipboard().setText(json_str)
      QMessageBox.information(
          self, "Disalin!", "Format JSON utuh berhasil disalin ke clipboard!"
      )
    else:
      QMessageBox.warning(
          self, "Gagal", "Gagal mengembalikan format JSON dari database."
      )

  def update_antigravity_file(self, account_id: str, email: str):
    folder_path = self.config_bar.get_folder_path()
    if not folder_path or not os.path.exists(folder_path):
      QMessageBox.warning(
          self,
          "Folder Tidak Valid",
          "Silakan pilih folder Antigravity terlebih dahulu lewat Menu Pengaturan!",
      )
      return

    target_file = os.path.join(folder_path, "antigravity-accounts.json")
    if not os.path.exists(target_file):
      QMessageBox.warning(
          self,
          "File Tidak Ditemukan",
          f"File target <b>antigravity-accounts.json</b> tidak ditemukan di"
          f" folder:\n{folder_path}",
      )
      return

    confirm = QMessageBox.question(
        self,
        "Konfirmasi Update File",
        f"Apakah Anda yakin ingin <b>MENIMPA TOTAL</b> isi"
        f" file:\n<b>{target_file}</b>\n\ndengan data akun <b>{email}</b>?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )

    if confirm == QMessageBox.StandardButton.Yes:
      raw_json_str = self.db.reconstruct_json_by_id(account_id)
      if not raw_json_str:
        QMessageBox.critical(
            self, "Error", "Gagal mengambil data akun dari database."
        )
        return

      try:
        new_data = json.loads(raw_json_str)
        with open(target_file, "w", encoding="utf-8") as f:
          json.dump(new_data, f, indent=2)

        QMessageBox.information(
            self,
            "Berhasil",
            f"File <b>antigravity-accounts.json</b> berhasil ditimpa total"
            f" dengan akun:\n{email}",
        )
      except Exception as e:
        QMessageBox.critical(
            self,
            "Gagal Menulis File",
            f"Terjadi kesalahan saat menulis file:\n\n{str(e)}",
        )

  def update_db_from_antigravity(self, account_id: str, email: str):
    folder_path = self.config_bar.get_folder_path()
    if not folder_path or not os.path.exists(folder_path):
      QMessageBox.warning(
          self,
          "Folder Tidak Valid",
          "Silakan pilih folder Antigravity terlebih dahulu lewat Menu Pengaturan!",
      )
      return

    target_file = os.path.join(folder_path, "antigravity-accounts.json")
    if not os.path.exists(target_file):
      QMessageBox.warning(
          self,
          "File Tidak Ditemukan",
          f"File <b>antigravity-accounts.json</b> tidak ditemukan di"
          f" folder:\n{folder_path}",
      )
      return

    try:
      with open(target_file, "r", encoding="utf-8") as f:
        content = f.read().strip()
        if not content:
          QMessageBox.warning(
              self,
              "File Kosong",
              "File <b>antigravity-accounts.json</b> kosong!",
          )
          return
        file_data = json.loads(content)
    except json.JSONDecodeError as e:
      QMessageBox.critical(
          self,
          "Error JSON File",
          f"Format file antigravity-accounts.json tidak valid!\n\n{str(e)}",
      )
      return
    except Exception as e:
      QMessageBox.critical(
          self,
          "Gagal Membaca File",
          f"Gagal membaca file:\n\n{str(e)}",
      )
      return

    file_acc = (
        file_data.get("accounts", [file_data])[0]
        if isinstance(file_data, dict) and "accounts" in file_data
        else file_data
    )
    if isinstance(file_acc, list) and len(file_acc) > 0:
      file_acc = file_acc[0]

    file_acc_id = file_acc.get("id") if isinstance(file_acc, dict) else None
    file_acc_email = (
        file_acc.get("email", "Tidak Diketahui")
        if isinstance(file_acc, dict)
        else "Tidak Diketahui"
    )

    mismatch_warning = ""
    if file_acc_id and file_acc_id != account_id:
      mismatch_warning = (
          f"\n\n<b>PERINGATAN BEDA AKUN:</b>\n"
          f"ID Akun di file (<b>{file_acc_email}</b>) BERBEDA dengan baris"
          f" yang dipilih di tabel (<b>{email}</b>)!"
      )

    confirm = QMessageBox.question(
        self,
        "Konfirmasi Update Database",
        f"Apakah Anda yakin ingin memperbarui data database baris"
        f" <b>{email}</b> menggunakan isi dari file:\n<b>{target_file}</b>?{mismatch_warning}",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )

    if confirm == QMessageBox.StandardButton.Yes:
      try:
        self.db.insert_or_update_json(content)
        QMessageBox.information(
            self,
            "Berhasil Update Database",
            "Berhasil mengonfirmasi & memperbarui data akun ke database!",
        )
        self.reload_accounts()
      except Exception as e:
        QMessageBox.critical(
            self,
            "Database Error",
            f"Terjadi kesalahan saat memperbarui database:\n\n{str(e)}",
        )

  def delete_account_with_confirmation(self, account_id: str, email: str):
    """Menampilkan dialog konfirmasi dan menghapus akun dari database."""
    confirm = QMessageBox.question(
        self,
        "Konfirmasi Hapus Akun",
        f"Apakah Anda yakin ingin <b>MENGHAPUS PERMANEN</b> akun ini dari database?\n\n"
        f"Email: <b>{email}</b>\nID: <code>{account_id}</code>",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )

    if confirm == QMessageBox.StandardButton.Yes:
      try:
        success = self.db.delete_account(account_id)
        if success:
          QMessageBox.information(
              self,
              "Berhasil",
              f"Akun <b>{email}</b> berhasil dihapus dari database.",
          )
          self.reload_accounts()
        else:
          QMessageBox.warning(
              self,
              "Gagal",
              "Data akun tidak ditemukan atau gagal dihapus.",
          )
      except Exception as e:
        QMessageBox.critical(
            self,
            "Database Error",
            f"Terjadi kesalahan saat menghapus data:\n\n{str(e)}",
        )
