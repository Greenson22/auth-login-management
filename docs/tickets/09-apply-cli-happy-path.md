# 09: Apply ke Antigravity CLI — happy path

**What to build:** Pengguna bisa menerapkan akun ke Antigravity CLI. Token divalidasi ke Google sebelum apa pun disentuh, sesi `agy` dibereskan, snapshot dibuat, lalu keyring `gemini/antigravity` dan file `~/.gemini` ditulis dan diverifikasi ulang. Aplikasi tidak menjalankan `agy` setelah Apply.

**Blocked by:** 03, 06, 07, 08

**Status:** completed

- [x] Preflight memastikan availability target, akun ada di DB, `refresh_token` tidak kosong dan bentuknya wajar, serta akun dapat didekripsi bila terenkripsi; tidak ada penulisan sebelum semua lolos.
- [x] Validasi token memanggil endpoint token Google dengan client OAuth Antigravity, timeout 30 detik, tanpa retry otomatis.
- [x] Respons wajib memuat `access_token`, dan email dari `id_token` harus ada dan sama case-insensitive dengan email akun.
- [x] Apply mendeteksi ulang sesi: bila plan tidak mengizinkan kill tetapi ada sesi hidup → gagal tanpa menulis; bila diizinkan → hentikan lewat state machine, lalu deteksi ulang dan pastikan tidak ada sesi hidup.
- [x] Snapshot keyring dan file `~/.gemini` dibuat setelah sesi bersih dan sebelum tulis pertama, termasuk penanda file yang tidak ada.
- [x] Keyring diperbarui pada item `service=gemini`, `username=antigravity`, schema `org.freedesktop.Secret.Generic`.
- [x] Payload keyring mempertahankan `auth_method` yang ada (default `consumer`) dan `writer_id` yang ada; bila tidak ada, `writer_id` dibuat acak 32 byte base64url.
- [x] Token menyimpan access token, token type, refresh token, expiry RFC3339 dengan skew 30 detik, dan `expires_in`.
- [x] `oauth_creds.json` memuat access token, scope, token type, `id_token`, `expiry_date` milidetik, dan refresh token.
- [x] `google_accounts.json` memuat `active` = email baru dan `old` = gabungan unik daftar `old` lama + email aktif sebelumnya, dikurangi email baru; email lama tidak dihapus.
- [x] Bila `~/.gemini` belum ada, direktori dibuat dengan mode `0700` lalu file ditulis.
- [x] Verifikasi membaca ulang keyring dan file; email dan refresh token harus cocok dengan plan dan file `~/.gemini` sinkron dengan keyring.
- [x] Apply sukses menandai DB `applied_target='antigravity_cli'` dan waktu; dialog sukses menampilkan email, target, waktu, dan lokasi backup.
- [x] Deteksi ulang dilakukan tepat sebelum menulis keyring; sesi baru yang muncul kapan pun setelah phase kill menggagalkan Apply tanpa penulisan, termasuk saat auto-kill aktif.
- [x] Aplikasi tidak menjalankan `agy` dan tidak menampilkan TUI.
- [x] Apply CLI hanya menyentuh item keyring `gemini/antigravity`, tidak pernah item lain.

---

### Catatan Implementasi & Waktu Build

- **Waktu Selesai Build / Pengujian:** 2026-11-21T15:30:12+08:00
- **Modul yang dibangun / diperbarui:**
  - `src/integrations/antigravity/factory.py`:
    - `ProductionKeyringPort`: Implementasi pembacaan, penulisan (`org.freedesktop.Secret.Generic`), dan penghapusan item keyring `service=gemini`, `username=antigravity` via D-Bus Secret Service dan fallback `secret-tool`. Hanya memanipulasi item service/username spesifik tanpa menyentuh item lain.
    - `ProductionGeminiFilesPort`: Pembacaan dan penulisan atomic `oauth_creds.json` dan `google_accounts.json` dengan izin `0600`, serta pembuatan direktori `~/.gemini` berizin `0700` jika belum ada.
    - `ProductionOAuthPort`: Penukaran token OAuth langsung ke endpoint Google dengan `client_id` Antigravity CLI resmi, timeout 30 detik, tanpa retry otomatis.
  - `src/integrations/antigravity/service.py`:
    - `build_plan`: Preflight availability, validasi integritas format `refresh_token`, pertukaran token OAuth Google, verifikasi `access_token` dan pencocokan email `id_token` secara case-insensitive terhadap akun DB.
    - `_apply_cli`: Orkestrasi lengkap:
      1. Deteksi dan penghentian sesi `agy` via state machine (jika diizinkan).
      2. Recheck sesi sesaat sebelum penulisan untuk mengantisipasi race sesi baru.
      3. Pembuatan snapshot backup keyring & file `~/.gemini` sebelum tulis pertama.
      4. Penulisan item keyring `gemini/antigravity` dengan mempertahankan `auth_method` dan `writer_id` yang ada (atau membuat 32 byte base64url baru), serta penulisan expiry RFC3339 ber-skew 30 detik.
      5. Penulisan `oauth_creds.json` & `google_accounts.json` (mempertahankan daftar riwayat `old`).
      6. Verifikasi membaca ulang keyring dan file; memicu otomatis rollback bila terdeteksi ketidakcocokan.
      7. Penandaan status database `applied_target='antigravity_cli'` dan `last_applied_at`.
      8. Pembersihan retensi 30 backup terbaru.
  - `src/ui/main_window.py`:
    - Alur dua tahap: `build_plan` asinkron, dialog konfirmasi penghentian sesi `AgyConfirmDialog` bila diperlukan, lalu eksekusi `apply` asinkron dengan laporan detail lokasi backup dan waktu apply.
    - Tidak memanggil atau mengeksekusi binary `agy` setelah apply.
  - `tests/test_apply_cli_happy_path.py`:
    - Pengujian unit komprehensif menguji end-to-end happy path, retensi auth_method/writer_id, penggabungan email unik pada google_accounts.json, pembatasan preflight token, pembatalan akibat email mismatch pada id_token, pembuatan direktori `0700`, dan pembatalan dengan rollback saat verifikasi gagal.
