"""Pengujian migrasi aditif dan kolom audit database (Ticket 03).

Memeriksa:
1. Migrasi idempoten SQLite: PRAGMA table_info dicek, dijalankan 2x tetap aman.
2. Migrasi pada database kosong maupun database lama (skema v1.1.0 sebelum kolom audit).
3. Kolom `applied_target` dan `last_applied_at` berada di akhir fetch_accounts_summary (indeks 0-10 tidak bergeser).
4. `mark_applied` menyimpan target kanonik dan epoch detik UTC.
5. `update_refresh_token` menghormati status enkripsi akun (terenkripsi tetap terenkripsi, plaintext tetap plaintext).
6. Penandaan audit tidak mengubah kategori, kuota, atau tabel account_fingerprints.
"""

import json
import sqlite3
import pytest

from src.crypto import decrypt_value, encrypt_value
from src.database import AccountDatabase
from src.targets import TARGET_ANTIGRAVITY_CLI, TARGET_OPENCODE


SAMPLE_RAW_JSON = json.dumps({
    "version": 4,
    "accounts": [{
        "id": "acc-audit-1",
        "email": "user1@example.com",
        "refreshToken": "1//initial-refresh-token",
        "projectId": "proj-1",
        "category": "Kerja",
        "enabled": True,
        "cachedQuota": {
            "gemini-flash": {
                "remainingFraction": 0.85,
                "resetTime": "2026-11-21T18:00:00Z"
            },
            "gemini-pro": {
                "remainingFraction": 0.50,
                "resetTime": "2026-11-21T19:00:00Z"
            },
            "claude": {
                "remainingFraction": 1.0,
                "resetTime": "2026-11-21T20:00:00Z"
            }
        },
        "fingerprint": {
            "deviceId": "dev-123",
            "sessionToken": "sess-456",
            "userAgent": "TestAgent/1.0",
            "apiClient": "TestClient",
            "clientMetadata": {
                "ideType": "VSCode",
                "platform": "Linux",
                "pluginType": "Core"
            },
            "createdAt": 1700000000
        }
    }]
})


def test_additive_migration_on_fresh_database(tmp_path):
  """Database baru otomatis memiliki kolom audit applied_target dan last_applied_at."""
  db_path = str(tmp_path / "fresh.db")
  db = AccountDatabase(db_path=db_path)

  with sqlite3.connect(db_path) as conn:
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(accounts);")
    columns = {row[1]: row[2] for row in cursor.fetchall()}

  assert "applied_target" in columns
  assert "last_applied_at" in columns


def test_idempotent_migration_running_twice(tmp_path):
  """Memanggil init_db() berulang kali tidak melempar error dan kolom tetap ada."""
  db_path = str(tmp_path / "idempotent.db")
  db = AccountDatabase(db_path=db_path)

  # Panggil ulang init_db 2x
  db.init_db()
  db.init_db()

  with sqlite3.connect(db_path) as conn:
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(accounts);")
    columns = {row[1]: row[2] for row in cursor.fetchall()}

  assert "applied_target" in columns
  assert "last_applied_at" in columns


