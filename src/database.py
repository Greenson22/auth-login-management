import json
import sqlite3
from typing import Optional
from src.crypto import (
    create_encryption_canary,
    decrypt_aes256,
    decrypt_value,
    encrypt_aes256,
    encrypt_value,
    verify_encryption_canary,
)
from src.turso_client import TursoClient


class AccountDatabase:

  def __init__(
      self,
      db_path: str = "accounts_manager.db",
      use_turso: bool = False,
      turso_url: str = "",
      turso_token: str = "",
  ):
    self.db_path = db_path
    self.use_turso = use_turso
    self.turso_url = turso_url
    self.turso_token = turso_token
    self.turso_client: Optional[TursoClient] = None

    if self.use_turso and self.turso_url and self.turso_token:
      self.turso_client = TursoClient(self.turso_url, self.turso_token)

    self.init_db()

  def get_connection(self):
    """Membuka koneksi lokal SQLite."""
    conn = sqlite3.connect(self.db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

  def init_db(self):
    """Membuat struktur tabel SQLite atau Turso."""
    create_accounts_sql = """
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
            rate_limit_reset_times TEXT,
            is_encrypted INTEGER NOT NULL DEFAULT 0,
            enc_check TEXT,
            category TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """
    create_fingerprints_sql = """
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
    """
    create_quotas_sql = """
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
    """

    if self.use_turso and self.turso_client:
      try:
        self.turso_client.execute_pipeline([
            (create_accounts_sql, None),
            (create_fingerprints_sql, None),
            (create_quotas_sql, None),
        ])
        # Migrasi kolom is_encrypted, rate_limit_reset_times & enc_check bila tabel sudah ada sebelumnya
        try:
          self.turso_client.execute("ALTER TABLE accounts ADD COLUMN is_encrypted INTEGER NOT NULL DEFAULT 0")
        except Exception:
          pass
        try:
          self.turso_client.execute("ALTER TABLE accounts ADD COLUMN rate_limit_reset_times TEXT")
        except Exception:
          pass
        try:
          self.turso_client.execute("ALTER TABLE accounts ADD COLUMN enc_check TEXT")
        except Exception:
          pass
        try:
          self.turso_client.execute("ALTER TABLE accounts ADD COLUMN category TEXT DEFAULT ''")
        except Exception:
          pass
      except Exception:
        # Jika database offline / belum terhubung saat startup, abaikan agar tidak crash
        pass
    else:
      with self.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(create_accounts_sql)
        cursor.execute(create_fingerprints_sql)
        cursor.execute(create_quotas_sql)
        # Migrasi kolom accounts untuk SQLite lokal
        cursor.execute("PRAGMA table_info(accounts);")
        columns = [row[1] for row in cursor.fetchall()]
        if "is_encrypted" not in columns:
          cursor.execute("ALTER TABLE accounts ADD COLUMN is_encrypted INTEGER NOT NULL DEFAULT 0;")
        if "rate_limit_reset_times" not in columns:
          cursor.execute("ALTER TABLE accounts ADD COLUMN rate_limit_reset_times TEXT;")
        if "enc_check" not in columns:
          cursor.execute("ALTER TABLE accounts ADD COLUMN enc_check TEXT;")
        if "category" not in columns:
          cursor.execute("ALTER TABLE accounts ADD COLUMN category TEXT DEFAULT '';")
        conn.commit()

  def _prepare_account_record(
      self, acc: dict, encrypt: bool, password: str, category: str = ""
  ):
    """Menyiapkan data akun, fingerprint, dan quota untuk disimpan (terenkripsi atau plaintext)."""
    acc_id = acc.get("id")
    email = acc.get("email")
    if not acc_id or not email:
      return None

    is_enc = bool(encrypt and password)
    is_encrypted_val = 1 if is_enc else 0

    if is_enc:
      stored_rt = encrypt_value(acc.get("refreshToken", ""), password)
      stored_project_id = encrypt_value(acc.get("projectId"), password)
      stored_managed_project_id = encrypt_value(acc.get("managedProjectId"), password)
      stored_enabled = encrypt_value(acc.get("enabled", True), password)
      stored_verification_required = encrypt_value(acc.get("verificationRequired", False), password)
      stored_added_at = encrypt_value(acc.get("addedAt"), password)
      stored_last_used = encrypt_value(acc.get("lastUsed"), password)
      stored_cached_quota_updated_at = encrypt_value(acc.get("cachedQuotaUpdatedAt"), password)
      stored_rate_limit_reset_times = encrypt_value(acc.get("rateLimitResetTimes", {}), password)
      stored_enc_check = create_encryption_canary(password)
    else:
      stored_rt = acc.get("refreshToken", "")
      stored_project_id = acc.get("projectId")
      stored_managed_project_id = acc.get("managedProjectId")
      stored_enabled = 1 if acc.get("enabled", True) else 0
      stored_verification_required = 1 if acc.get("verificationRequired", False) else 0
      stored_added_at = acc.get("addedAt")
      stored_last_used = acc.get("lastUsed")
      stored_cached_quota_updated_at = acc.get("cachedQuotaUpdatedAt")
      stored_rate_limit_reset_times = json.dumps(acc.get("rateLimitResetTimes", {}))
      stored_enc_check = None

    cat_val = category.strip() if category else (acc.get("category") or "").strip()

    args_acc = [
        acc_id,
        email,
        stored_rt,
        stored_project_id,
        stored_managed_project_id,
        stored_enabled,
        stored_verification_required,
        stored_added_at,
        stored_last_used,
        stored_cached_quota_updated_at,
        stored_rate_limit_reset_times,
        is_encrypted_val,
        stored_enc_check,
        cat_val,
    ]

    fp = acc.get("fingerprint", {}) or {}
    cm = fp.get("clientMetadata", {}) or {}

    if is_enc:
      stored_dev_id = encrypt_value(fp.get("deviceId", ""), password)
      stored_st = encrypt_value(fp.get("sessionToken", ""), password)
      stored_user_agent = encrypt_value(fp.get("userAgent", ""), password)
      stored_api_client = encrypt_value(fp.get("apiClient", ""), password)
      stored_ide_type = encrypt_value(cm.get("ideType", ""), password)
      stored_platform = encrypt_value(cm.get("platform", ""), password)
      stored_plugin_type = encrypt_value(cm.get("pluginType", ""), password)
      stored_fp_created_at = encrypt_value(fp.get("createdAt"), password)
    else:
      stored_dev_id = fp.get("deviceId")
      stored_st = fp.get("sessionToken", "")
      stored_user_agent = fp.get("userAgent")
      stored_api_client = fp.get("apiClient")
      stored_ide_type = cm.get("ideType")
      stored_platform = cm.get("platform")
      stored_plugin_type = cm.get("pluginType")
      stored_fp_created_at = fp.get("createdAt")

    args_fp = [
        acc_id,
        stored_dev_id,
        stored_st,
        stored_user_agent,
        stored_api_client,
        stored_ide_type,
        stored_platform,
        stored_plugin_type,
        stored_fp_created_at,
    ]

    quotas = acc.get("cachedQuota", {}) or {}
    args_quotas = []
    for model_name, q in quotas.items():
      # Note: model_name, remainingFraction, resetTime tetap plaintext untuk summary & sorting UI
      if is_enc:
        stored_remaining_reset = encrypt_value(q.get("remainingFractionResetTime"), password)
        stored_model_count = encrypt_value(q.get("modelCount", 1), password)
      else:
        stored_remaining_reset = q.get("remainingFractionResetTime")
        stored_model_count = q.get("modelCount", 1)

      args_quotas.append([
          acc_id,
          model_name,
          q.get("remainingFraction", 1.0),
          q.get("resetTime"),
          stored_remaining_reset,
          stored_model_count,
      ])

    return args_acc, args_fp, args_quotas

  def insert_or_update_json(
      self,
      raw_json_str: str,
      encrypt: bool = False,
      password: str = "",
      category: str = "",
  ) -> int:
    """Parsing JSON dan menyimpannya ke database (Local SQLite atau Turso).

    Jika encrypt=True dan password diberikan, semua field kredensial & metadata
    (selain id, email, dan kuota ringkas untuk UI) akan dienkripsi dengan AES-256.
    """
    data = json.loads(raw_json_str)
    accounts = (
        data.get("accounts", [data])
        if isinstance(data, dict) and "accounts" in data
        else data
    )
    if isinstance(accounts, dict):
      accounts = [accounts]

    sql_acc = """
        INSERT INTO accounts (
            id, email, refresh_token, project_id, managed_project_id,
            enabled, verification_required, added_at, last_used, cached_quota_updated_at,
            rate_limit_reset_times, is_encrypted, enc_check, category
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            email=excluded.email,
            refresh_token=excluded.refresh_token,
            project_id=excluded.project_id,
            managed_project_id=excluded.managed_project_id,
            enabled=excluded.enabled,
            verification_required=excluded.verification_required,
            added_at=excluded.added_at,
            last_used=excluded.last_used,
            cached_quota_updated_at=excluded.cached_quota_updated_at,
            rate_limit_reset_times=excluded.rate_limit_reset_times,
            is_encrypted=excluded.is_encrypted,
            enc_check=excluded.enc_check,
            category=CASE WHEN excluded.category != '' THEN excluded.category ELSE accounts.category END
    """
    sql_fp = """
        INSERT INTO account_fingerprints (
            account_id, device_id, session_token, user_agent,
            api_client, ide_type, platform, plugin_type, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id) DO UPDATE SET
            device_id=excluded.device_id,
            session_token=excluded.session_token,
            user_agent=excluded.user_agent,
            api_client=excluded.api_client,
            ide_type=excluded.ide_type,
            platform=excluded.platform,
            plugin_type=excluded.plugin_type,
            created_at=excluded.created_at
    """
    sql_q = """
        INSERT INTO account_quotas (
            account_id, model_name, remaining_fraction, reset_time,
            remaining_fraction_reset_time, model_count
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id, model_name) DO UPDATE SET
            remaining_fraction=excluded.remaining_fraction,
            reset_time=excluded.reset_time,
            remaining_fraction_reset_time=excluded.remaining_fraction_reset_time,
            model_count=excluded.model_count
    """

    inserted_count = 0

    if self.use_turso and self.turso_client:
      pipeline_stmts = []
      for acc in accounts:
        prepared = self._prepare_account_record(acc, encrypt, password, category)
        if not prepared:
          continue
        args_acc, args_fp, list_args_quotas = prepared
        pipeline_stmts.append((sql_acc, args_acc))
        pipeline_stmts.append((sql_fp, args_fp))
        for args_q in list_args_quotas:
          pipeline_stmts.append((sql_q, args_q))
        inserted_count += 1

      if pipeline_stmts:
        self.turso_client.execute_pipeline(pipeline_stmts)

      return inserted_count

    else:
      with self.get_connection() as conn:
        cursor = conn.cursor()
        for acc in accounts:
          prepared = self._prepare_account_record(acc, encrypt, password, category)
          if not prepared:
            continue
          args_acc, args_fp, list_args_quotas = prepared
          cursor.execute(sql_acc, args_acc)
          cursor.execute(sql_fp, args_fp)
          for args_q in list_args_quotas:
            cursor.execute(sql_q, args_q)
          inserted_count += 1
        conn.commit()
      return inserted_count

  def decrypt_all_accounts(self, password: str) -> int:
    """Mendekripsi semua akun yang tersimpan terenkripsi (is_encrypted=1) dan menyimpannya kembali sebagai plaintext.

    Digunakan sebelum mengganti password enkripsi agar data lama dapat dibaca ulang.
    Mengembalikan jumlah akun yang berhasil didekripsi.
    """
    if not password:
      raise ValueError("Password enkripsi tidak boleh kosong.")

    # Ambil semua akun yang terenkripsi dan canary-nya jika ada
    query_accs = "SELECT id, enc_check FROM accounts WHERE is_encrypted = 1"

    if self.use_turso and self.turso_client:
      rows, _ = self.turso_client.execute(query_accs)
      enc_accounts = rows if rows else []
    else:
      with self.get_connection() as conn:
        cursor = conn.cursor()
        enc_accounts = cursor.execute(query_accs).fetchall()

    if not enc_accounts:
      return 0

    # Lakukan validasi password terlebih dahulu terhadap canary yang tersedia
    for _, enc_check in enc_accounts:
      if enc_check:
        if not verify_encryption_canary(enc_check, password):
          raise ValueError(
              "Password enkripsi yang dimasukkan salah!\n\n"
              "Operasi dekripsi dibatalkan agar data tidak korup."
          )
        # Jika satu canary berhasil diverifikasi, password dipastikan benar
        break

    count = 0
    for row in enc_accounts:
      acc_id = row[0]
      try:
        # Rekonstruksi JSON menggunakan password yang ada
        json_str = self.reconstruct_json_by_id(acc_id, password=password)
        if not json_str:
          continue
        # Simpan ulang sebagai plaintext (encrypt=False)
        self.insert_or_update_json(json_str, encrypt=False, password="")
        count += 1
      except Exception as e:
        raise ValueError(
            f"Gagal mendekripsi akun '{acc_id}': {e}\n\n"
            "Pastikan password yang dimasukkan benar."
        ) from e

    return count

  def delete_account(self, account_id: str) -> bool:
    """Menghapus akun berdasarkan ID dari database."""
    if self.use_turso and self.turso_client:
      stmts = [
          ("DELETE FROM account_quotas WHERE account_id = ?", [account_id]),
          (
              "DELETE FROM account_fingerprints WHERE account_id = ?",
              [account_id],
          ),
          ("DELETE FROM accounts WHERE id = ?", [account_id]),
      ]
      results = self.turso_client.execute_pipeline(stmts)
      if results and len(results) >= 3:
        # hasil delete accounts
        _, affected = results[2]
        return affected > 0
      return True
    else:
      with self.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        conn.commit()
        return cursor.rowcount > 0

  def update_account_category(self, account_id: str, category: str) -> bool:
    """Mengubah kategori akun di database."""
    clean_cat = category.strip() if category else ""
    query = "UPDATE accounts SET category = ? WHERE id = ?"
    if self.use_turso and self.turso_client:
      _, affected = self.turso_client.execute(query, [clean_cat, account_id])
      return affected > 0
    else:
      with self.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (clean_cat, account_id))
        conn.commit()
        return cursor.rowcount > 0

  def rename_category(self, old_name: str, new_name: str) -> int:
    """Mengubah nama kategori untuk semua akun dari old_name menjadi new_name."""
    clean_old = old_name.strip() if old_name else ""
    clean_new = new_name.strip() if new_name else ""
    query = "UPDATE accounts SET category = ? WHERE category = ?"
    if self.use_turso and self.turso_client:
      _, affected = self.turso_client.execute(query, [clean_new, clean_old])
      return affected
    else:
      with self.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (clean_new, clean_old))
        conn.commit()
        return cursor.rowcount

  def move_category_accounts(self, source_category: str, target_category: str) -> int:
    """Memindahkan seluruh akun dari kategori source_category ke target_category."""
    return self.rename_category(source_category, target_category)

  def move_accounts_bulk(self, account_ids: list, target_category: str) -> int:
    """Memindahkan daftar account_id terpilih ke target_category."""
    if not account_ids:
      return 0
    clean_target = target_category.strip() if target_category else ""
    placeholders = ",".join(["?"] * len(account_ids))
    query = f"UPDATE accounts SET category = ? WHERE id IN ({placeholders})"
    params = [clean_target] + list(account_ids)
    if self.use_turso and self.turso_client:
      _, affected = self.turso_client.execute(query, params)
      return affected
    else:
      with self.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        return cursor.rowcount

  def delete_category_and_accounts(self, category: str) -> int:
    """Menghapus semua akun dalam kategori tertentu serta data relasinya, lalu mengembalikan jumlah akun yang terhapus."""
    clean_cat = category.strip() if category else ""
    if not clean_cat:
      return 0

    if self.use_turso and self.turso_client:
      # Ambil ID akun yang ada di kategori ini
      find_query = "SELECT id FROM accounts WHERE category = ?"
      rows, _ = self.turso_client.execute(find_query, [clean_cat])
      acc_ids = [r[0] for r in (rows or []) if r and r[0]]
      if not acc_ids:
        return 0

      # Hapus quota, fingerprints, dan accounts dengan pipeline
      stmts = [
          ("DELETE FROM account_quotas WHERE account_id IN (SELECT id FROM accounts WHERE category = ?)", [clean_cat]),
          ("DELETE FROM account_fingerprints WHERE account_id IN (SELECT id FROM accounts WHERE category = ?)", [clean_cat]),
          ("DELETE FROM accounts WHERE category = ?", [clean_cat]),
      ]
      results = self.turso_client.execute_pipeline(stmts)
      if results and len(results) >= 3:
        _, affected = results[2]
        return affected
      return len(acc_ids)
    else:
      with self.get_connection() as conn:
        cursor = conn.cursor()
        # Aktifkan pragma dan hapus
        cursor.execute("DELETE FROM accounts WHERE category = ?", (clean_cat,))
        affected = cursor.rowcount
        conn.commit()
        return affected

  def fetch_categories_with_counts(self) -> list:
    """Mengambil daftar kategori beserta jumlah akun di masing-masing kategori."""
    query = """
        SELECT category, COUNT(*) as count
        FROM accounts
        WHERE category IS NOT NULL AND TRIM(category) != ''
        GROUP BY category
        ORDER BY category COLLATE NOCASE ASC
    """
    if self.use_turso and self.turso_client:
      rows, _ = self.turso_client.execute(query)
      return [{"category": r[0], "count": int(r[1])} for r in (rows or []) if r and r[0]]
    else:
      with self.get_connection() as conn:
        cursor = conn.cursor()
        rows = cursor.execute(query).fetchall()
        return [{"category": r[0], "count": int(r[1])} for r in rows if r and r[0]]

  def fetch_categories(self) -> list:
    """Mengambil daftar kategori unik yang aktif digunakan oleh akun di database."""
    query = """
        SELECT DISTINCT category
        FROM accounts
        WHERE category IS NOT NULL AND TRIM(category) != ''
        ORDER BY category COLLATE NOCASE ASC
    """
    if self.use_turso and self.turso_client:
      rows, _ = self.turso_client.execute(query)
      return [r[0] for r in (rows or []) if r and r[0]]
    else:
      with self.get_connection() as conn:
        cursor = conn.cursor()
        rows = cursor.execute(query).fetchall()
        return [r[0] for r in rows if r and r[0]]

  def fetch_accounts_summary(self):
    """Mengambil Email, Reset Time, Remaining Fraction per model, Status Enkripsi, dan Kategori untuk keperluan UI."""
    query = """
        SELECT 
            a.id,
            a.email,
            MAX(CASE WHEN q.model_name = 'gemini-flash' THEN q.reset_time END) AS flash_reset,
            MAX(CASE WHEN q.model_name = 'gemini-flash' THEN q.remaining_fraction END) AS flash_frac,
            MAX(CASE WHEN q.model_name = 'gemini-pro' THEN q.reset_time END) AS pro_reset,
            MAX(CASE WHEN q.model_name = 'gemini-pro' THEN q.remaining_fraction END) AS pro_frac,
            MAX(CASE WHEN q.model_name = 'claude' THEN q.reset_time END) AS claude_reset,
            MAX(CASE WHEN q.model_name = 'claude' THEN q.remaining_fraction END) AS claude_frac,
            a.is_encrypted,
            a.enc_check,
            COALESCE(a.category, '') AS category
        FROM accounts a
        LEFT JOIN account_quotas q ON a.id = q.account_id
        GROUP BY a.id
        ORDER BY a.created_at DESC
    """
    if self.use_turso and self.turso_client:
      rows, _ = self.turso_client.execute(query)
      return rows
    else:
      with self.get_connection() as conn:
        cursor = conn.cursor()
        return cursor.execute(query).fetchall()

  def reconstruct_json_by_id(self, account_id: str, password: str = ""):
    """Membuka kembali data dari SQLite / Turso dan mengembalikannya ke format JSON utuh.

    Jika akun tersimpan dalam kondisi terenkripsi (is_encrypted == 1), seluruh data
    yang dienkripsi akan didekripsi menggunakan password.
    """
    query_acc = """
        SELECT id, refresh_token, project_id, email, enabled, added_at,
                last_used, verification_required, managed_project_id, cached_quota_updated_at,
                is_encrypted, rate_limit_reset_times, enc_check, COALESCE(category, '')
        FROM accounts WHERE id = ?
    """
    query_fp = """
        SELECT device_id, session_token, user_agent, api_client,
                ide_type, platform, plugin_type, created_at
        FROM account_fingerprints WHERE account_id = ?
    """
    query_quotas = """
        SELECT model_name, remaining_fraction, reset_time, remaining_fraction_reset_time, model_count
        FROM account_quotas WHERE account_id = ?
    """

    if self.use_turso and self.turso_client:
      acc_rows, _ = self.turso_client.execute(query_acc, [account_id])
      if not acc_rows:
        return None
      acc_row = acc_rows[0]

      fp_rows, _ = self.turso_client.execute(query_fp, [account_id])
      fp_row = fp_rows[0] if fp_rows else None

      quota_rows, _ = self.turso_client.execute(query_quotas, [account_id])
    else:
      with self.get_connection() as conn:
        cursor = conn.cursor()
        acc_row = cursor.execute(query_acc, (account_id,)).fetchone()
        if not acc_row:
          return None
        fp_row = cursor.execute(query_fp, (account_id,)).fetchone()
        quota_rows = cursor.execute(query_quotas, (account_id,)).fetchall()

    is_encrypted = bool(acc_row[10]) if len(acc_row) > 10 and acc_row[10] else False
    enc_check = acc_row[12] if len(acc_row) > 12 else None

    if is_encrypted:
      if not password:
        raise ValueError(
            "Akun ini terenkripsi. Silakan atur/masukkan password enkripsi di Menu Pengaturan."
        )
      if enc_check and not verify_encryption_canary(enc_check, password):
        raise ValueError(
            "Password enkripsi salah atau data telah korup. Dekripsi dibatalkan demi keamanan."
        )
      try:
        final_refresh_token = decrypt_value(acc_row[1], password, "", strict=True)
        final_project_id = decrypt_value(acc_row[2], password, None, strict=True)
        final_enabled = decrypt_value(acc_row[4], password, True, strict=True)
        final_added_at = decrypt_value(acc_row[5], password, None, strict=True)
        final_last_used = decrypt_value(acc_row[6], password, None, strict=True)
        final_verification_required = decrypt_value(acc_row[7], password, False, strict=True)
        final_managed_project_id = decrypt_value(acc_row[8], password, None, strict=True)
        final_cached_quota_updated_at = decrypt_value(acc_row[9], password, None, strict=True)
        raw_rate_limit = acc_row[11] if len(acc_row) > 11 else None
        final_rate_limit_reset_times = decrypt_value(raw_rate_limit, password, {}, strict=True) or {}

        if fp_row:
          final_device_id = decrypt_value(fp_row[0], password, "", strict=True)
          final_session_token = decrypt_value(fp_row[1], password, "", strict=True)
          final_user_agent = decrypt_value(fp_row[2], password, "", strict=True)
          final_api_client = decrypt_value(fp_row[3], password, "", strict=True)
          final_ide_type = decrypt_value(fp_row[4], password, "", strict=True)
          final_platform = decrypt_value(fp_row[5], password, "", strict=True)
          final_plugin_type = decrypt_value(fp_row[6], password, "", strict=True)
          final_fp_created_at = decrypt_value(fp_row[7], password, 0, strict=True)
        else:
          final_device_id = ""
          final_session_token = ""
          final_user_agent = ""
          final_api_client = ""
          final_ide_type = ""
          final_platform = ""
          final_plugin_type = ""
          final_fp_created_at = 0
      except Exception as e:
        raise ValueError(
            f"Gagal mendekripsi akun (password mungkin salah atau data korup): {e}"
        )
    else:
      final_refresh_token = acc_row[1] or ""
      final_project_id = acc_row[2]
      final_enabled = bool(acc_row[4])
      final_added_at = acc_row[5]
      final_last_used = acc_row[6]
      final_verification_required = bool(acc_row[7])
      final_managed_project_id = acc_row[8]
      final_cached_quota_updated_at = acc_row[9]
      raw_rate_limit = acc_row[11] if len(acc_row) > 11 else None
      if isinstance(raw_rate_limit, str) and raw_rate_limit:
        try:
          final_rate_limit_reset_times = json.loads(raw_rate_limit)
        except Exception:
          final_rate_limit_reset_times = {}
      else:
        final_rate_limit_reset_times = raw_rate_limit or {}

      if fp_row:
        final_device_id = fp_row[0] or ""
        final_session_token = fp_row[1] or ""
        final_user_agent = fp_row[2] or ""
        final_api_client = fp_row[3] or ""
        final_ide_type = fp_row[4] or ""
        final_platform = fp_row[5] or ""
        final_plugin_type = fp_row[6] or ""
        final_fp_created_at = fp_row[7] or 0
      else:
        final_device_id = ""
        final_session_token = ""
        final_user_agent = ""
        final_api_client = ""
        final_ide_type = ""
        final_platform = ""
        final_plugin_type = ""
        final_fp_created_at = 0

    cached_quota = {}
    for q in quota_rows:
      model_name = q[0]
      rem_frac = q[1]
      res_time = q[2]
      if is_encrypted:
        rem_frac_res_time = decrypt_value(q[3], password, q[3], strict=True)
        model_count = decrypt_value(q[4], password, q[4] or 1, strict=True)
      else:
        rem_frac_res_time = q[3]
        model_count = q[4] or 1

      cached_quota[model_name] = {
          "remainingFraction": rem_frac,
          "resetTime": res_time,
          "remainingFractionResetTime": rem_frac_res_time,
          "modelCount": model_count,
      }

    cat_val = acc_row[13] if len(acc_row) > 13 and acc_row[13] else ""

    account_json = {
        "id": acc_row[0],
        "refreshToken": final_refresh_token,
        "projectId": final_project_id,
        "email": acc_row[3],
        "category": cat_val,
        "enabled": bool(final_enabled),
        "addedAt": final_added_at,
        "lastUsed": final_last_used,
        "verificationRequired": bool(final_verification_required),
        "managedProjectId": final_managed_project_id,
        "rateLimitResetTimes": final_rate_limit_reset_times if isinstance(final_rate_limit_reset_times, dict) else {},
        "fingerprint": {
            "deviceId": final_device_id,
            "sessionToken": final_session_token,
            "userAgent": final_user_agent,
            "apiClient": final_api_client,
            "clientMetadata": {
                "ideType": final_ide_type,
                "platform": final_platform,
                "pluginType": final_plugin_type,
            },
            "createdAt": final_fp_created_at,
        },
        "fingerprintHistory": [],
        "cachedQuota": cached_quota,
        "cachedQuotaUpdatedAt": final_cached_quota_updated_at,
    }

    full_config = {
        "version": 4,
        "accounts": [account_json],
        "activeIndex": 0,
        "activeIndexByFamily": {"claude": 0, "gemini": 0},
    }
    return json.dumps(full_config, indent=2)
