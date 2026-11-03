import json
import os

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.database import AccountDatabase
from src.ui.utils import parse_quota_info


class MainWindow(QMainWindow):

  def __init__(self):
    super().__init__()
    self.db = AccountDatabase()
    self.settings = QSettings("OpenCodeApp", "AccountManager")
    self.init_ui()
    self.load_settings()
    self.load_table_data()

  def init_ui(self):
    self.setWindowTitle("JSON Account Manager (PyQt6)")
    self.resize(1100, 700)

    main_widget = QWidget()
    self.setCentralWidget(main_widget)
    main_layout = QVBoxLayout(main_widget)

    # ------------------------------------------
    # BAGIAN ATAS: FOLDER CONFIG & CONTROL BAR
    # ------------------------------------------
    config_layout = QHBoxLayout()

    label_folder = QLabel("<b>Folder OpenCode Config:</b>")
    self.txt_folder_path = QLineEdit()
    self.txt_folder_path.setReadOnly(True)
    self.txt_folder_path.setPlaceholderText("Belum ada folder yang dipilih...")

    btn_browse = QPushButton("Pilih Folder...")
    btn_browse.setStyleSheet("padding: 4px 10px;")
    btn_browse.clicked.connect(self.select_opencode_folder)

    config_layout.addWidget(label_folder)
    config_layout.addWidget(self.txt_folder_path)
    config_layout.addWidget(btn_browse)

    main_layout.addLayout(config_layout)

    # Splitter untuk Input JSON dan Tabel
    splitter = QSplitter(Qt.Orientation.Vertical)

    # ------------------------------------------
    # BAGIAN TENGAH: INPUT JSON
    # ------------------------------------------
    top_widget = QWidget()
    top_layout = QVBoxLayout(top_widget)
    top_layout.setContentsMargins(0, 5, 0, 0)

    label_input = QLabel("<b>Paste JSON Akun di Sini:</b>")
    self.json_input = QTextEdit()
    self.json_input.setPlaceholderText("Paste teks JSON...")

    btn_layout = QHBoxLayout()
    self.btn_save = QPushButton("Simpan ke Database SQLite")
    self.btn_save.setStyleSheet(
        "background-color: #2b5c8f; color: white; font-weight: bold; padding:"
        " 6px;"
    )
    self.btn_save.clicked.connect(self.process_json)

    self.btn_clear = QPushButton("Bersihkan Input")
    self.btn_clear.clicked.connect(lambda: self.json_input.clear())

    btn_layout.addWidget(self.btn_save)
    btn_layout.addWidget(self.btn_clear)

    top_layout.addWidget(label_input)
    top_layout.addWidget(self.json_input)
    top_layout.addLayout(btn_layout)

    # ------------------------------------------
    # BAGIAN BAWAH: TABEL & CONTROL SORTING
    # ------------------------------------------
    bottom_widget = QWidget()
    bottom_layout = QVBoxLayout(bottom_widget)
    bottom_layout.setContentsMargins(0, 5, 0, 0)

    # Bar Pengurutan (Sorting Bar)
    sort_layout = QHBoxLayout()
    label_table = QLabel(
        "<b>Daftar Akun:</b> (Klik kanan pada baris untuk menu aksi)"
    )

    label_sort = QLabel("<b>Urutkan Berdasarkan:</b>")
    self.cmb_sort_mode = QComboBox()
    self.cmb_sort_mode.addItems([
        "Email (A-Z)",
        "Email (Z-A)",
        "Reset Time Tercepat",
        "Token Terbanyak (Flash)",
        "Token Tersedikit (Flash)",
        "Token Terbanyak (Pro)",
        "Token Tersedikit (Pro)",
        "Token Terbanyak (Claude)",
        "Token Tersedikit (Claude)",
    ])
    self.cmb_sort_mode.currentIndexChanged.connect(self.on_sort_changed)

    sort_layout.addWidget(label_table)
    sort_layout.addStretch()
    sort_layout.addWidget(label_sort)
    sort_layout.addWidget(self.cmb_sort_mode)

    self.table = QTableWidget()
    self.table.setColumnCount(4)
    self.table.setHorizontalHeaderLabels([
        "Email",
        "Flash Quota (Reset)",
        "Pro Quota (Reset)",
        "Claude Quota (Reset)",
    ])
    self.table.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.Stretch
    )
    self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    self.table.customContextMenuRequested.connect(self.show_context_menu)

    bottom_layout.addLayout(sort_layout)
    bottom_layout.addWidget(self.table)

    splitter.addWidget(top_widget)
    splitter.addWidget(bottom_widget)
    splitter.setSizes([150, 450])

    main_layout.addWidget(splitter)

  def select_opencode_folder(self):
    """Membuka dialog pemilih folder dan menyimpannya di QSettings."""
    current_dir = self.txt_folder_path.text() or ""
    folder = QFileDialog.getExistingDirectory(
        self, "Pilih Folder OpenCode Config", current_dir
    )
    if folder:
      self.txt_folder_path.setText(folder)
      self.settings.setValue("opencode_folder", folder)

  def load_settings(self):
    """Memuat folder dan preferensi sorting yang tersimpan dari QSettings."""
    saved_folder = self.settings.value("opencode_folder", "")
    if saved_folder:
      self.txt_folder_path.setText(saved_folder)

    saved_sort = self.settings.value("sort_mode_index", 0, type=int)
    if 0 <= saved_sort < self.cmb_sort_mode.count():
      self.cmb_sort_mode.setCurrentIndex(saved_sort)

  def on_sort_changed(self, index):
    """Simpan pilihan pengurutan ke QSettings dan muat ulang tabel."""
    self.settings.setValue("sort_mode_index", index)
    self.load_table_data()

  def process_json(self):
    """Handler saat menyimpan JSON baru."""
    raw_text = self.json_input.toPlainText().strip()
    if not raw_text:
      QMessageBox.warning(self, "Peringatan", "Area teks JSON masih kosong!")
      return

    try:
      count = self.db.insert_or_update_json(raw_text)
      QMessageBox.information(
          self, "Sukses", f"Berhasil menyimpan {count} akun!"
      )
      self.json_input.clear()
      self.load_table_data()
    except json.JSONDecodeError as e:
      QMessageBox.critical(
          self, "Error JSON", f"Format JSON tidak valid!\n\n{str(e)}"
      )
    except Exception as e:
      QMessageBox.critical(
          self, "Database Error", f"Terjadi kesalahan:\n\n{str(e)}"
      )

  def load_table_data(self):
    """Memuat daftar akun ke dalam tabel dan menerapkan logika pengurutan."""
    rows = self.db.fetch_accounts_summary()
    parsed_list = []

    # Parse semua baris data terlebih dahulu
    for row_data in rows:
      (
          acc_id,
          email,
          flash_reset,
          flash_frac,
          pro_reset,
          pro_frac,
          claude_reset,
          claude_frac,
      ) = row_data

      p_flash = parse_quota_info(flash_frac, flash_reset)
      p_pro = parse_quota_info(pro_frac, pro_reset)
      p_claude = parse_quota_info(claude_frac, claude_reset)

      # Hitung timestamp reset tercepat (di antara 3 model)
      min_reset_ts = min(p_flash[4], p_pro[4], p_claude[4])

      parsed_list.append({
          "acc_id": acc_id,
          "email": email or "-",
          "flash": p_flash,
          "pro": p_pro,
          "claude": p_claude,
          "min_reset_ts": min_reset_ts,
      })

    # Logika Pengurutan
    sort_mode = self.cmb_sort_mode.currentText()
    if sort_mode == "Email (A-Z)":
      parsed_list.sort(key=lambda x: x["email"].lower())
    elif sort_mode == "Email (Z-A)":
      parsed_list.sort(key=lambda x: x["email"].lower(), reverse=True)
    elif sort_mode == "Reset Time Tercepat":
      parsed_list.sort(key=lambda x: x["min_reset_ts"])
    elif sort_mode == "Token Terbanyak (Flash)":
      parsed_list.sort(
          key=lambda x: (
              x["flash"][3] if x["flash"][3] is not None else -1
          ),
          reverse=True,
      )
    elif sort_mode == "Token Tersedikit (Flash)":
      parsed_list.sort(
          key=lambda x: (
              x["flash"][3] if x["flash"][3] is not None else 999
          )
      )
    elif sort_mode == "Token Terbanyak (Pro)":
      parsed_list.sort(
          key=lambda x: (x["pro"][3] if x["pro"][3] is not None else -1),
          reverse=True,
      )
    elif sort_mode == "Token Tersedikit (Pro)":
      parsed_list.sort(
          key=lambda x: (x["pro"][3] if x["pro"][3] is not None else 999)
      )
    elif sort_mode == "Token Terbanyak (Claude)":
      parsed_list.sort(
          key=lambda x: (
              x["claude"][3] if x["claude"][3] is not None else -1
          ),
          reverse=True,
      )
    elif sort_mode == "Token Tersedikit (Claude)":
      parsed_list.sort(
          key=lambda x: (
              x["claude"][3] if x["claude"][3] is not None else 999
          )
      )

    # Tampilkan ke QTableWidget
    self.table.setRowCount(0)
    for row_idx, item_data in enumerate(parsed_list):
      self.table.insertRow(row_idx)

      p_flash = item_data["flash"]
      p_pro = item_data["pro"]
      p_claude = item_data["claude"]

      row_has_reset = p_flash[1] or p_pro[1] or p_claude[1]

      item_email = QTableWidgetItem(item_data["email"])
      item_email.setData(Qt.ItemDataRole.UserRole, item_data["acc_id"])

      item_flash = QTableWidgetItem(p_flash[0])
      item_flash.setForeground(QBrush(QColor(p_flash[2])))

      item_pro = QTableWidgetItem(p_pro[0])
      item_pro.setForeground(QBrush(QColor(p_pro[2])))

      item_claude = QTableWidgetItem(p_claude[0])
      item_claude.setForeground(QBrush(QColor(p_claude[2])))

      items = [item_email, item_flash, item_pro, item_claude]

      for c, item in enumerate(items):
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if row_has_reset:
          item.setBackground(QBrush(QColor("#ffcdd2")))
          font = item.font()
          font.setBold(True)
          item.setFont(font)
        self.table.setItem(row_idx, c, item)

  def show_context_menu(self, pos):
    """Menampilkan menu konteks saat pengguna klik kanan pada baris tabel."""
    item = self.table.itemAt(pos)
    if not item:
      return

    row = item.row()
    account_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
    email = self.table.item(row, 0).text()

    menu = QMenu(self)
    action_copy = menu.addAction("  Copy JSON")
    action_update_file = menu.addAction("  Update ke antigravity-accounts.json")
    action_update_db = menu.addAction(
        "  Update Database dari antigravity-accounts.json"
    )
    menu.addSeparator()
    action_delete = menu.addAction("  Hapus Akun")

    chosen_action = menu.exec(self.table.viewport().mapToGlobal(pos))
    if chosen_action == action_copy:
      self.copy_account_json(account_id)
    elif chosen_action == action_update_file:
      self.update_antigravity_file(account_id, email)
    elif chosen_action == action_update_db:
      self.update_db_from_antigravity(account_id, email)
    elif chosen_action == action_delete:
      self.delete_account_with_confirmation(account_id, email)

  def copy_account_json(self, account_id):
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

  def update_antigravity_file(self, account_id, email):
    folder_path = self.txt_folder_path.text().strip()
    if not folder_path or not os.path.exists(folder_path):
      QMessageBox.warning(
          self,
          "Folder Tidak Valid",
          "Silakan pilih folder OpenCode Config terlebih dahulu!",
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

  def update_db_from_antigravity(self, account_id, email):
    folder_path = self.txt_folder_path.text().strip()
    if not folder_path or not os.path.exists(folder_path):
      QMessageBox.warning(
          self,
          "Folder Tidak Valid",
          "Silakan pilih folder OpenCode Config terlebih dahulu!",
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
        count = self.db.insert_or_update_json(content)
        QMessageBox.information(
            self,
            "Berhasil Update Database",
            "Berhasil mengonfirmasi & memperbarui data akun ke database!",
        )
        self.load_table_data()
      except Exception as e:
        QMessageBox.critical(
            self,
            "Database Error",
            f"Terjadi kesalahan saat memperbarui database:\n\n{str(e)}",
        )

  def delete_account_with_confirmation(self, account_id, email):
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
          self.load_table_data()
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