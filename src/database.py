import sqlite3
import json

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
        """Parsing JSON dan menyimpannya ke database."""
        data = json.loads(raw_json_str)
        
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
                            remaining_fraction_reset_time=excluded.remaining_fraction_reset_time,
                            model_count=excluded.model_count
                    ''', (
                        acc_id, model_name, q.get("remainingFraction", 1.0),
                        q.get("resetTime"), q.get("remainingFractionResetTime"),
                        q.get("modelCount", 1)
                    ))
                
                inserted_count += 1
            conn.commit()
        return inserted_count

    def fetch_accounts_summary(self):
        """Mengambil Email, Reset Time per model, dan ID untuk keperluan UI."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT 
                    a.id,
                    a.email,
                    MAX(CASE WHEN q.model_name = 'gemini-flash' THEN q.reset_time END) AS flash_reset,
                    MAX(CASE WHEN q.model_name = 'gemini-pro' THEN q.reset_time END) AS pro_reset,
                    MAX(CASE WHEN q.model_name = 'claude' THEN q.reset_time END) AS claude_reset
                FROM accounts a
                LEFT JOIN account_quotas q ON a.id = q.account_id
                GROUP BY a.id
                ORDER BY a.created_at DESC
            '''
            return cursor.execute(query).fetchall()

    def reconstruct_json_by_id(self, account_id):
        """Membuka kembali data dari SQLite dan mengembalikannya ke format JSON utuh."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Ambil Data Akun
            acc_row = cursor.execute('''
                SELECT id, refresh_token, project_id, email, enabled, added_at, 
                       last_used, verification_required, managed_project_id, cached_quota_updated_at
                FROM accounts WHERE id = ?
            ''', (account_id,)).fetchone()
            
            if not acc_row:
                return None

            # Ambil Fingerprint
            fp_row = cursor.execute('''
                SELECT device_id, session_token, user_agent, api_client, 
                       ide_type, platform, plugin_type, created_at
                FROM account_fingerprints WHERE account_id = ?
            ''', (account_id,)).fetchone()

            # Ambil Quotas
            quota_rows = cursor.execute('''
                SELECT model_name, remaining_fraction, reset_time, remaining_fraction_reset_time, model_count
                FROM account_quotas WHERE account_id = ?
            ''', (account_id,)).fetchall()

            # Konstruksi Objek JSON Utuh
            cached_quota = {}
            for q in quota_rows:
                cached_quota[q[0]] = {
                    "remainingFraction": q[1],
                    "resetTime": q[2],
                    "remainingFractionResetTime": q[3],
                    "modelCount": q[4]
                }

            account_json = {
                "id": acc_row[0],
                "refreshToken": acc_row[1],
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
                    "sessionToken": fp_row[1] if fp_row else "",
                    "userAgent": fp_row[2] if fp_row else "",
                    "apiClient": fp_row[3] if fp_row else "",
                    "clientMetadata": {
                        "ideType": fp_row[4] if fp_row else "",
                        "platform": fp_row[5] if fp_row else "",
                        "pluginType": fp_row[6] if fp_row else ""
                    },
                    "createdAt": fp_row[7] if fp_row else 0
                },
                "fingerprintHistory": [],
                "cachedQuota": cached_quota,
                "cachedQuotaUpdatedAt": acc_row[9]
            }

            return json.dumps(account_json, indent=2)