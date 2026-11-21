import json
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.database import AccountDatabase
from src.integrations.antigravity.factory import create_facade
from src.targets import create_settings
from src.turso_client import TursoClient
from src.ui.components import (
    AboutDialog,
    AccountTableWidget,
    CategoryManagementDialog,
    ConfigBarWidget,
    JsonInputWidget,
    LoadingDialog,
    SettingsDialog,
    WorkerThread,
)


class MainWindow(QMainWindow):

  def __init__(self):
    super().__init__()
    self.settings = create_settings()
    self.db = None
    self.facade = None
    self._current_worker = None  # Mencegah garbage collection pada worker aktif
    self.init_ui()
    self.load_settings()
    self.init_database_connection()
    self.reload_accounts()

  def init_ui(self):
    self.setWindowTitle("JSON Account Manager (PyQt6)")
    self.resize(1100, 700)

    # Set Window Icon jika file ada
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    icon_path = os.path.join(base_dir, "assets", "images", "app_icon.png")
    if os.path.exists(icon_path):
      self.setWindowIcon(QIcon(icon_path))

    main_widget = QWidget()
    self.setCentralWidget(main_widget)
    main_layout = QVBoxLayout(main_widget)

    self.config_bar = ConfigBarWidget(settings=self.settings)
    self.json_input = JsonInputWidget()
    self.account_table = AccountTableWidget()

    main_layout.addWidget(self.config_bar)

    splitter = QSplitter(Qt.Orientation.Vertical)
    splitter.addWidget(self.json_input)
    splitter.addWidget(self.account_table)
    splitter.setSizes([150, 450])
    main_layout.addWidget(splitter)

    self.json_input.json_submitted.connect(self.process_json)

    self.account_table.sort_mode_changed.connect(self._on_sort_mode_changed)
    self.account_table.category_filter_changed.connect(self._on_category_filter_changed)
    self.account_table.manage_categories_requested.connect(self.open_category_management_dialog)
    self.account_table.bulk_change_category_requested.connect(self.bulk_change_account_category)
    self.account_table.apply_requested.connect(self.apply_account_to_target)
    self.config_bar.target_changed.connect(self._on_target_changed)
    self.account_table.copy_requested.connect(self.copy_account_json)
    self.account_table.refresh_quota_requested.connect(self.refresh_account_quota)
    self.account_table.bulk_refresh_quota_requested.connect(self.bulk_refresh_account_quotas)
    self.account_table.refresh_all_quotas_requested.connect(self.refresh_all_accounts_quota)
    self.account_table.update_file_requested.connect(self.update_antigravity_file)
    self.account_table.update_db_requested.connect(self.update_db_from_antigravity)
    self.account_table.change_category_requested.connect(self.change_account_category)
    self.account_table.delete_requested.connect(self.delete_account_with_confirmation)

    self._init_menu_bar()

  def _init_menu_bar(self):
    menu_bar = self.menuBar()

    category_menu = menu_bar.addMenu("&Kategori")
    manage_cat_action = QAction("&Kelola Kategori...", self)
    manage_cat_action.setShortcut(QKeySequence("Ctrl+M"))
    manage_cat_action.setStatusTip("Ubah nama, pindahkan banyak akun, atau hapus kategori")
    manage_cat_action.triggered.connect(self.open_category_management_dialog)
    category_menu.addAction(manage_cat_action)

    settings_menu = menu_bar.addMenu("&Pengaturan")

    settings_action = QAction("&Buka Pengaturan...", self)
    settings_action.setShortcut(QKeySequence("Ctrl+,"))
    settings_action.setStatusTip("Atur folder Antigravity dan password enkripsi AES-256")
    settings_action.triggered.connect(self.open_settings_dialog)

    restore_action = QAction("Pulihkan &Backup Terakhir...", self)
    restore_action.setStatusTip("Pulihkan konfigurasi keyring atau file dari titik backup terakhir")
    restore_action.triggered.connect(self.restore_last_backup_with_confirmation)

    settings_menu.addAction(settings_action)
    settings_menu.addSeparator()
    settings_menu.addAction(restore_action)

    help_menu = menu_bar.addMenu("&Bantuan")

    about_action = QAction("&Tentang Aplikasi...", self)
    about_action.setShortcut(QKeySequence("F1"))
    about_action.setStatusTip("Informasi mengenai fitur aplikasi dan pengembang")
    about_action.triggered.connect(self.open_about_dialog)

    help_menu.addAction(about_action)

  def open_about_dialog(self):
    dialog = AboutDialog(self)
    dialog.exec()

  # ─── Helper: Jalankan task di background thread + tampilkan loading dialog ───

  def run_async_task(self, title: str, message: str, task_func, on_success, on_failed=None):
    """Menjalankan task berat di WorkerThread dengan menampilkan LoadingDialog modal."""
    dialog = LoadingDialog(self, title=title, message=message)
    worker = WorkerThread(task_func)
    self._current_worker = worker  # Simpan referensi agar tidak di-GC

    def handle_success(result):
      dialog.accept()
      QApplication.restoreOverrideCursor()
      if on_success:
        on_success(result)

    def handle_failed(err):
      dialog.reject()
      QApplication.restoreOverrideCursor()
      if on_failed:
        on_failed(err)
      else:
        QMessageBox.critical(self, "Error", f"Terjadi kesalahan:\n\n{str(err)}")

    worker.success.connect(handle_success)
    worker.failed.connect(handle_failed)

    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    worker.start()
    dialog.exec()

  # ─── Settings & Init ───

  def open_settings_dialog(self):
    dialog = SettingsDialog(self)
    if dialog.exec() == SettingsDialog.DialogCode.Accepted:
      folder = self.settings.value("antigravity_folder", "") or self.settings.value("opencode_folder", "")
      self.config_bar.set_folder_path(folder)
      self.config_bar.set_crypto_status(self._is_encryption_enabled())
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

    self.facade = create_facade(
        self.db,
        lambda: self.config_bar.get_folder_path(),
    )

  def _is_encryption_enabled(self) -> bool:
    val = self.settings.value("enable_encryption", False)
    if isinstance(val, str):
      return val.lower() in ("true", "1")
    return bool(val)

  def _get_encryption_password(self) -> str:
    return self.settings.value("aes256_password", "") or ""

  def load_settings(self):
    """Memuat folder, preferensi sorting, filter kategori, dan indikator enkripsi dari QSettings."""
    saved_folder = self.settings.value("antigravity_folder", "") or self.settings.value("opencode_folder", "")
    self.config_bar.set_folder_path(saved_folder)

    saved_sort = self.settings.value("sort_mode_index", 0, type=int)
    self.account_table.set_sort_index(saved_sort)

    saved_cat = self.settings.value("selected_category_filter", "__ALL__", type=str)
    self.account_table.set_selected_filter_category(saved_cat)

    self.config_bar.set_crypto_status(self._is_encryption_enabled())

  def _on_sort_mode_changed(self, index: int):
    self.settings.setValue("sort_mode_index", index)

  def _on_category_filter_changed(self, category_key: str):
    self.settings.setValue("selected_category_filter", category_key)

  def _on_target_changed(self, target: str):
    """Dipanggil saat target aktif diubah di ConfigBar."""
    if self.facade:
      try:
        overall_status = self.facade.read_status()
        self.config_bar.set_target_status(overall_status.get_status(target))
      except Exception:
        pass

  # ─── Reload Akun ───

  def reload_accounts(self):
    """Mengambil data akun terbaru dari database dengan loading indicator."""
    if not self.db:
      self.account_table.set_accounts_data([])
      self.json_input.set_categories([])
      return

    def task():
      rows = self.db.fetch_accounts_summary()
      cats = self.db.fetch_categories()
      overall_status = None
      if self.facade:
        try:
          overall_status = self.facade.read_status()
        except Exception:
          pass
      return rows, cats, overall_status

    def on_success(result):
      rows, cats, overall_status = result
      current_pwd = self._get_encryption_password()
      self.account_table.set_accounts_data(
          rows or [], current_password=current_pwd, overall_status=overall_status
      )
      self.json_input.set_categories(cats or [])
      if overall_status is not None:
        active_target = self.config_bar.get_active_target()
        self.config_bar.set_target_status(overall_status.get_status(active_target))

    def on_failed(e):
      self.account_table.set_accounts_data([], current_password="")
      self.json_input.set_categories([])
      use_turso_val = self.settings.value("use_turso", False)
      use_turso = (
          bool(use_turso_val)
          if not isinstance(use_turso_val, str)
          else use_turso_val.lower() in ("true", "1")
      )
      if use_turso:
        db_name = TursoClient.extract_db_name(self.settings.value("turso_url", ""))
        self.config_bar.set_db_status(
            use_turso=True,
            is_connected=False,
            db_name=db_name,
            error_msg=str(e),
        )

    self.run_async_task(
        "Memuat Data Akun",
        "Mengambil data akun dari database...",
        task,
        on_success,
        on_failed,
    )

  # ─── Simpan JSON ke Database ───

  def process_json(self, raw_text: str, category: str = ""):
    """Handler saat menyimpan JSON baru ke database."""
    if not raw_text:
      QMessageBox.warning(self, "Peringatan", "Area teks JSON masih kosong!")
      return

    encrypt = self._is_encryption_enabled()
    pwd = self._get_encryption_password()

    if encrypt and not pwd:
      QMessageBox.warning(
          self,
          "Password Enkripsi Belum Diatur",
          "Opsi enkripsi akun sedang aktif namun password enkripsi belum diatur!\n"
          "Silakan buka Menu Pengaturan untuk menyetel password enkripsi.",
      )
      self.open_settings_dialog()
      return

    # Validasi JSON terlebih dahulu di main thread sebelum menjalankan task
    try:
      json.loads(raw_text)
    except json.JSONDecodeError as e:
      QMessageBox.critical(self, "Error JSON", f"Format JSON tidak valid!\n\n{str(e)}")
      return

    def task():
      return self.db.insert_or_update_json(
          raw_text, encrypt=encrypt, password=pwd, category=category
      )

    def on_success(count):
      info_enc = " (Terenkripsi AES-256 — semua field sensitif terenkripsi)" if encrypt else ""
      cat_info = f" pada kategori '{category}'" if category else ""
      QMessageBox.information(
          self, "Sukses", f"Berhasil menyimpan {count} akun{cat_info}!{info_enc}"
      )
      self.json_input.clear_input()
      self.reload_accounts()

    def on_failed(e):
      QMessageBox.critical(self, "Database Error", f"Terjadi kesalahan:\n\n{str(e)}")

    msg = (
        "Mengenkripsi semua field sensitif dan menyimpan ke database..."
        if encrypt
        else "Menyimpan data akun ke database..."
    )
    self.run_async_task("Menyimpan Akun", msg, task, on_success, on_failed)

  def change_account_category(self, account_id: str, email: str, current_category: str):
    """Menampilkan dialog untuk mengubah atau memindahkan kategori akun."""
    if not self.db:
      return

    existing_cats = self.db.fetch_categories()
    items = ["(Tanpa Kategori)"] + [c for c in existing_cats if c]

    current_idx = 0
    if current_category and current_category in items:
      current_idx = items.index(current_category)

    new_cat_raw, ok = QInputDialog.getItem(
        self,
        "Ubah Kategori Akun",
        f"Pilih atau ketik kategori baru untuk:\n{email}",
        items,
        current_idx,
        True,
    )

    if not ok:
      return

    new_cat_str = new_cat_raw.strip()
    if new_cat_str == "(Tanpa Kategori)":
      new_cat_str = ""

    def task():
      return self.db.update_account_category(account_id, new_cat_str)

    def on_success(success):
      if success:
        if new_cat_str:
          msg = f"Kategori akun <b>{email}</b> berhasil diubah ke: <b>{new_cat_str}</b>"
        else:
          msg = f"Kategori akun <b>{email}</b> telah dikosongkan (Tanpa Kategori)."
        QMessageBox.information(self, "Kategori Diperbarui", msg)
        self.reload_accounts()
      else:
        QMessageBox.warning(self, "Gagal", "Gagal memperbarui kategori akun di database.")

    def on_failed(e):
      QMessageBox.critical(self, "Database Error", f"Terjadi kesalahan:\n\n{str(e)}")

    self.run_async_task(
        "Memperbarui Kategori",
        f"Memperbarui kategori {email}...",
        task,
        on_success,
        on_failed,
    )

  def bulk_change_account_category(self, account_ids: list):
    """Memindahkan beberapa akun yang dipilih sekaligus ke kategori lain."""
    if not self.db or not account_ids:
      return

    existing_cats = self.db.fetch_categories()
    items = ["(Tanpa Kategori)"] + [c for c in existing_cats if c]

    new_cat_raw, ok = QInputDialog.getItem(
        self,
        "Pindah Kategori Banyak Akun",
        f"Pilih atau ketik kategori baru untuk {len(account_ids)} akun terpilih:",
        items,
        0,
        True,
    )

    if not ok:
      return

    new_cat_str = new_cat_raw.strip()
    if new_cat_str == "(Tanpa Kategori)":
      new_cat_str = ""

    def task():
      return self.db.move_accounts_bulk(account_ids, new_cat_str)

    def on_success(affected):
      if new_cat_str:
        msg = f"Berhasil memindahkan <b>{affected}</b> akun ke kategori: <b>{new_cat_str}</b>"
      else:
        msg = f"Berhasil mengosongkan kategori (Tanpa Kategori) untuk <b>{affected}</b> akun."
      QMessageBox.information(self, "Kategori Diperbarui", msg)
      self.reload_accounts()

    def on_failed(e):
      QMessageBox.critical(self, "Database Error", f"Terjadi kesalahan saat memindahkan akun:\n\n{str(e)}")

    self.run_async_task(
        "Memindahkan Akun",
        f"Memindahkan {len(account_ids)} akun ke kategori baru...",
        task,
        on_success,
        on_failed,
    )

  def open_category_management_dialog(self):
    """Membuka dialog manajemen kategori (Ubah nama, Pindah banyak akun, Hapus kategori & akun)."""
    if not self.db:
      QMessageBox.warning(self, "Database Belum Siap", "Koneksi database belum tersedia.")
      return

    dialog = CategoryManagementDialog(self.db, self)
    dialog.categories_updated.connect(self.reload_accounts)
    dialog.exec()
    if dialog.has_changes:
      self.reload_accounts()

  # ─── Copy JSON ke Clipboard ───

  def copy_account_json(self, account_id: str):
    """Mendekripsi data akun dari database lalu menyalin JSON utuh ke clipboard."""
    pwd = self._get_encryption_password()

    def task():
      return self.db.reconstruct_json_by_id(account_id, password=pwd)

    def on_success(json_str):
      if json_str:
        QApplication.clipboard().setText(json_str)
        QMessageBox.information(
            self, "Disalin!", "Format JSON utuh berhasil disalin ke clipboard!"
        )
      else:
        QMessageBox.warning(
            self, "Gagal", "Gagal mengembalikan format JSON dari database."
        )

    def on_failed(e):
      if isinstance(e, ValueError):
        QMessageBox.critical(
            self,
            "Gagal Mendekripsi",
            f"Tidak dapat menyalin data akun:\n\n{str(e)}",
        )
      else:
        QMessageBox.critical(
            self, "Error", f"Terjadi kesalahan saat memproses data:\n\n{str(e)}"
        )

    self.run_async_task(
        "Menyiapkan Data",
        "Mendekripsi dan merekonstruksi format JSON...",
        task,
        on_success,
        on_failed,
    )

  # ─── Apply Akun ke Target (OpenCode / Antigravity CLI) ───

  def apply_account_to_target(self, account_id: str, target: str = ""):
    """Menerapkan akun ke target yang dipilih (atau active target jika target kosong)."""
    if not self.facade:
      QMessageBox.warning(self, "Layanan Belum Siap", "Layanan integrasi belum siap.")
      return

    effective_target = target if target else self.config_bar.get_active_target()
    pwd = self._get_encryption_password()
    auto_kill = self.settings.value("auto_kill_agy", False)
    if isinstance(auto_kill, str):
      auto_kill = auto_kill.lower() in ("true", "1")
    write_gemini = self.settings.value("write_gemini_files", True)
    if isinstance(write_gemini, str):
      write_gemini = write_gemini.lower() in ("true", "1")

    def plan_task():
      return self.facade.build_plan(
          account_id,
          effective_target,
          password=pwd,
          auto_kill_agy=auto_kill,
      )

    def on_plan_success(plan):
      if plan.error_code:
        full_msg = plan.error_message or "Plan tidak valid"
        QMessageBox.warning(self, "Gagal Menerapkan Akun", full_msg)
        return

      # Cek apakah butuh konfirmasi penghentian sesi agy
      allow_kill = False
      if plan.requires_confirmation and plan.detected_sessions:
        from src.ui.components.agy_session_dialog import AgyConfirmDialog
        confirm_dlg = AgyConfirmDialog(plan.detected_sessions, self, settings=self.settings)
        if confirm_dlg.exec() != QDialog.DialogCode.Accepted:
          return
        allow_kill = True
      elif auto_kill:
        allow_kill = True

      # Eksekusi Apply
      def apply_task():
        return self.facade.apply(
            plan,
            allow_kill=allow_kill,
            write_gemini_files=write_gemini,
            password=pwd,
        )

      def on_apply_success(apply_result):
        if not apply_result:
          return
        if apply_result.status.value == "CANCELLED":
          QMessageBox.information(self, "Dibatalkan", apply_result.user_message)
          return
        if apply_result.status.value == "FAILED":
          parts = [apply_result.user_message]
          if apply_result.action_suggestion:
            parts.append(apply_result.action_suggestion)
          if apply_result.backup_location:
            parts.append(f"Lokasi backup snapshot: {apply_result.backup_location}")
          full_msg = "\n\n".join(parts)
          QMessageBox.warning(self, "Gagal Menerapkan Akun", full_msg)
          return

        if apply_result.status.value == "SUCCESS":
          target_name = "OpenCode" if effective_target == "opencode" else "Antigravity CLI"
          accounts_cnt = apply_result.accounts_count
          count_str = f" ({accounts_cnt} akun di file)" if accounts_cnt is not None else ""
          backup_info = ""
          if apply_result.backup_location:
            backup_info = f"\n<br><small>Lokasi backup: {apply_result.backup_location}</small>"
          QMessageBox.information(
              self,
              "Berhasil Menerapkan Akun",
              f"Akun <b>{apply_result.email}</b> berhasil diterapkan ke <b>{target_name}</b>{count_str}!{backup_info}",
          )
          self.reload_accounts()

      def on_apply_failed(e):
        QMessageBox.critical(self, "Error", f"Terjadi kesalahan saat menerapkan akun:\n\n{str(e)}")

      self.run_async_task(
          "Menerapkan Akun",
          f"Menerapkan akun ke {effective_target}...",
          apply_task,
          on_apply_success,
          on_apply_failed,
      )

    def on_plan_failed(e):
      QMessageBox.critical(self, "Error", f"Terjadi kesalahan saat memeriksa akun:\n\n{str(e)}")

    self.run_async_task(
        "Menyiapkan Akun",
        f"Memeriksa akun dan memvalidasi token...",
        plan_task,
        on_plan_success,
        on_plan_failed,
    )

  # ─── Restore Backup Terakhir ───

  def restore_last_backup_with_confirmation(self):
    """Memulihkan backup terakhir setelah konfirmasi yang transparan mengenai kredensial."""
    from src.integrations.antigravity.backup import get_latest_backup
    import datetime

    latest = get_latest_backup()
    if not latest:
      QMessageBox.information(
          self,
          "Tidak Ada Backup",
          "Belum ada backup snapshot yang tersimpan untuk dipulihkan.",
      )
      return

    backup_dir, meta = latest
    target = meta.get("target", "opencode")
    email = meta.get("email", "-")
    timestamp = meta.get("timestamp", 0)
    target_name = "OpenCode" if target == "opencode" else "Antigravity CLI"

    try:
      time_str = datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
      time_str = str(timestamp)

    msg = (
        f"Apakah Anda yakin ingin memulihkan backup snapshot berikut?\n\n"
        f"• <b>Target:</b> {target_name}\n"
        f"• <b>Email:</b> {email}\n"
        f"• <b>Waktu Backup:</b> {time_str}\n"
        f"• <b>Lokasi:</b> {backup_dir}\n\n"
        f"<i>Peringatan: Backup ini berisi data kredensial akun dan hanya dapat diakses oleh pengguna pemilik. "
        f"Memulihkan backup akan mengembalikan kondisi konfigurasi/keyring ke titik tersebut.</i>"
    )

    confirm = QMessageBox.question(
        self,
        "Konfirmasi Pulihkan Backup Terakhir",
        msg,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if confirm != QMessageBox.StandardButton.Yes:
      return

    def task():
      return self.facade.restore_last_backup()

    def on_success(res):
      if res and res.status.value == "SUCCESS":
        QMessageBox.information(
            self,
            "Pulihkan Backup Berhasil",
            res.message or "Backup berhasil dipulihkan.",
        )
        self.reload_accounts()
      else:
        err = res.error if res else "Terjadi kesalahan"
        QMessageBox.warning(
            self,
            "Gagal Memulihkan Backup",
            f"Gagal memulihkan backup:\n\n{err}",
        )

    def on_failed(e):
      QMessageBox.critical(
          self,
          "Error Pulihkan Backup",
          f"Terjadi kesalahan saat memulihkan backup:\n\n{str(e)}",
      )

    self.run_async_task(
        "Memulihkan Backup",
        "Mengembalikan file dan konfigurasi dari backup terakhir...",
        task,
        on_success,
        on_failed,
    )

  # ─── Update File Antigravity dari Database ───

  def update_antigravity_file(self, account_id: str, email: str):
    """Menulis data akun dari database langsung ke file antigravity-accounts.json."""
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

    if confirm != QMessageBox.StandardButton.Yes:
      return

    pwd = self._get_encryption_password()

    def task():
      raw_json_str = self.db.reconstruct_json_by_id(account_id, password=pwd)
      if not raw_json_str:
        raise ValueError("Data akun tidak ditemukan di database.")
      new_data = json.loads(raw_json_str)
      with open(target_file, "w", encoding="utf-8") as f:
        json.dump(new_data, f, indent=2)
      return True

    def on_success(_):
      QMessageBox.information(
          self,
          "Berhasil",
          f"File <b>antigravity-accounts.json</b> berhasil ditimpa total"
          f" dengan akun:\n{email}",
      )

    def on_failed(e):
      if isinstance(e, ValueError):
        QMessageBox.critical(
            self,
            "Gagal Mendekripsi Akun",
            f"Tidak dapat menulis ke file Antigravity:\n\n{str(e)}",
        )
      else:
        QMessageBox.critical(
            self,
            "Gagal Menulis File",
            f"Terjadi kesalahan saat menulis file:\n\n{str(e)}",
        )

    self.run_async_task(
        "Memperbarui File",
        "Mendekripsi data dan memperbarui antigravity-accounts.json...",
        task,
        on_success,
        on_failed,
    )

  # ─── Update Database dari File Antigravity ───

  def update_db_from_antigravity(self, account_id: str, email: str):
    """Membaca file antigravity-accounts.json lalu memperbarui data akun di database."""
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

    # Baca & validasi file di main thread sebelum menampilkan konfirmasi
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
      QMessageBox.critical(self, "Gagal Membaca File", f"Gagal membaca file:\n\n{str(e)}")
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
        file_acc.get("email", "Tidak Diketahui") if isinstance(file_acc, dict) else "Tidak Diketahui"
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

    if confirm != QMessageBox.StandardButton.Yes:
      return

    encrypt = self._is_encryption_enabled()
    pwd = self._get_encryption_password()
    if encrypt and not pwd:
      QMessageBox.warning(
          self,
          "Password Enkripsi Belum Diatur",
          "Opsi enkripsi akun sedang aktif namun password enkripsi belum diatur!\n"
          "Silakan atur password di Menu Pengaturan.",
      )
      self.open_settings_dialog()
      return

    def task():
      return self.db.insert_or_update_json(content, encrypt=encrypt, password=pwd)

    def on_success(_):
      info_enc = " (Terenkripsi AES-256 — semua field sensitif terenkripsi)" if encrypt else ""
      QMessageBox.information(
          self,
          "Berhasil Update Database",
          f"Berhasil mengonfirmasi & memperbarui data akun ke database!{info_enc}",
      )
      self.reload_accounts()

    def on_failed(e):
      QMessageBox.critical(
          self,
          "Database Error",
          f"Terjadi kesalahan saat memperbarui database:\n\n{str(e)}",
      )

    msg = (
        "Mengenkripsi semua field sensitif dan memperbarui database..."
        if encrypt
        else "Memperbarui data akun di database..."
    )
    self.run_async_task("Update Database", msg, task, on_success, on_failed)

  # ─── Hapus Akun ───

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

    if confirm != QMessageBox.StandardButton.Yes:
      return

    def task():
      return self.db.delete_account(account_id)

    def on_success(success):
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

    def on_failed(e):
      QMessageBox.critical(
          self,
          "Database Error",
          f"Terjadi kesalahan saat menghapus data:\n\n{str(e)}",
      )

    self.run_async_task(
        "Menghapus Akun",
        f"Menghapus akun {email} dari database...",
        task,
        on_success,
        on_failed,
    )

  # ─── Refresh Quota (Gemini & Claude) ───

  def _extract_account_dict(self, account_id: str, password: str = "") -> dict:
    """Helper untuk merekonstruksi dan mengembalikan dictionary akun pertama dari database."""
    raw_json = self.db.reconstruct_json_by_id(account_id, password=password)
    if not raw_json:
      raise ValueError("Data akun tidak ditemukan di database.")
    data = json.loads(raw_json)
    if isinstance(data, list) and len(data) > 0:
      acc = data[0]
    elif isinstance(data, dict):
      accs = data.get("accounts", [])
      acc = accs[0] if (isinstance(accs, list) and len(accs) > 0) else data
    else:
      raise ValueError("Format JSON akun tidak valid.")

    if "refreshToken" not in acc and "refresh_token" in acc:
      acc["refreshToken"] = acc["refresh_token"]
    if "projectId" not in acc and "project_id" in acc:
      acc["projectId"] = acc["project_id"]
    return acc

  def refresh_account_quota(self, account_id: str, email: str):
    """Mengambil kuota terbaru dari backend Google Cloud Code dan menyimpannya ke database & tabel."""
    from src.integrations.antigravity.quota_service import fetch_account_quota

    enc_pw = self._get_encryption_password()

    def task():
      acc_data = self._extract_account_dict(account_id, password=enc_pw)
      rt = acc_data.get("refreshToken")
      pid = acc_data.get("projectId") or "aicode-consumers"
      if not rt:
        raise ValueError("Akun tidak memiliki refreshToken yang valid.")

      quotas = fetch_account_quota(rt, project_id=pid)
      if not quotas:
        raise ValueError("Server tidak mengembalikan informasi kuota untuk akun ini.")

      self.db.update_account_quotas(account_id, quotas)
      return quotas

    def on_success(quotas):
      self.account_table.update_row_quota_cells(account_id, quotas)
      # Reload akun agar seluruh cache & sorting internal ter-update
      self.reload_accounts()
      QMessageBox.information(
          self,
          "Kuota Diperbarui",
          f"Kuota model Gemini & Claude untuk akun <b>{email}</b> berhasil diperbarui!",
      )

    def on_failed(e):
      QMessageBox.critical(
          self,
          "Gagal Memperbarui Kuota",
          f"Terjadi kesalahan saat memperbarui kuota untuk <b>{email}</b>:\n\n{str(e)}",
      )

    self.run_async_task(
        "Memperbarui Kuota",
        f"Mengambil sisa kuota Gemini & Claude untuk {email}...\nMohon tunggu beberapa saat.",
        task,
        on_success,
        on_failed,
    )

  def bulk_refresh_account_quotas(self, account_list: list):
    """Memperbarui kuota untuk sejumlah akun terpilih secara berurutan di background."""
    from src.integrations.antigravity.quota_service import fetch_account_quota

    enc_pw = self._get_encryption_password()

    def task():
      results = []
      for acc_id, email in account_list:
        try:
          acc_data = self._extract_account_dict(acc_id, password=enc_pw)
          rt = acc_data.get("refreshToken")
          if not rt:
            results.append((acc_id, email, False, "Refresh token tidak tersedia"))
            continue
          pid = acc_data.get("projectId") or "aicode-consumers"
          quotas = fetch_account_quota(rt, project_id=pid)
          if not quotas:
            results.append((acc_id, email, False, "Data kuota kosong"))
            continue
          self.db.update_account_quotas(acc_id, quotas)
          results.append((acc_id, email, True, quotas))
        except Exception as ex:
          results.append((acc_id, email, False, str(ex)))
      return results

    def on_success(results):
      success_count = 0
      failed_details = []
      for acc_id, email, ok, payload in results:
        if ok:
          success_count += 1
          self.account_table.update_row_quota_cells(acc_id, payload)
        else:
          failed_details.append(f"• {email}: {payload}")

      self.reload_accounts()
      msg = f"Berhasil memperbarui {success_count} dari {len(account_list)} akun."
      if failed_details:
        msg += "\n\nCatatan / Kendala:\n" + "\n".join(failed_details[:5])
        if len(failed_details) > 5:
          msg += f"\n...dan {len(failed_details) - 5} lainnya."
        QMessageBox.warning(self, "Pembaruan Kuota Selesai", msg)
      else:
        QMessageBox.information(self, "Pembaruan Kuota Selesai", msg)

    self.run_async_task(
        "Memperbarui Kuota Masal",
        f"Memperbarui kuota {len(account_list)} akun terpilih...\nMohon tunggu beberapa saat.",
        task,
        on_success,
    )

  def refresh_all_accounts_quota(self):
    """Memperbarui kuota untuk SEMUA akun yang ada di database secara otomatis."""
    if not self.db:
      return

    rows = self.db.fetch_accounts_summary()
    if not rows:
      QMessageBox.information(
          self,
          "Daftar Akun Kosong",
          "Belum ada akun yang tersimpan di database.",
      )
      return

    # Siapkan daftar (account_id, email)
    all_accounts = [(r[0], r[1]) for r in rows if r and len(r) > 1]

    confirm = QMessageBox.question(
        self,
        "Konfirmasi Perbarui Semua Kuota",
        f"Apakah Anda ingin memperbarui kuota Gemini & Claude untuk seluruh <b>{len(all_accounts)} akun</b> di database?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    if confirm != QMessageBox.StandardButton.Yes:
      return

    from src.integrations.antigravity.quota_service import fetch_account_quota

    enc_pw = self._get_encryption_password()

    def task():
      results = []
      total = len(all_accounts)
      for idx, (acc_id, email) in enumerate(all_accounts):
        try:
          acc_data = self._extract_account_dict(acc_id, password=enc_pw)
          rt = acc_data.get("refreshToken")
          if not rt:
            results.append((acc_id, email, False, "Refresh token tidak tersedia"))
            continue
          pid = acc_data.get("projectId") or "aicode-consumers"
          quotas = fetch_account_quota(rt, project_id=pid)
          if not quotas:
            results.append((acc_id, email, False, "Data kuota kosong"))
            continue
          self.db.update_account_quotas(acc_id, quotas)
          results.append((acc_id, email, True, quotas))
        except Exception as ex:
          results.append((acc_id, email, False, str(ex)))
      return results

    def on_success(results):
      success_count = 0
      failed_details = []
      for acc_id, email, ok, payload in results:
        if ok:
          success_count += 1
          self.account_table.update_row_quota_cells(acc_id, payload)
        else:
          failed_details.append(f"• {email}: {payload}")

      self.reload_accounts()
      msg = f"Selesai! Berhasil memperbarui {success_count} dari {len(all_accounts)} akun."
      if failed_details:
        msg += "\n\nCatatan / Akun dengan kendala:\n" + "\n".join(failed_details[:6])
        if len(failed_details) > 6:
          msg += f"\n...dan {len(failed_details) - 6} lainnya."
        QMessageBox.warning(self, "Pembaruan Semua Kuota Selesai", msg)
      else:
        QMessageBox.information(self, "Pembaruan Semua Kuota Sukses", msg)

    self.run_async_task(
        "Memperbarui Semua Kuota",
        f"Sedang memperbarui kuota {len(all_accounts)} akun di database...\nMohon tunggu beberapa saat.",
        task,
        on_success,
    )
