# Pengujian

Dependensi test adalah dependensi pengembangan. Aplikasi tetap berjalan tanpa
`pytest` maupun `pytest-qt`.

```bash
python3 -m venv .env
.env/bin/pip install -r requirements-dev.txt
.env/bin/python -m pytest
```

Test widget selalu berjalan dengan `QT_QPA_PLATFORM=offscreen`; tidak perlu
display atau X server.

## Isolasi

Fixture `fake_root` (autouse lewat `isolated_user_environment`) mengarahkan
`HOME`, seluruh folder XDG, dan working directory ke `tmp_path` milik pytest.
Konsekuensinya:

- database default `accounts_manager.db` dibuat di folder sementara, bukan repo;
- folder OpenCode pengguna tidak tersentuh;
- `~/.gemini` dan keyring asli tidak tersentuh.

Fixture yang tersedia di `tests/conftest.py`:

- `fake_keyring` — keyring in-memory, bisa dikunci/dimatikan;
- `fake_proc` — tabel proses `/proc` palsu;
- `fake_signals` — pencatat sinyal untuk tabel proses palsu;
- `fake_oauth` — stub penukaran refresh token Google;
- `fake_clock` — jam yang hanya bergerak saat `advance()`/`sleep()` dipanggil;
- `fake_root` — root filesystem sementara beserta path home/XDG/OpenCode.

## Test integration (opt-in)

Test yang menyentuh keyring/D-Bus nyata ditandai `integration` dan di-skip
secara default. Aktifkan hanya saat ingin mengujinya:

```bash
AUTH_MANAGER_RUN_INTEGRATION=1 .env/bin/python -m pytest
```

Test keyring nyata memakai item sementara `service=selftest` lewat
`secret-tool` (dependensi sistem opsional) dan tidak pernah menyentuh item
`gemini`. Bila `secret-tool` tidak terpasang, test tersebut skip. Test proses
nyata memakai `sleep` yang di-`SIGSTOP` untuk memverifikasi jalur
`SIGCONT` → `SIGTERM`.