def test_migration_from_legacy_database_with_data(tmp_path):
  """Database lama tanpa kolom audit yang sudah berisi akun dan kuota berhasil dimigrasi tanpa merusak data."""
  db_path = str(tmp_path / "legacy.db")

  # Buat database lama (skema sebelum audit columns)
  with sqlite3.connect(db_path) as conn:
    conn.execute("""
        CREATE TABLE accounts (
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
            rate_limit_reset_times TEXT,
            is_encrypted INTEGER NOT NULL DEFAULT 0,
            enc_check TEXT,
            category TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE account_fingerprints (
            account_id TEXT PRIMARY KEY,
            device_id TEXT,
            session_token TEXT,
            user_agent TEXT,
            api_client TEXT,
            ide_type TEXT,
            platform TEXT,
            plugin_type TEXT,
            created_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE account_quotas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            model_name TEXT NOT NULL,
            remaining_fraction REAL NOT NULL DEFAULT 1.0,
            reset_time TEXT,
            remaining_fraction_reset_time TEXT,
            model_count INTEGER DEFAULT 1
        )
    """)
    # Masukkan 1 akun lama
    conn.execute(
        "INSERT INTO accounts (id, email, refresh_token, category) VALUES (?, ?, ?, ?)",
        ("legacy-1", "legacy@example.com", "rt-legacy", "Lama"),
    )
    conn.execute(
        "INSERT INTO account_fingerprints (account_id, device_id) VALUES (?, ?)",
        ("legacy-1", "dev-old"),
    )
    conn.execute(
        "INSERT INTO account_quotas (account_id, model_name, remaining_fraction) VALUES (?, ?, ?)",
        ("legacy-1", "gemini-flash", 0.9),
    )
    conn.commit()

  # Buka dengan AccountDatabase sehingga migrasi aditif berjalan
  db = AccountDatabase(db_path=db_path)

  # Pastikan kolom audit ada
  with sqlite3.connect(db_path) as conn:
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(accounts);")
    cols = [r[1] for r in cursor.fetchall()]
    assert "applied_target" in cols
    assert "last_applied_at" in cols

  # Data lama tetap utuh
  summary = db.fetch_accounts_summary()
  assert len(summary) == 1
  assert summary[0][0] == "legacy-1"
  assert summary[0][1] == "legacy@example.com"
  assert summary[0][10] == "Lama"
  # Kolom audit awal bernilai None
  assert summary[0][11] is None
  assert summary[0][12] is None


def test_accounts_summary_indices_and_audit_columns(tmp_path):
  """fetch_accounts_summary mengembalikan 13 kolom dengan indeks 0-10 identik dengan versi sebelumnya."""
  db_path = str(tmp_path / "test_indices.db")
  db = AccountDatabase(db_path=db_path)
  db.insert_or_update_json(SAMPLE_RAW_JSON)

  rows = db.fetch_accounts_summary()
  assert len(rows) == 1
  row = rows[0]

  assert len(row) == 13
  # Indeks lama 0-10
  assert row[0] == "acc-audit-1"                     # id
  assert row[1] == "user1@example.com"              # email
  assert row[2] == "2026-11-21T18:00:00Z"           # flash_reset
  assert row[3] == 0.85                             # flash_frac
  assert row[4] == "2026-11-21T19:00:00Z"           # pro_reset
  assert row[5] == 0.50                             # pro_frac
  assert row[6] == "2026-11-21T20:00:00Z"           # claude_reset
  assert row[7] == 1.0                              # claude_frac
  assert row[8] == 0                                # is_encrypted
  assert row[9] is None                             # enc_check
  assert row[10] == "Kerja"                         # category
  # Kolom audit baru di indeks 11 dan 12
  assert row[11] is None                            # applied_target
  assert row[12] is None                            # last_applied_at


def test_mark_applied_canonical_target_and_epoch(tmp_path):
  """mark_applied menyimpan target kanonik dan timestamp epoch detik UTC."""
  db_path = str(tmp_path / "test_mark.db")
  db = AccountDatabase(db_path=db_path)
  db.insert_or_update_json(SAMPLE_RAW_JSON)

  # Tandai opencode dengan waktu eksplisit
  epoch_time = 1732170000
  success = db.mark_applied("acc-audit-1", "OpenCode", applied_at=epoch_time)
  assert success is True

  rows = db.fetch_accounts_summary()
  assert rows[0][11] == TARGET_OPENCODE
  assert rows[0][12] == epoch_time

  # Tandai antigravity_cli dengan default waktu otomatis
  success2 = db.mark_applied("acc-audit-1", "antigravity_cli")
  assert success2 is True

  rows2 = db.fetch_accounts_summary()
  assert rows2[0][11] == TARGET_ANTIGRAVITY_CLI
  assert isinstance(rows2[0][12], int)
  assert rows2[0][12] > 0

  # Target tak dikenal otomatis dinormalisasi ke OpenCode
  db.mark_applied("acc-audit-1", "unknown_target", applied_at=12345)
  rows3 = db.fetch_accounts_summary()
  assert rows3[0][11] == TARGET_OPENCODE
  assert rows3[0][12] == 12345


