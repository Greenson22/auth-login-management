import json
import sqlite3
from typing import Optional
from src.crypto import decrypt_aes256, encrypt_aes256
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
            is_encrypted INTEGER NOT NULL DEFAULT 0,
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
        # Migrasi kolom is_encrypted bila tabel sudah ada sebelumnya
        try:
          self.turso_client.execute("ALTER TABLE accounts ADD COLUMN is_encrypted INTEGER NOT NULL DEFAULT 0")
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
        # Migrasi kolom is_encrypted untuk SQLite lokal
        cursor.execute("PRAGMA table_info(accounts);")
        columns = [row[1] for row in cursor.fetchall()]
        if "is_encrypted" not in columns:
          cursor.execute("ALTER TABLE accounts ADD COLUMN is_encrypted INTEGER NOT NULL DEFAULT 0;")
        conn.commit()

  def insert_or_update_json(
      self, raw_json_str: str, encrypt: bool = False, password: str = ""
  ) -> int:
    """Parsing JSON dan menyimpannya ke database (Local SQLite atau Turso).

    Jika encrypt=True dan password diberikan, refreshToken dan sessionToken
    akan dienkripsi dengan AES-256 dan ditandai is_encrypted=1.
    """
    data = json.loads(raw_json_str)
    accounts = (
        data.get("accounts", [data])
        if isinstance(data, dict) and "accounts" in data
        else data
    )
    if isinstance(accounts, dict):
      accounts = [accounts]

    inserted_count = 0
    is_encrypted_val = 1 if (encrypt and password) else 0

    if self.use_turso and self.turso_client:
      pipeline_stmts = []
      for acc in accounts:
        if "id" not in acc or "email" not in acc:
          continue
        acc_id = acc.get("id")
        raw_rt = acc.get("refreshToken", "")
        stored_rt = (
            encrypt_aes256(raw_rt, password)
            if is_encrypted_val and raw_rt
            else raw_rt
        )

        sql_acc = """
            INSERT INTO accounts (
                id, email, refresh_token, project_id, managed_project_id,
                enabled, verification_required, added_at, last_used, cached_quota_updated_at,
                is_encrypted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                email=excluded.email,
                refresh_token=excluded.refresh_token,
                enabled=excluded.enabled,
                last_used=excluded.last_used,
                cached_quota_updated_at=excluded.cached_quota_updated_at,
                is_encrypted=excluded.is_encrypted
        """
        args_acc = [
            acc_id,
            acc.get("email"),
            stored_rt,
            acc.get("projectId"),
            acc.get("managedProjectId"),
            1 if acc.get("enabled", True) else 0,
            1 if acc.get("verificationRequired", False) else 0,
            acc.get("addedAt"),
            acc.get("lastUsed"),
            acc.get("cachedQuotaUpdatedAt"),
            is_encrypted_val,
        ]
        pipeline_stmts.append((sql_acc, args_acc))

        fp = acc.get("fingerprint", {})
        cm = fp.get("clientMetadata", {})
        raw_st = fp.get("sessionToken", "")
        stored_st = (
            encrypt_aes256(raw_st, password)
            if is_encrypted_val and raw_st
            else raw_st
        )

        sql_fp = """
            INSERT INTO account_fingerprints (
                account_id, device_id, session_token, user_agent,
                api_client, ide_type, platform, plugin_type, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
                device_id=excluded.device_id,
                session_token=excluded.session_token,
                user_agent=excluded.user_agent,
                api_client=excluded.api_client
        """
        args_fp = [
            acc_id,
            fp.get("deviceId"),
            stored_st,
            fp.get("userAgent"),
            fp.get("apiClient"),
            cm.get("ideType"),
            cm.get("platform"),
            cm.get("pluginType"),
            fp.get("createdAt"),
        ]
        pipeline_stmts.append((sql_fp, args_fp))

        quotas = acc.get("cachedQuota", {})
        for model_name, q in quotas.items():
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
          args_q = [
              acc_id,
              model_name,
              q.get("remainingFraction", 1.0),
              q.get("resetTime"),
              q.get("remainingFractionResetTime"),
              q.get("modelCount", 1),
          ]
          pipeline_stmts.append((sql_q, args_q))

        inserted_count += 1

      if pipeline_stmts:
        self.turso_client.execute_pipeline(pipeline_stmts)

      return inserted_count

    else:
      with self.get_connection() as conn:
        cursor = conn.cursor()
        for acc in accounts:
          if "id" not in acc or "email" not in acc:
            continue
          acc_id = acc.get("id")
          raw_rt = acc.get("refreshToken", "")
          stored_rt = (
              encrypt_aes256(raw_rt, password)
              if is_encrypted_val and raw_rt
              else raw_rt
          )

          cursor.execute(
              """
              INSERT INTO accounts (
                  id, email, refresh_token, project_id, managed_project_id,
                  enabled, verification_required, added_at, last_used, cached_quota_updated_at,
                  is_encrypted
              ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
              ON CONFLICT(id) DO UPDATE SET
                  email=excluded.email,
                  refresh_token=excluded.refresh_token,
                  enabled=excluded.enabled,
                  last_used=excluded.last_used,
                  cached_quota_updated_at=excluded.cached_quota_updated_at,
                  is_encrypted=excluded.is_encrypted
              """,
              (
                  acc_id,
                  acc.get("email"),
                  stored_rt,
                  acc.get("projectId"),
                  acc.get("managedProjectId"),
                  1 if acc.get("enabled", True) else 0,
                  1 if acc.get("verificationRequired", False) else 0,
                  acc.get("addedAt"),
                  acc.get("lastUsed"),
                  acc.get("cachedQuotaUpdatedAt"),
                  is_encrypted_val,
              ),
          )
          fp = acc.get("fingerprint", {})
          cm = fp.get("clientMetadata", {})
          raw_st = fp.get("sessionToken", "")
          stored_st = (
              encrypt_aes256(raw_st, password)
              if is_encrypted_val and raw_st
              else raw_st
          )

          cursor.execute(
              """
              INSERT INTO account_fingerprints (
                  account_id, device_id, session_token, user_agent,
                  api_client, ide_type, platform, plugin_type, created_at
              ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
              ON CONFLICT(account_id) DO UPDATE SET
                  device_id=excluded.device_id,
                  session_token=excluded.session_token,
                  user_agent=excluded.user_agent,
                  api_client=excluded.api_client
              """,
              (
                  acc_id,
                  fp.get("deviceId"),
                  stored_st,
                  fp.get("userAgent"),
                  fp.get("apiClient"),
                  cm.get("ideType"),
                  cm.get("platform"),
                  cm.get("pluginType"),
                  fp.get("createdAt"),
              ),
          )
          quotas = acc.get("cachedQuota", {})
          for model_name, q in quotas.items():
            cursor.execute(
                """
                INSERT INTO account_quotas (
                    account_id, model_name, remaining_fraction, reset_time,
                    remaining_fraction_reset_time, model_count
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, model_name) DO UPDATE SET
                    remaining_fraction=excluded.remaining_fraction,
                    reset_time=excluded.reset_time,
                    remaining_fraction_reset_time=excluded.remaining_fraction_reset_time,
                    model_count=excluded.model_count
                """,
                (
                    acc_id,
                    model_name,
                    q.get("remainingFraction", 1.0),
                    q.get("resetTime"),
                    q.get("remainingFractionResetTime"),
                    q.get("modelCount", 1),
                ),
            )
          inserted_count += 1
        conn.commit()
      return inserted_count

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

  def fetch_accounts_summary(self):
    """Mengambil Email, Reset Time, dan Remaining Fraction per model untuk keperluan UI."""
    query = """
        SELECT 
            a.id,
            a.email,
            MAX(CASE WHEN q.model_name = 'gemini-flash' THEN q.reset_time END) AS flash_reset,
            MAX(CASE WHEN q.model_name = 'gemini-flash' THEN q.remaining_fraction END) AS flash_frac,
            MAX(CASE WHEN q.model_name = 'gemini-pro' THEN q.reset_time END) AS pro_reset,
            MAX(CASE WHEN q.model_name = 'gemini-pro' THEN q.remaining_fraction END) AS pro_frac,
            MAX(CASE WHEN q.model_name = 'claude' THEN q.reset_time END) AS claude_reset,
            MAX(CASE WHEN q.model_name = 'claude' THEN q.remaining_fraction END) AS claude_frac
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

    Jika akun tersimpan dalam kondisi terenkripsi (is_encrypted == 1), data token
    akan didekripsi menggunakan password.
    """
    query_acc = """
        SELECT id, refresh_token, project_id, email, enabled, added_at,
                last_used, verification_required, managed_project_id, cached_quota_updated_at,
                is_encrypted
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

    cached_quota = {}
    for q in quota_rows:
      cached_quota[q[0]] = {
          "remainingFraction": q[1],
          "resetTime": q[2],
          "remainingFractionResetTime": q[3],
          "modelCount": q[4],
      }

    is_encrypted = bool(acc_row[10]) if len(acc_row) > 10 and acc_row[10] else False
    raw_rt = acc_row[1] or ""
    raw_st = fp_row[1] if fp_row and fp_row[1] else ""

    if is_encrypted:
      if not password:
        raise ValueError(
            "Akun ini terenkripsi. Silakan atur/masukkan password enkripsi di Menu Pengaturan."
        )
      try:
        final_refresh_token = decrypt_aes256(raw_rt, password) if raw_rt else ""
        final_session_token = decrypt_aes256(raw_st, password) if raw_st else ""
      except Exception as e:
        raise ValueError(
            f"Gagal mendekripsi akun (password mungkin salah atau data korup): {e}"
        )
    else:
      final_refresh_token = raw_rt
      final_session_token = raw_st

    account_json = {
        "id": acc_row[0],
        "refreshToken": final_refresh_token,
        "projectId": acc_row[2],
        "email": acc_row[3],
        "enabled": bool(acc_row[4]),
        "addedAt": acc_row[5],
        "lastUsed": acc_row[6],
        "verificationRequired": bool(acc_row[7]),
        "managedProjectId": acc_row[8],
        "rateLimitResetTimes": {},
        "fingerprint": {
            "deviceId": fp_row[0] if fp_row else "",
            "sessionToken": final_session_token,
            "userAgent": fp_row[2] if fp_row else "",
            "apiClient": fp_row[3] if fp_row else "",
            "clientMetadata": {
                "ideType": fp_row[4] if fp_row else "",
                "platform": fp_row[5] if fp_row else "",
                "pluginType": fp_row[6] if fp_row else "",
            },
            "createdAt": fp_row[7] if fp_row else 0,
        },
        "fingerprintHistory": [],
        "cachedQuota": cached_quota,
        "cachedQuotaUpdatedAt": acc_row[9],
    }

    full_config = {
        "version": 4,
        "accounts": [account_json],
        "activeIndex": 0,
        "activeIndexByFamily": {"claude": 0, "gemini": 0},
    }
    return json.dumps(full_config, indent=2)
