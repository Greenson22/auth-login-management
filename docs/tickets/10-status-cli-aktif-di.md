# 10: Status Antigravity CLI dan "Aktif di" dua target

**What to build:** Pengguna melihat akun yang benar-benar terpasang di Antigravity CLI — dibaca dari keyring dan `~/.gemini`, bukan dari setting — termasuk saat keyring kosong, terkunci, menunjuk akun "liar", atau tidak sinkron dengan file. Kolom "Aktif di" menunjukkan status per akun untuk kedua target.

**Blocked by:** 04, 09

**Status:** ready-for-agent

- [ ] `read status` CLI membaca email dari payload keyring; keyring kosong → `none`.
- [ ] Email keyring yang tidak ada di DB → `unrecorded`.
- [ ] Keyring dan `~/.gemini` menunjuk email berbeda → `drift_gemini`, dan status tetap menampilkan email keyring sebagai Active Account.
- [ ] Keyring terkunci → `locked`; OS tidak didukung → `unavailable` beserta alasan ketidaktersediaan; kegagalan lain → `error`.
- [ ] Untuk CLI, status menyertakan ringkasan sesi (jumlah hidup/stopped/zombie) dan alasan ketidaktersediaan.
- [ ] `read status` CLI tidak pernah melempar exception ke pemanggil, termasuk saat `/proc` tidak terbaca.
- [ ] Chip Target menandai akun aktif yang tidak tercatat di DB dan kondisi file/keyring bermasalah sesuai matriks status; tooltip memuat teks penuh, email aktif, kondisi, alasan ketidaktersediaan, dan ringkasan sesi.
- [ ] Kolom "Aktif di" menampilkan `Antigravity CLI` bila hanya aktif di CLI, `OpenCode + CLI` bila aktif di keduanya, `OpenCode` bila hanya OpenCode, dan `—` bila tidak ada — semua case-insensitive.
- [ ] Kolom audit DB (`applied_target`, `last_applied_at`) tidak dipakai untuk kolom "Aktif di"; nilainya hanya untuk audit dan tooltip kecil.
- [ ] Status diperbarui saat aplikasi start, setiap reload, setelah Apply, setelah kill, dan setelah restore.
