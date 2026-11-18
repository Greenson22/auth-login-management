# 02: Pemilihan Target persisten + chip ConfigBar

**What to build:** Pengguna dapat memilih target `OpenCode` atau `Antigravity CLI` dari chip di ConfigBar, dan pilihannya bertahan setelah aplikasi ditutup. Mengganti target hanya mengubah mode; tidak ada kredensial yang disentuh dan tidak ada Apply otomatis.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Target hanya bernilai kanonik `opencode` atau `antigravity_cli`; nilai kosong/tak dikenal dianggap `opencode`.
- [ ] Pilihan disimpan di QSettings organisasi `OpenCodeApp`, aplikasi `AccountManager`, key `active_target`, dan terbaca kembali pada instans baru (simulasi reopen).
- [ ] Chip Target berupa `QToolButton` berteks dengan menu dropdown, gaya padding/border/font 11 px identik dengan chip DB dan Enkripsi — bukan `QComboBox` dan bukan toolbar kedua.
- [ ] Urutan ConfigBar: DB, Enkripsi, Target, label Folder, lalu field folder dengan `stretch=1` dan lebar minimum 120 px; chip Target berukuran tetap.
- [ ] Memilih item menu langsung mengubah teks chip dan memancarkan sinyal perubahan target.
- [ ] Teks chip di-elide pada `resizeEvent` sesuai lebar tersedia; tooltip selalu memuat teks penuh.
- [ ] Pada lebar 900 px ConfigBar tetap satu baris, field Folder tetap terlihat, dan tidak muncul scroll horizontal permanen.
- [ ] Mengganti target tidak mengubah file OpenCode, keyring, maupun `~/.gemini`.
