# 02: Pemilihan Target persisten + chip ConfigBar

**What to build:** Pengguna dapat memilih target `OpenCode` atau `Antigravity CLI` dari chip di ConfigBar, dan pilihannya bertahan setelah aplikasi ditutup. Mengganti target hanya mengubah mode; tidak ada kredensial yang disentuh dan tidak ada Apply otomatis.

**Blocked by:** 01

**Status:** done

- [x] Target hanya bernilai kanonik `opencode` atau `antigravity_cli`; nilai kosong/tak dikenal dianggap `opencode`.
- [x] Pilihan disimpan di QSettings organisasi `OpenCodeApp`, aplikasi `AccountManager`, key `active_target`, dan terbaca kembali pada instans baru (simulasi reopen).
- [x] Chip Target berupa `QToolButton` berteks dengan menu dropdown, gaya padding/border/font 11 px identik dengan chip DB dan Enkripsi — bukan `QComboBox` dan bukan toolbar kedua.
- [x] Urutan ConfigBar: DB, Enkripsi, Target, label Folder, lalu field folder dengan `stretch=1` dan lebar minimum 120 px; chip Target berukuran tetap.
- [x] Memilih item menu langsung mengubah teks chip dan memancarkan sinyal perubahan target.
- [x] Teks chip di-elide pada `resizeEvent` sesuai lebar tersedia; tooltip selalu memuat teks penuh.
- [x] Pada lebar 900 px ConfigBar tetap satu baris, field Folder tetap terlihat, dan tidak muncul scroll horizontal permanen.
- [x] Mengganti target tidak mengubah file OpenCode, keyring, maupun `~/.gemini`.

---

## Catatan implementasi

**Waktu build:** 2026-11-21 14:03 WITA

**Ringkasan perubahan:**

- `src/targets.py` — nilai kanonik `opencode` / `antigravity_cli`, normalisasi nilai kosong/tak dikenal ke `opencode`, label tampilan, serta load/save `active_target` ke QSettings `OpenCodeApp` / `AccountManager`.
- `src/ui/components/target_badge.py` — chip `TargetBadge` berbasis `QToolButton` dengan menu dropdown, status checked per target, sinyal `target_changed(str)`, persistensi QSettings, dan elide teks berdasarkan lebar teks penuh (bukan teks yang sedang terpangkas). Tooltip selalu berisi teks penuh.
- `src/ui/components/config_bar.py` — chip Target masuk di antara Enkripsi dan label Folder; field folder memakai `stretch=1` dan `minimumWidth=120`; sinyal target diteruskan lewat `ConfigBarWidget.target_changed`.
- `src/ui/main_window.py` — `MainWindow` menyerahkan instance QSettings yang sama ke ConfigBar, sehingga pemilihan target memakai sumber setting yang konsisten.
- `src/ui/components/__init__.py` — mengekspor `TargetBadge`.

**Keputusan teknis:**

- Target divalidasi lewat `normalize_target()`; tidak ada jalur yang menyimpan nilai target selain dua nilai kanonik.
- Lebar alami chip dihitung dari teks penuh di `sizeHint()`, sedangkan `_update_display()` memakai lebar teks penuh yang sama untuk memutuskan elide. Ini mencegah teks berubah-ubah antara penuh dan terpangkas saat resize.
- Chip memakai `QSizePolicy.Maximum`: tidak ikut melar seperti field folder, tetapi boleh menyusut sampai lebar minimum 96 px ketika window sempit.
- Widget target tidak memiliki akses ke port file/keyring/OAuth. Mengganti target hanya menulis QSettings, sehingga kredensial tidak tersentuh secara struktural.

**Test:**

- File baru `tests/test_target_selection.py` menguji normalisasi nilai, default OpenCode, perubahan teks + sinyal + persistensi, simulasi reopen, urutan layout, `stretch` folder, lebar 900 px tanpa scroll horizontal, elide pada lebar sempit dengan tooltip penuh, serta tidak berubahnya file OpenCode, `oauth_creds.json`, dan item keyring saat target diganti.
- `tests/test_widget_harness.py` diisolasi dengan QSettings INI sementara agar tidak membaca setting pengguna.
- Hasil suite: **30 passed, 2 skipped** (test integration opt-in tetap di-skip secara default).

**Catatan review:**

- Temuan elide tidak stabil sudah diperbaiki dengan menghitung lebar dari teks penuh dan override `sizeHint()`.
- State `_full_text` yang tidak terpakai dihapus.
- Test kredensial diperluas agar mencakup keyring, bukan hanya file.
- Pemeriksaan layout 900 px ditambah assertion tidak ada `QScrollArea` di ConfigBar.
