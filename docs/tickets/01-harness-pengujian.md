# 01: Harness pengujian

**What to build:** Fondasi pengujian otomatis yang dipakai seluruh tiket berikutnya. Developer bisa menjalankan `pytest` dan mendapatkan test widget (offscreen) serta fake untuk sistem eksternal tanpa pernah menyentuh database milik repo, folder OpenCode pengguna, atau `~/.gemini` pengguna.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `pytest` dan `pytest-qt` tercatat sebagai dependensi pengembangan, bukan runtime; aplikasi tetap berjalan tanpa keduanya.
- [ ] Ada `conftest.py` berisi fixture fake untuk keyring in-memory, tabel proses `/proc` palsu, stub OAuth, jam palsu, dan root filesystem sementara.
- [ ] Test widget berjalan dengan `QT_QPA_PLATFORM=offscreen`.
- [ ] Marker `integration` didaftarkan dan test bertanda itu di-skip secara default, hanya aktif lewat environment variable.
- [ ] Test yang ada tidak memakai `accounts_manager.db` milik repo, folder OpenCode pengguna, atau `~/.gemini` pengguna.
- [ ] Dijalankan dua kali berturut-turut, suite tetap lulus dan tidak meninggalkan file sisa di direktori pengguna.
