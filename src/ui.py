import json
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QHeaderView, QMessageBox, QSplitter
)
from PyQt6.QtCore import Qt
from src.database import AccountDatabase


def format_human_time(time_str):
    """Mengubah timestamp/ISO string menjadi format tanggal manusia yang mudah dibaca."""
    if not time_str or time_str == "-":
        return "-"
    
    try:
        # Jika format berupa angka/timestamp Unix (detik atau milidetik)
        if str(time_str).isdigit() or isinstance(time_str, (int, float)):
            ts = float(time_str)
            if ts > 1e11:  # Milidetik
                ts /= 1000.0
            dt = datetime.fromtimestamp(ts)
        else:
            # Jika format ISO String (misal: "2026-11-04T05:30:00Z" atau "2026-11-04T05:30:00")
            clean_str = time_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_str)
            
        # Format tampilan: "04 Nov 2026, 12:30"
        return dt.strftime("%d %b %Y, %H:%M")
    except Exception:
        # Jika terjadi kesalahan parsing, tampilkan teks aslinya
        return str(time_str)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = AccountDatabase()
        self.init_ui()
        self.load_table_data()

    def init_ui(self):
        self.setWindowTitle("JSON Account Manager (PyQt6)")
        self.resize(1000, 600)
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # ------------------------------------------
        # BAGIAN ATAS: INPUT JSON
        # ------------------------------------------
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

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
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        label_table = QLabel("<b>Daftar Akun:</b>")
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Email", "Flash Reset Time", "Pro Reset Time", "Claude Reset Time", "Aksi"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        bottom_layout.addWidget(label_table)
        bottom_layout.addWidget(self.table)

        splitter.addWidget(top_widget)
        splitter.addWidget(bottom_widget)
        splitter.setSizes([180, 420])

        main_layout.addWidget(splitter)

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
            acc_id, email, flash_reset, pro_reset, claude_reset = row_data
            self.table.insertRow(row_idx)

            # Kolom Email
            self.table.setItem(row_idx, 0, QTableWidgetItem(email or "-"))

            # Kolom Reset Times (Menggunakan format_human_time)
            self.table.setItem(row_idx, 1, QTableWidgetItem(format_human_time(flash_reset)))
            self.table.setItem(row_idx, 2, QTableWidgetItem(format_human_time(pro_reset)))
            self.table.setItem(row_idx, 3, QTableWidgetItem(format_human_time(claude_reset)))

            # Format rata tengah teks kolom
            for c in range(4):
                item = self.table.item(row_idx, c)
                if item:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # Tombol Copy JSON
            btn_copy = QPushButton("Copy JSON")
            btn_copy.setStyleSheet("background-color: #4CAF50; color: white; padding: 3px 8px; border-radius: 3px;")
            btn_copy.clicked.connect(lambda _, aid=acc_id: self.copy_account_json(aid))
            self.table.setCellWidget(row_idx, 4, btn_copy)

    def copy_account_json(self, account_id):
        """Merekonstruksi JSON asli dari database lalu menyalinnya ke Clipboard."""
        json_str = self.db.reconstruct_json_by_id(account_id)
        if json_str:
            QApplication.clipboard().setText(json_str)
            QMessageBox.information(self, "Disalin!", "Format JSON utuh berhasil disalin ke clipboard!")
        else:
            QMessageBox.warning(self, "Gagal", "Gagal mengembalikan format JSON dari database.")