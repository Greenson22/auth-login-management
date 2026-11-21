# 10: Status Antigravity CLI dan "Aktif di" dua target

**What to build:** Pengguna melihat akun yang benar-benar terpasang di Antigravity CLI — dibaca dari keyring dan `~/.gemini`, bukan dari setting — termasuk saat keyring kosong, terkunci, menunjuk akun "liar", atau tidak sinkron dengan file. Kolom "Aktif di" menunjukkan status per akun untuk kedua target.

**Blocked by:** 04, 09

**Status:** completed

- [x] `read status` CLI membaca email dari payload keyring; keyring kosong → `none`.
- [x] Email keyring yang tidak ada di DB → `unrecorded`.
- [x] Keyring dan `~/.gemini` menunjuk email berbeda → `drift_gemini`, dan status tetap menampilkan email keyring sebagai Active Account.
- [x] Keyring terkunci → `locked`; OS tidak didukung → `unavailable` beserta alasan ketidaktersediaan; kegagalan lain → `error`.
- [x] Untuk CLI, status menyertakan ringkasan sesi (jumlah hidup/stopped/zombie) dan alasan ketidaktersediaan.
- [x] `read status` CLI tidak pernah melempar exception ke pemanggil, termasuk saat `/proc` tidak terbaca.
- [x] Chip Target menandai akun aktif yang tidak tercatat di DB dan kondisi file/keyring bermasalah sesuai matriks status; tooltip memuat teks penuh, email aktif, kondisi, alasan ketidaktersediaan, dan ringkasan sesi.
- [x] Kolom "Aktif di" menampilkan `Antigravity CLI` bila hanya aktif di CLI, `OpenCode + CLI` bila aktif di keduanya, `OpenCode` bila hanya OpenCode, dan `—` bila tidak ada — semua case-insensitive.
- [x] Kolom audit DB (`applied_target`, `last_applied_at`) tidak dipakai untuk kolom "Aktif di"; nilainya hanya untuk audit dan tooltip kecil.
- [x] Status diperbarui saat aplikasi start, setiap reload, setelah Apply, setelah kill, dan setelah restore.

---

### Catatan Implementasi & Waktu Build

- **Waktu Selesai Build / Pengujian:** 2026-11-21T15:39:32+08:00
- **Modul yang dibangun / diperbarui:**
  - `src/integrations/antigravity/service.py`:
    - `_read_cli_status`: Implementasi pembacaan status CLI dari keyring (`gemini/antigravity`), drift check vs `~/.gemini`, unrecorded jika tidak ada di DB, locked/unavailable/error, sessions summary. Tidak melempar exception ke pemanggil.
  - `src/ui/components/target_badge.py`:
    - `_full_tooltip`: Format human-readable untuk ringkasan sesi CLI.
  - `src/ui/components/account_table.py`:
    - Menampilkan audit tooltip dari DB pada kolom "Aktif di", sementara nilai teks kolom tetap dari `compute_active_di`.
  - `tests/test_cli_status_and_active_di.py`:
    - 8 test suite lengkap untuk status CLI dan kolom "Aktif di".
- **Hasil build:** 121 passed, 2 skipped
- **Commit:** `f6616a1`
