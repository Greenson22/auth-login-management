# 08: Backup, rollback, dan restore

**What to build:** Setiap Apply punya titik pulih. Snapshot keyring dan file target dibuat sebelum penulisan, kegagalan memicu rollback otomatis, dan pengguna bisa memulihkan backup terakhir lewat menu tanpa mencari file sendiri.

**Blocked by:** 01

**Status:** completed

- [x] Direktori backup `~/.local/state/auth-login-management/backups/<timestamp>/` bermode `0700` dan file di dalamnya `0600`.
- [x] Setiap backup berisi salinan item keyring dan file target yang ada pada saat itu.
- [x] `meta.json` mencatat target, email, waktu, versi aplikasi, PID yang dihentikan, dan daftar artefak beserta status "ada"/"tidak ada".
- [x] Restore mengembalikan isi artefak yang ada, dan menghapus artefak yang sebelumnya tidak ada — baik item keyring maupun file.
- [x] Restore tidak mengubah kolom audit DB; indikator tetap membaca kenyataan.
- [x] Retensi menyisakan 30 backup terbaru dan dilakukan setelah Apply sukses, sehingga backup yang baru dibuat tidak ikut terhapus.
- [x] Rollback otomatis mengembalikan keyring dan file dari snapshot lalu melaporkan kegagalan asli; penandaan DB tidak pernah terjadi lebih dulu.
- [x] Bila kegagalan terjadi setelah snapshot dibuat, snapshot dipertahankan dan lokasinya disebutkan di dialog kegagalan.
- [x] Menu Pengaturan memiliki aksi "Pulihkan Backup Terakhir…" dengan konfirmasi yang menyebut waktu, target, dan email dari manifest, serta menyatakan bahwa backup berisi kredensial.
- [x] Tidak ada backup, keyring, atau file lain yang dibaca/ditulis ketika tidak ada backup.

---

### Catatan Implementasi & Waktu Build

- **Waktu Selesai Build / Pengujian:** 2026-11-21T15:18:31+08:00
- **Modul yang dibangun / diperbarui:**
  - `src/integrations/antigravity/backup.py`:
    - Fungsi `create_cli_backup` dan `create_opencode_backup` membuat direktori backup berizin `0700` dan file di dalamnya `0600`.
    - Manifes `meta.json` menyimpan target, email, timestamp, `app_version`, `stopped_pids`, serta status `present`/`absent` dari masing-masing artefak (keyring `keyring_item.bin`, `oauth_creds.json`, `google_accounts.json`, dan `antigravity-accounts.json`).
    - Fungsi `rollback_from_backup`: Memulihkan file dan item keyring yang berstatus `present` (dengan chmod `0600`), dan **menghapus** (`unlink`/`delete`) artefak yang sebelumnya `absent` agar kondisi kembali persis seperti semula.
    - Fungsi `list_backups` dan `get_latest_backup` untuk mendeteksi backup terbaru berdasarkan timestamp manifest.
    - Fungsi `cleanup_old_backups(max_keep=30)`: Membersihkan backup lama dan mempertahankan 30 snapshot terbaru.
  - `src/integrations/antigravity/service.py`:
    - Rollback otomatis saat penulisan file gagal atau penandaan database gagal pada alur apply OpenCode/CLI sebelum melaporkan status `FAILED`.
    - Mengembalikan `backup_location` pada `ApplyResult` saat terjadi kegagalan setelah snapshot dibuat.
    - Implementasi `restore_last_backup()` pada `AntigravityFacade` untuk memulihkan backup terakhir tanpa mengubah kolom audit database.
  - `src/ui/main_window.py`:
    - Menambahkan aksi menu **"Pulihkan Backup Terakhir…"** di Menu Pengaturan (`settings_menu`).
    - Menyediakan dialog konfirmasi sebelum restore yang menampilkan target, email, waktu backup, lokasi snapshot, serta penegasan bahwa backup berisi kredensial akun.
    - Menampilkan lokasi backup snapshot pada dialog peringatan ketika Apply akun gagal.
  - `tests/test_backup_rollback_restore.py`:
    - Suite pengujian komprehensif (12 test cases) mencakup verifikasi izin `0700`/`0600`, struktur `meta.json`, pemulihan artefak present dan penghapusan artefak absent, retensi 30 backup, rollback otomatis saat error write/DB, audit DB tidak terpengaruh saat restore, no-op saat tidak ada backup, dan keberadaan aksi menu Pengaturan.
- **Hasil Verifikasi:**
  - `tests/test_backup_rollback_restore.py`: 12 passed (0.41s)
  - Seluruh test suite: 106 passed, 2 skipped (3.23s)
