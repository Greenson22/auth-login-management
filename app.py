import sys
import sqlite3
import json
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QHeaderView, QMessageBox, QSplitter
)
from PyQt6.QtCore import Qt

# ==========================================
# 1. DATABASE HELPER
# ==========================================
class AccountDatabase:
    def __init__(self, db_path="accounts_manager.db"):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def init_db(self):
        """Membuat struktur tabel SQLite."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Tabel Accounts
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    refresh_token TEXT NOT NULL,
                    project_id TEXT,
                    managed_project_id TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    verification_required INTEGER DEFAULT 0,
                    added_at INTEGER,
                    last_used INTEGER,
                    cached_quota_updated_at INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Tabel Fingerprints
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS account_fingerprints (
                    account_id TEXT PRIMARY KEY,
                    device_id TEXT,
                    session_token TEXT,
                    user_agent TEXT,
                    api_client TEXT,
                    ide_type TEXT,
                    platform TEXT,
                    plugin_type TEXT,
                    created_at INTEGER,
                    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
                )
            ''')

            # Tabel Quotas
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS account_quotas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    remaining_fraction REAL NOT NULL DEFAULT 1.0,
                    reset_time TEXT,
                    remaining_fraction_reset_time TEXT,
                    model_count INTEGER DEFAULT 1,
                    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                    CONSTRAINT uq_account_model UNIQUE (account_id, model_name)
                )
            ''')
            conn.commit()

    def insert_or_update_json(self, raw_json_str):
        """Parsing JSON dan menyimpannya ke database (Upsert)."""
        data = json.loads(raw_json_str)
        
        # Tangani jika input berupa objek tunggal atau wrapper versi
        accounts = data.get("accounts", [data]) if isinstance(data, dict) and "accounts" in data else data
        if isinstance(accounts, dict):
            accounts = [accounts]

        inserted_count = 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for acc in accounts:
                if "id" not in acc or "email" not in acc:
                    continue
                
                acc_id = acc.get("id")

                # 1. Upsert Accounts
                cursor.execute('''
                    INSERT INTO accounts (
                        id, email, refresh_token, project_id, managed_project_id,
                        enabled, verification_required, added_at, last_used, cached_quota_updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        email=excluded.email,
                        refresh_token=excluded.refresh_token,
                        enabled=excluded.enabled,
                        last_used=excluded.last_used,
                        cached_quota_updated_at=excluded.cached_quota_updated_at
                ''', (
                    acc_id, acc.get("email"), acc.get("refreshToken", ""),
                    acc.get("projectId"), acc.get("managedProjectId"),
                    1 if acc.get("enabled", True) else 0,
                    1 if acc.get("verificationRequired", False) else 0,
                    acc.get("addedAt"), acc.get("lastUsed"), acc.get("cachedQuotaUpdatedAt")
                ))

                # 2. Upsert Fingerprint
                fp = acc.get("fingerprint", {})
                cm = fp.get("clientMetadata", {})
                cursor.execute('''
                    INSERT INTO account_fingerprints (
                        account_id, device_id, session_token, user_agent,
                        api_client, ide_type, platform, plugin_type, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(account_id) DO UPDATE SET
                        device_id=excluded.device_id,
                        session_token=excluded.session_token,
                        user_agent=excluded.user_agent,
                        api_client=excluded.api_client
                ''', (
                    acc_id, fp.get("deviceId"), fp.get("sessionToken"),
                    fp.get("userAgent"), fp.get("apiClient"),
                    cm.get("ideType"), cm.get("platform"), cm.get("pluginType"),
                    fp.get("createdAt")
                ))

                # 3. Upsert Quotas
                quotas = acc.get("cachedQuota", {})
                for model_name, q in quotas.items():
                    cursor.execute('''
                        INSERT INTO account_quotas (
                            account_id, model_name, remaining_fraction, reset_time,
                            remaining_fraction_reset_time, model_count
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(account_id, model_name) DO UPDATE SET
                            remaining_fraction=excluded.remaining_fraction,
                            reset_time=excluded.reset_time,
                            model_count=excluded.model_count
                    ''', (
                        acc_id, model_name, q.get("remainingFraction", 1.0),
                        q.get("resetTime"), q.get("remainingFractionResetTime"),
                        q.get("modelCount", 1)
                    ))
                
                inserted_count += 1
            conn.commit()
        return inserted_count

    def fetch_all_accounts_summary(self):
        """Mengambil gabungan data akun dan kuotanya untuk tabel GUI."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT 
                    a.id,
                    a.email,
                    a.enabled,
                    f.platform,
                    f.ide_type,
                    MAX(CASE WHEN q.model_name = 'gemini-flash' THEN ROUND(q.remaining_fraction * 100, 2) END) AS flash_q,
                    MAX(CASE WHEN q.model_name = 'gemini-pro' THEN ROUND(q.remaining_fraction * 100, 2) END) AS pro_q,
                    MAX(CASE WHEN q.model_name = 'claude' THEN ROUND(q.remaining_fraction * 100, 2) END) AS claude_q,
                    a.project_id
                FROM accounts a
                LEFT JOIN account_fingerprints f ON a.id = f.account_id
                LEFT JOIN account_quotas q ON a.id = q.account_id
                GROUP BY a.id
                ORDER BY a.created_at DESC
            '''
            return cursor.execute(query).fetchall()

# ==========================================
# 2. GUI PYQT6
# ==========================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = AccountDatabase()
        self.init_ui()
        self.load_table_data()

    def init_ui(self):
        self.setWindowTitle("JSON Account Manager to SQLite (PyQt6)")
        self.resize(1100, 650)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # Splitter untuk memisahkan area Input JSON dan Tabel Data
        splitter = QSplitter(Qt.Orientation.Vertical)

        # ------------------------------------------
        # BAGIAN ATAS: INPUT JSON & BUTTON
        # ------------------------------------------
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        label_input = QLabel("<b>Paste Format JSON Akun di Sini:</b>")
        self.json_input = QTextEdit()
        self.json_input.setPlaceholderText('Paste teks JSON di sini, contoh: {"version": 4, "accounts": [...] }')

        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("Simpan ke Database SQLite")
        self.btn_save.setStyleSheet("background-color: #2b5c8f; color: white; font-weight: bold; padding: 8px;")
        self.btn_save.clicked.connect(self.process_json)

        self.btn_clear = QPushButton("Bersihkan Input")
        self.btn_clear.clicked.connect(lambda: self.json_input.clear())

        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_clear)

        top_layout.addWidget(label_input)
        top_layout.addWidget(self.json_input)
        top_layout.addLayout(btn_layout)

        # ------------------------------------------
        # BAGIAN BAWAH: DAFTAR KUMPULAN DATA (TABEL)
        # ------------------------------------------
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        label_table = QLabel("<b>Daftar Akun Tersimpan di Database:</b>")
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "Account ID", "Email", "Status", "Platform", "IDE", 
            "Flash Quota (%)", "Pro Quota (%)", "Claude Quota (%)", "Project ID"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        bottom_layout.addWidget(label_table)
        bottom_layout.addWidget(self.table)

        # Masukkan ke splitter
        splitter.addWidget(top_widget)
        splitter.addWidget(bottom_widget)
        splitter.setSizes([200, 450])

        main_layout.addWidget(splitter)

    def process_json(self):
        """Handler saat tombol simpan diklik."""
        raw_text = self.json_input.toPlainText().strip()
        if not raw_text:
            QMessageBox.warning(self, "Peringatan", "Area teks JSON masih kosong!")
            return

        try:
            count = self.db.insert_or_update_json(raw_text)
            QMessageBox.information(self, "Sukses", f"Berhasil menyimpan/memperbarui {count} data akun!")
            self.json_input.clear()
            self.load_table_data() # Refresh Tabel
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "Error JSON", f"Format JSON tidak valid!\n\nDetail: {str(e)}")
        except Exception as e:
            QMessageBox.critical(self, "Database Error", f"Terjadi kesalahan saat menyimpan:\n\n{str(e)}")

    def load_table_data(self):
        """Memuat ulang data dari SQLite ke QTableWidget."""
        rows = self.db.fetch_all_accounts_summary()
        self.table.setRowCount(0)

        for row_idx, row_data in enumerate(rows):
            self.table.insertRow(row_idx)
            for col_idx, value in enumerate(row_data):
                # Formatting Tampilan
                if col_idx == 2:  # Status Enabled
                    display_text = "Aktif" if value == 1 else "Nonaktif"
                elif col_idx in [5, 6, 7]:  # Quota percentages
                    display_text = f"{value}%" if value is not None else "N/A"
                else:
                    display_text = str(value) if value is not None else "-"

                item = QTableWidgetItem(display_text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

# ==========================================
# 3. RUN APPLICATION
# ==========================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())