def test_mark_applied_preserves_categories_quotas_and_fingerprints(tmp_path):
  """Penandaan audit tidak mengubah kategori, kuota, atau fingerprint."""
  db_path = str(tmp_path / "test_preserve.db")
  db = AccountDatabase(db_path=db_path)
  db.insert_or_update_json(SAMPLE_RAW_JSON)

  # Tandai akun
  db.mark_applied("acc-audit-1", "antigravity_cli", applied_at=1732171234)

  # Periksa kategori dan kuota via summary
  rows = db.fetch_accounts_summary()
  assert rows[0][10] == "Kerja"
  assert rows[0][3] == 0.85
  assert rows[0][5] == 0.50
  assert rows[0][7] == 1.0

  # Periksa fingerprint di tabel SQLite langsung
  with sqlite3.connect(db_path) as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT device_id, session_token FROM account_fingerprints WHERE account_id = ?", ("acc-audit-1",))
    fp = cursor.fetchone()
    assert fp == ("dev-123", "sess-456")

  # Periksa rekonstruksi JSON
  recon = json.loads(db.reconstruct_json_by_id("acc-audit-1"))
  acc = recon["accounts"][0]
  assert acc["category"] == "Kerja"
  assert acc["fingerprint"]["deviceId"] == "dev-123"
  assert acc["cachedQuota"]["gemini-flash"]["remainingFraction"] == 0.85


def test_update_refresh_token_plaintext(tmp_path):
  """update_refresh_token memperbarui token akun plaintext tanpa enkripsi."""
  db_path = str(tmp_path / "test_rt_plain.db")
  db = AccountDatabase(db_path=db_path)
  db.insert_or_update_json(SAMPLE_RAW_JSON, encrypt=False)

  new_token = "1//rotated-refresh-token-999"
  success = db.update_refresh_token("acc-audit-1", new_token)
  assert success is True

  recon = json.loads(db.reconstruct_json_by_id("acc-audit-1"))
  assert recon["accounts"][0]["refreshToken"] == new_token

  # Cek nilai di database SQLite langsung memang plaintext
  with sqlite3.connect(db_path) as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT refresh_token, is_encrypted FROM accounts WHERE id = ?", ("acc-audit-1",))
    row = cursor.fetchone()
    assert row[0] == new_token
    assert row[1] == 0


def test_update_refresh_token_encrypted(tmp_path):
  """update_refresh_token memperbarui token akun terenkripsi dengan tetap mempertahankan status enkripsi."""
  db_path = str(tmp_path / "test_rt_enc.db")
  db = AccountDatabase(db_path=db_path)
  password = "SecretPassword123!"

  db.insert_or_update_json(SAMPLE_RAW_JSON, encrypt=True, password=password)

  # Cek awal akun terenkripsi
  with sqlite3.connect(db_path) as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT refresh_token, is_encrypted FROM accounts WHERE id = ?", ("acc-audit-1",))
    row = cursor.fetchone()
    assert row[1] == 1
    assert row[0] != "1//initial-refresh-token"

  # Gagal bila password tidak disertakan
  with pytest.raises(ValueError, match="Password enkripsi diperlukan"):
    db.update_refresh_token("acc-audit-1", "1//new-rot-token", password="")

  # Gagal bila password salah
  with pytest.raises(ValueError, match="Password enkripsi salah"):
    db.update_refresh_token("acc-audit-1", "1//new-rot-token", password="WrongPassword")

  # Berhasil dengan password yang benar
  new_token = "1//rotated-encrypted-token-888"
  success = db.update_refresh_token("acc-audit-1", new_token, password=password)
  assert success is True

  # Di database nilai tersimpan terenkripsi
  with sqlite3.connect(db_path) as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT refresh_token, is_encrypted FROM accounts WHERE id = ?", ("acc-audit-1",))
    row_updated = cursor.fetchone()
    assert row_updated[1] == 1
    assert row_updated[0] != new_token
    decrypted = decrypt_value(row_updated[0], password, "")
    assert decrypted == new_token

  # Rekonstruksi dengan password membaca token baru
  recon = json.loads(db.reconstruct_json_by_id("acc-audit-1", password=password))
  assert recon["accounts"][0]["refreshToken"] == new_token
