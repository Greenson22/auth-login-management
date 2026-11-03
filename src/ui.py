import os
import json
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QHeaderView, QMessageBox, QSplitter, QFileDialog, QLineEdit, QMenu
)
from PyQt6.QtCore import Qt, QSettings
from src.database import AccountDatabase


def format_quota_info(remaining_fraction, reset_time):
    """
    Mengformat persentase kuota dan tanggal reset time.
    Contoh output: "100% (-)" atau "50% (04 Nov 2026, 12:30)"
    """
    # 1. Format Persentase Quota
    if remaining_fraction is None:
        percentage_str = "-"
    else:
        try:
            percent = int(float(remaining_fraction) * 100)
            percentage_str = f"{percent}%"
        except (ValueError, TypeError):
            percentage_str = "-"

    # 2. Format Reset Time
    if not reset_time or reset_time == "-":
        formatted_time = "-"
    else:
        try:
            if str(reset_time).isdigit() or isinstance(reset_time, (int, float)):
                ts = float(reset_time)
                if ts > 1e11:  # Milidetik
                    ts /= 1000.0
                dt = datetime.fromtimestamp(ts)
            else:
                clean_str = reset_time.replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean_str)
                
            formatted_time = dt.strftime("%d %b %Y, %H:%M")
        except Exception:
            formatted_time = str(reset_time)

    if percentage_str == "-" and formatted_time == "-":
        return "-"
    
    return f"{percentage_str} ({formatted_time})"


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
        self.resize(1050, 650)
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # ------------------------------------------
        # BAGIAN ATAS: PENGATURAN FOLDER OPENCODE CONFIG
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
        self.json_input.setPlaceholderText('Paste teks JSON...')

        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("Simpan ke Database SQLite")
        self.btn_save.setStyleSheet("background-color: #2b5c8f; color: white; font-weight: bold; padding: 6px;")
        self.btn_save.clicked.connect(self.process_json)

        self.btn_clear = QPushButton("Bersihkan Input")
        self.btn_clear.clicked.connect(lambda: self.json_input.clear())

        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_clear)

        top_layout.addWidget(label_input)
        top_layout.addWidget(self.json_input)
        top_layout.addLayout(btn_layout)

        # ------------------------------------------
        # BAGIAN BAWAH: TABEL
        # ------------------------------------------
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 5, 0, 0)

        label_table = QLabel("<b>Daftar Akun:</b> (Klik kanan pada baris untuk menu aksi)")
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            "Email", "Flash Quota (Reset)", "Pro Quota (Reset)", "Claude Quota (Reset)"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        
        # Aktifkan Custom Context Menu (Klik Kanan)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        bottom_layout.addWidget(label_table)
        bottom_layout.addWidget(self.table)

        splitter.addWidget(top_widget)
        splitter.addWidget(bottom_widget)
        splitter.setSizes([160, 440])

        main_layout.addWidget(splitter)

    def select_opencode_folder(self):
        """Membuka dialog pemilih folder dan menyimpannya di QSettings."""
        current_dir = self.txt_folder_path.text() or ""
        folder = QFileDialog.getExistingDirectory(self, "Pilih Folder OpenCode Config", current_dir)
        if folder:
            self.txt_folder_path.setText(folder)
            self.settings.setValue("opencode_folder", folder)

    def load_settings(self):
        """Memuat folder yang tersimpan dari QSettings."""
        saved_folder = self.settings.value("opencode_folder", "")
        if saved_folder:
            self.txt_folder_path.setText(saved_folder)

    def process_json(self):
        """Handler saat menyimpan JSON baru."""
        raw_text = self.json_input.toPlainText().strip()
        if not raw_text:
            QMessageBox.warning(self, "Peringatan", "Area teks JSON masih kosong!")
            return

        try:
            count = self.db.insert_or_update_json(raw_text)
            QMessageBox.information(self, "Sukses", f"Berhasil menyimpan {count} akun!")
            self.json_input.clear()
            self.load_table_data()
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "Error JSON", f"Format JSON tidak valid!\n\n{str(e)}")
        except Exception as e:
            QMessageBox.critical(self, "Database Error", f"Terjadi kesalahan:\n\n{str(e)}")

    def load_table_data(self):
        """Memuat daftar akun ke dalam tabel."""
        rows = self.db.fetch_accounts_summary()
        self.table.setRowCount(0)

        for row_idx, row_data in enumerate(rows):
            acc_id, email, flash_reset, flash_frac, pro_reset, pro_frac, claude_reset, claude_frac = row_data
            self.table.insertRow(row_idx)

            item_email = QTableWidgetItem(email or "-")
            # Simpan account_id di UserRole item email agar bisa diambil saat klik kanan
            item_email.setData(Qt.ItemDataRole.UserRole, acc_id)

            self.table.setItem(row_idx, 0, item_email)
            self.table.setItem(row_idx, 1, QTableWidgetItem(format_quota_info(flash_frac, flash_reset)))
            self.table.setItem(row_idx, 2, QTableWidgetItem(format_quota_info(pro_frac, pro_reset)))
            self.table.setItem(row_idx, 3, QTableWidgetItem(format_quota_info(claude_frac, claude_reset)))

            for c in range(4):
                item = self.table.item(row_idx, c)
                if item:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

    def show_context_menu(self, pos):
        """Menampilkan menu konteks saat pengguna klik kanan pada baris tabel."""
        item = self.table.itemAt(pos)
        if not item:
            return

        row = item.row()
        account_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        email = self.table.item(row, 0).text()

        menu = QMenu(self)
        action_copy = menu.addAction("📋 Copy JSON")
        action_update_file = menu.addAction("🔄 Update ke antigravity-accounts.json")
        action_update_db = menu.addAction("📥 Update Database dari antigravity-accounts.json")

        # Eksekusi menu
        chosen_action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen_action == action_copy:
            self.copy_account_json(account_id)
        elif chosen_action == action_update_file:
            self.update_antigravity_file(account_id, email)
        elif chosen_action == action_update_db:
            self.update_db_from_antigravity(account_id, email)

    def copy_account_json(self, account_id):
        """Merekonstruksi JSON asli dari database lalu menyalinnya ke Clipboard."""
        json_str = self.db.reconstruct_json_by_id(account_id)
        if json_str:
            QApplication.clipboard().setText(json_str)
            QMessageBox.information(self, "Disalin!", "Format JSON utuh berhasil disalin ke clipboard!")
        else:
            QMessageBox.warning(self, "Gagal", "Gagal mengembalikan format JSON dari database.")

    def update_antigravity_file(self, account_id, email):
        """Memperbarui file antigravity-accounts.json di folder config yang dipilih."""
        folder_path = self.txt_folder_path.text().strip()

        # Peringatan 1: Folder belum dipilih
        if not folder_path or not os.path.exists(folder_path):
            QMessageBox.warning(
                self, 
                "Folder Tidak Valid", 
                "Silakan pilih folder OpenCode Config terlebih dahulu pada bagian atas!"
            )
            return

        target_file = os.path.join(folder_path, "antigravity-accounts.json")

        # Peringatan 2: File target tidak ditemukan
        if not os.path.exists(target_file):
            QMessageBox.warning(
                self,
                "File Tidak Ditemukan",
                f"File target <b>antigravity-accounts.json</b> tidak ditemukan di folder:\n{folder_path}"
            )
            return

        # Konfirmasi Pengguna
        confirm = QMessageBox.question(
            self,
            "Konfirmasi Update File",
            f"Apakah Anda yakin ingin menimpa isi file:\n<b>{target_file}</b>\n\ndengan data akun dari database untuk <b>{email}</b>?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if confirm == QMessageBox.StandardButton.Yes:
            json_str = self.db.reconstruct_json_by_id(account_id)
            if not json_str:
                QMessageBox.critical(self, "Error", "Gagal mengambil data akun dari database.")
                return

            try:
                with open(target_file, "w", encoding="utf-8") as f:
                    f.write(json_str)
                QMessageBox.information(
                    self,
                    "Berhasil",
                    f"File <b>antigravity-accounts.json</b> berhasil diperbarui dengan akun:\n{email}"
                )
            except Exception as e:
                QMessageBox.critical(self, "Gagal Menulis File", f"Terjadi kesalahan saat menulis file:\n\n{str(e)}")

    def update_db_from_antigravity(self, account_id, email):
        """Membaca isi antigravity-accounts.json dan memperbarui data akun terpilih di database."""
        folder_path = self.txt_folder_path.text().strip()

        # Peringatan 1: Folder belum dipilih
        if not folder_path or not os.path.exists(folder_path):
            QMessageBox.warning(
                self,
                "Folder Tidak Valid",
                "Silakan pilih folder OpenCode Config terlebih dahulu pada bagian atas!"
            )
            return

        target_file = os.path.join(folder_path, "antigravity-accounts.json")

        # Peringatan 2: File tidak ditemukan
        if not os.path.exists(target_file):
            QMessageBox.warning(
                self,
                "File Tidak Ditemukan",
                f"File <b>antigravity-accounts.json</b> tidak ditemukan di folder:\n{folder_path}"
            )
            return

        # Read & Parse File JSON
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    QMessageBox.warning(self, "File Kosong", "File <b>antigravity-accounts.json</b> kosong!")
                    return
                file_data = json.loads(content)
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "Error JSON File", f"Format file antigravity-accounts.json tidak valid!\n\n{str(e)}")
            return
        except Exception as e:
            QMessageBox.critical(self, "Gagal Membaca File", f"Gagal membaca file:\n\n{str(e)}")
            return

        # Ambil ID Akun dari file JSON (bisa berupa object atau array)
        file_acc = file_data.get("accounts", [file_data])[0] if isinstance(file_data, dict) and "accounts" in file_data else file_data
        if isinstance(file_acc, list) and len(file_acc) > 0:
            file_acc = file_acc[0]

        file_acc_id = file_acc.get("id") if isinstance(file_acc, dict) else None
        file_acc_email = file_acc.get("email", "Tidak Diketahui") if isinstance(file_acc, dict) else "Tidak Diketahui"

        # Peringatan 3: Apabila ID di file berbeda dengan baris yang dipilih
        mismatch_warning = ""
        if file_acc_id and file_acc_id != account_id:
            mismatch_warning = (
                f"\n\n<b>⚠️ PERINGATAN BEDA AKUN:</b>\n"
                f"ID Akun di file (<b>{file_acc_email}</b>) BERBEDA dengan baris yang dipilih di tabel (<b>{email}</b>)!"
            )

        # Konfirmasi Pengguna
        confirm = QMessageBox.question(
            self,
            "Konfirmasi Update Database",
            f"Apakah Anda yakin ingin memperbarui data database baris <b>{email}</b> menggunakan isi dari file:\n<b>{target_file}</b>?{mismatch_warning}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if confirm == QMessageBox.StandardButton.Yes:
            try:
                # Masukkan/Update data dari file JSON ke SQLite Database
                count = self.db.insert_or_update_json(content)
                QMessageBox.information(
                    self,
                    "Berhasil Update Database",
                    "Berhasil mengonfirmasi & memperbarui data akun ke database!"
                )
                self.load_table_data()
            except Exception as e:
                QMessageBox.critical(self, "Database Error", f"Terjadi kesalahan saat memperbarui database:\n\n{str(e)}")