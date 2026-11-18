# 09: Apply ke Antigravity CLI — happy path

**What to build:** Pengguna bisa menerapkan akun ke Antigravity CLI. Token divalidasi ke Google sebelum apa pun disentuh, sesi `agy` dibereskan, snapshot dibuat, lalu keyring `gemini/antigravity` dan file `~/.gemini` ditulis dan diverifikasi ulang. Aplikasi tidak menjalankan `agy` setelah Apply.

**Blocked by:** 03, 06, 07, 08

**Status:** ready-for-agent

- [ ] Preflight memastikan availability target, akun ada di DB, `refresh_token` tidak kosong dan bentuknya wajar, serta akun dapat didekripsi bila terenkripsi; tidak ada penulisan sebelum semua lolos.
- [ ] Validasi token memanggil endpoint token Google dengan client OAuth Antigravity, timeout 30 detik, tanpa retry otomatis.
- [ ] Respons wajib memuat `access_token`, dan email dari `id_token` harus ada dan sama case-insensitive dengan email akun.
- [ ] Apply mendeteksi ulang sesi: bila plan tidak mengizinkan kill tetapi ada sesi hidup → gagal tanpa menulis; bila diizinkan → hentikan lewat state machine, lalu deteksi ulang dan pastikan tidak ada sesi hidup.
- [ ] Snapshot keyring dan file `~/.gemini` dibuat setelah sesi bersih dan sebelum tulis pertama, termasuk penanda file yang tidak ada.
- [ ] Keyring diperbarui pada item `service=gemini`, `username=antigravity`, schema `org.freedesktop.Secret.Generic`.
- [ ] Payload keyring mempertahankan `auth_method` yang ada (default `consumer`) dan `writer_id` yang ada; bila tidak ada, `writer_id` dibuat acak 32 byte base64url.
- [ ] Token menyimpan access token, token type, refresh token, expiry RFC3339 dengan skew 30 detik, dan `expires_in`.
- [ ] `oauth_creds.json` memuat access token, scope, token type, `id_token`, `expiry_date` milidetik, dan refresh token.
- [ ] `google_accounts.json` memuat `active` = email baru dan `old` = gabungan unik daftar `old` lama + email aktif sebelumnya, dikurangi email baru; email lama tidak dihapus.
- [ ] Bila `~/.gemini` belum ada, direktori dibuat dengan mode `0700` lalu file ditulis.
- [ ] Verifikasi membaca ulang keyring dan file; email dan refresh token harus cocok dengan plan dan file `~/.gemini` sinkron dengan keyring.
- [ ] Apply sukses menandai DB `applied_target='antigravity_cli'` dan waktu; dialog sukses menampilkan email, target, waktu, dan lokasi backup.
- [ ] Deteksi ulang dilakukan tepat sebelum menulis keyring; sesi baru yang muncul kapan pun setelah phase kill menggagalkan Apply tanpa penulisan, termasuk saat auto-kill aktif.
- [ ] Aplikasi tidak menjalankan `agy` dan tidak menampilkan TUI.
- [ ] Apply CLI hanya menyentuh item keyring `gemini/antigravity`, tidak pernah item lain.
