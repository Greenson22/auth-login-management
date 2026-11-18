# 06: Availability Antigravity CLI dan grup Pengaturan Integrasi

**What to build:** Target Antigravity CLI hanya ditawarkan saat lingkungan memang mendukung, dan saat tidak mendukung pengguna melihat alasannya alih-alih mencoba aksi yang pasti gagal. Pengaturan mendapat dua saklar integrasi yang tersimpan.

**Blocked by:** 02, 04

**Status:** ready-for-agent

- [ ] Availability OpenCode selalu tersedia; validasi folder/file baru dilakukan saat build plan.
- [ ] Availability Antigravity CLI hanya benar bila OS Linux, Secret Service/D-Bus dapat dihubungi, keyring dapat dibuka, dan aplikasi bukan root.
- [ ] Alasan tidak tersedia dikembalikan sebagai kode + teks: `unsupported_os`, `no_dbus`, `keyring_locked`, `root`, `dbus_error`.
- [ ] Menu target tetap menampilkan Antigravity CLI dalam keadaan disabled dengan alasan di tooltip.
- [ ] Availability diperiksa ulang setiap kali menu dibuka, sehingga keyring yang baru dibuka pengguna langsung terdeteksi tanpa restart.
- [ ] Item Antigravity CLI di submenu "Terapkan ke…" juga disabled dengan alasan yang sama.
- [ ] Di OS non-Linux adapter keyring memakai implementasi null yang selalu melaporkan tidak tersedia; aplikasi tetap berjalan penuh untuk OpenCode.
- [ ] Pengaturan memiliki grup "Integrasi" berisi `auto_kill_agy` (default mati) dan `write_gemini_files` (default aktif), keduanya memuat dan menyimpan nilai dengan benar.
- [ ] Tidak ada tombol impor file lama pada v1.0.
