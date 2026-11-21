# 11: Ketahanan Apply CLI — error, rollback, rotasi token, toggle file

**What to build:** Apply ke Antigravity CLI gagal dengan aman. Token mati atau milik akun lain tidak pernah ditulis, setiap kegagalan setelah penulisan pertama di-rollback penuh, refresh token hasil rotasi disimpan agar tidak ada dua kebenaran, dan pengguna bisa memilih hanya memperbarui keyring tanpa menyentuh `~/.gemini`.

**Blocked by:** 09

**Status:** completed

- [x] `invalid_grant` dipetakan ke pesan "login ulang" dan `unauthorized_client` ke pesan token bukan milik client Antigravity; tidak ada penulisan maupun backup.
- [x] `id_token` tanpa email atau email berbeda dari akun menggagalkan Apply sebelum backup dan tanpa penulisan.
- [x] Bila Google mengembalikan refresh token baru, keyring dan DB memakai token baru; konfigurasi akun di DB tetap source of truth.
- [x] `write_gemini_files=false` hanya menulis keyring dan DB; tidak ada file `~/.gemini` yang ditulis atau dibuat, dan verifikasi file dilewati.
- [x] Kegagalan menulis `oauth_creds.json` setelah keyring berhasil memicu pemulihan keyring dan file lain; DB tidak ditandai.
- [x] Ketidakcocokan saat verifikasi memicu rollback penuh dan pesan memuat lokasi backup.
- [x] Kegagalan menandai DB memicu rollback keyring dan file.
- [x] Pesan kegagalan menyebut langkah yang gagal, tindakan berikutnya, dan secara eksplisit apakah perubahan sudah di-rollback atau belum.
- [x] Kegagalan jaringan tidak di-retry otomatis; pengguna memilih Apply lagi.
- [x] Rate limit atau respons Google non-JSON dipetakan ke pesan "coba lagi" tanpa membocorkan respons mentah.
- [x] Kegagalan dekripsi memakai pesan yang sudah ada agar konsisten dengan fitur copy/update.
- [x] Tidak ada token utuh di dialog, pesan error, atau log; nilai yang perlu disebut diredaksi dengan pola awal/akhir.
- [x] Password enkripsi hanya dipakai sesaat untuk dekripsi dan tidak disimpan atau ditulis ulang oleh fitur ini.

---

## Catatan Implementasi

**Tanggal selesai:** 2026-11-21T07:44:12Z (UTC)

### File yang diimplementasikan / diubah

| File | Perubahan |
|---|---|
| `src/integrations/antigravity/service.py` | Fix pemetaan error OAuth: `rate_limit_exceeded`, `too_many_requests`, `quota_exceeded` dipetakan ke pesan "coba lagi"; respons mentah (HTML) tidak dimasukkan ke pesan user (sanitasi `< 80 char` dan tanpa `<`). Semua logika ketahanan lainnya sudah ada sejak tiket 06–09. |
| `tests/test_ketahanan_apply_cli.py` | **File baru** — 18 test yang mendokumentasikan perilaku ketahanan. |

### Detail fix `service.py`

Sebelumnya, error OAuth yang tidak dikenal (termasuk `rate_limit_exceeded`) langsung memasukkan `description` mentah server ke pesan user, berpotensi membocorkan HTML atau teks internal. Setelah fix:

```python
elif err_code in ("rate_limit_exceeded", "too_many_requests", "quota_exceeded"):
    msg = "Batas permintaan Google terlampaui. Coba lagi beberapa saat."
else:
    # Sanitasi: jangan bocorkan respons HTML atau teks mentah
    safe_desc = err_desc if err_desc and len(err_desc) <= 80 and "<" not in err_desc else ""
    msg = f"Gagal memvalidasi token ke Google ({err_code}). Coba lagi atau login ulang."
```

### Test yang ditambahkan

| Test | Kriteria |
|---|---|
| `test_invalid_grant_dipetakan_ke_pesan_login_ulang` | #1 |
| `test_unauthorized_client_dipetakan_ke_pesan_bukan_milik_client` | #1 |
| `test_id_token_tanpa_email_gagal_sebelum_tulis` | #2 |
| `test_email_berbeda_dari_akun_gagal_sebelum_tulis` | #2 |
| `test_rotasi_refresh_token_disimpan_ke_keyring_dan_db` | #3 |
| `test_tidak_ada_rotasi_jika_token_sama` | #3 |
| `test_write_gemini_files_false_tidak_menulis_file` | #4 |
| `test_gagal_tulis_oauth_creds_rollback_keyring_db_tidak_ditandai` | #5 |
| `test_verifikasi_gagal_rollback_penuh_dan_pesan_berisi_backup_lokasi` | #6 |
| `test_gagal_tandai_db_memicu_rollback_keyring_dan_file` | #7 |
| `test_pesan_kegagalan_menyebut_langkah_dan_rollback_eksplisit` | #8 |
| `test_pesan_kegagalan_preflight_menyebut_langkah_yang_gagal` | #8 |
| `test_kegagalan_jaringan_tidak_retry_otomatis` | #9 |
| `test_rate_limit_dipetakan_ke_pesan_coba_lagi` | #10 |
| `test_kegagalan_dekripsi_menggunakan_pesan_yang_ada` | #11 |
| `test_token_tidak_muncul_utuh_di_pesan_error` | #12 |
| `test_token_tidak_muncul_utuh_di_plan_error_message` | #12 |
| `test_password_enkripsi_tidak_disimpan_di_keyring_atau_file` | #13 |

### Hasil build

```
Waktu build: 2026-11-21T07:44:12Z (UTC) / 15:44:12 WIB
Command:     uv run pytest tests/
Hasil:       139 passed, 2 skipped (tidak ada regresi)
Test baru:   18 (semua pass, 0 fail)
```
