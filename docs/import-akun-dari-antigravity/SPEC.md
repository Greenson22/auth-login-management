# SPEC — Import Akun dari Antigravity CLI (Keyring)

> Spec ini ditulis dari [PRD.md](./PRD.md) hasil sesi `grill-with-docs`.
> Gunakan kosakata glosarium PRD §5 di seluruh kode, komentar, dan pesan UI.

---

## Problem Statement

Pengguna yang mengelola akun Google via `auth-login-management` harus menambahkan akun baru
secara manual dengan menempelkan JSON ke `JsonInputWidget`. Sementara itu, Antigravity CLI
(`agy`) sudah menyimpan akun aktifnya di GNOME Keyring (`service=gemini, username=antigravity`)
dalam format JSON yang mengandung `refresh_token` dan metadata lain.

Tidak ada cara langsung untuk mengambil data dari Keyring tersebut, memvalidasinya, dan
menyimpannya ke database — tanpa keluar dari aplikasi dan melakukan copy-paste manual.

---

## Solution

Tambahkan aksi **"Import dari Antigravity…"** di menu File yang menjalankan alur berikut:

1. Baca Keyring Item (`service=gemini, username=antigravity`) via D-Bus Secret Service.
2. Parse JSON — ekstrak `refresh_token`; decode `email` dari `id_token` JWT.
3. Validasi token secara live (exchange ke access token) di background thread.
4. Jika token valid: fetch kuota via API yang sudah ada.
5. Tampilkan **ImportDialog** — form lengkap dengan semua field yang bisa diedit.
6. Jika email sudah ada di DB: tampilkan banner duplikat + pilihan tindakan.
7. Simpan ke database (insert baru atau update token) menggunakan enkripsi sesi aktif.
8. Reload tabel akun di main window.

---

## User Stories

1. Sebagai pengguna, saya ingin mengambil akun aktif dari Antigravity CLI dengan satu klik, sehingga saya tidak perlu copy-paste JSON secara manual.
2. Sebagai pengguna, saya ingin melihat semua field akun (email, refresh token, project ID, kuota) di form sebelum menyimpan, sehingga saya bisa memastikan data benar.
3. Sebagai pengguna, saya ingin bisa mengedit field seperti kategori dan project ID di form sebelum simpan, sehingga data langsung terklasifikasi dengan benar.
4. Sebagai pengguna, saya ingin tahu apakah refresh token dari keyring masih valid sebelum disimpan, sehingga saya tidak menyimpan token yang sudah expired.
5. Sebagai pengguna, saya ingin kuota akun diambil otomatis saat import, sehingga saya tidak perlu memperbarui kuota secara terpisah setelah akun tersimpan.
6. Sebagai pengguna, saya ingin diberi tahu jika email yang diimport sudah ada di database, sehingga saya bisa memilih untuk memperbarui token atau menyimpan sebagai entri baru.
7. Sebagai pengguna, saya ingin memilih "Perbarui Token" jika email sudah ada, sehingga token lama yang mungkin sudah expired diganti token baru dari keyring.
8. Sebagai pengguna, saya ingin memilih "Tambah sebagai Entri Baru" jika email sudah ada, sehingga saya bisa menyimpan dua entri berbeda untuk email yang sama.
9. Sebagai pengguna, saya ingin bisa membatalkan form tanpa ada perubahan tersimpan ke database, sehingga aksi import tidak memiliki efek samping yang tidak diinginkan.
10. Sebagai pengguna, saya ingin melihat pesan error yang jelas jika keyring tidak tersedia atau terkunci, sehingga saya tahu apa yang harus dilakukan (mis. buka kunci keyring).
11. Sebagai pengguna, saya ingin import tetap bisa dilanjutkan meski kuota gagal diambil, sehingga satu kegagalan API tidak memblokir seluruh alur.
12. Sebagai pengguna, saya ingin import tetap bisa dilanjutkan meski token tidak valid (hanya dengan peringatan di form), sehingga saya masih bisa menyimpan token untuk referensi.
13. Sebagai pengguna, saya ingin refresh token tidak terlihat di log atau judul window, sehingga data sensitif tidak terekspos secara tidak sengaja.
14. Sebagai pengguna di platform non-Linux, saya ingin menu "Import dari Antigravity…" dinonaktifkan dengan tooltip yang jelas, sehingga saya tahu fitur ini hanya tersedia di Linux.
15. Sebagai pengguna, saya ingin password enkripsi yang sudah saya masukkan di awal sesi dipakai langsung tanpa diminta lagi, sehingga alur import tetap mulus.
16. Sebagai pengguna, saya ingin tabel akun diperbarui segera setelah simpan berhasil, sehingga akun baru langsung terlihat di daftar tanpa perlu me-refresh manual.

---

## Implementation Decisions

### 1. Modul Baru: `KeyringReader`

Buat modul **`KeyringReader`** (terpisah dari `service.py` dan `factory.py`) yang bertanggung
jawab **hanya** untuk membaca dan memparsing Keyring Item.

Antarmuka yang diekspos:

```python
# Dari prototype — ini kontrak tipe, bukan implementasi
@dataclass(frozen=True)
class KeyringImportData:
    refresh_token: str
    email: Optional[str]        # None jika id_token tidak ada atau tidak bisa di-decode
    project_id: Optional[str]   # Dari JSON keyring jika tersedia
    raw_fields: dict            # Semua field lain dari JSON keyring (untuk referensi)

class KeyringReader:
    def read_and_parse(self, keyring: KeyringPort) -> KeyringImportData:
        """Membaca service=gemini/username=antigravity, parse JSON, decode email dari id_token."""
        ...
```

`KeyringReader` hanya bergantung pada `KeyringPort` yang sudah ada — tidak ada dependensi baru.

### 2. Modul Baru: `ImportDialog` (UI)

Dialog PyQt6 independen (tidak mewarisi dialog yang ada). Menerima dependensi lewat konstruktor
(tidak langsung memanggil singleton atau DB global):

- `keyring: KeyringPort`
- `oauth: OAuthPort`
- `db: AccountDatabase`
- `password: str` — password enkripsi sesi aktif, dilewatkan dari `MainWindow`

Dialog mengelola lifecycle:
1. Baca Keyring → parse → tampilkan form awal.
2. Validasi token (via `WorkerThread` yang sudah ada) → update badge status di form.
3. Fetch kuota (via `WorkerThread`) → isi field kuota jika berhasil.
4. Simpan saat user klik "Simpan".

### 3. Integrasi di `MainWindow`

Tambahkan `QAction` di menu **File**:
- Label: "Import dari Antigravity…"
- Shortcut: `Ctrl+Shift+I` (opsional, bisa dihapus jika konflik)
- Dinonaktifkan (`setEnabled(False)`) + tooltip jika platform bukan Linux atau D-Bus tidak
  tersedia (cek via `check_cli_availability()` yang sudah ada).

Saat aksi dipicu:
```python
password = self.settings.value("encryption_password", "")
dialog = ImportDialog(
    keyring=self._get_keyring_port(),   # Port produksi atau fake
    oauth=self._get_oauth_port(),
    db=self.db,
    password=password,
    parent=self,
)
if dialog.exec() == QDialog.DialogCode.Accepted:
    self.reload_accounts()
```

### 4. Penanganan Duplikat Email

`ImportDialog` memanggil `db.fetch_accounts_summary()` dan mencocokkan email (case-insensitive)
setelah data keyring berhasil dibaca. Jika duplikat ditemukan:
- Tampilkan banner kuning di atas form dengan ID dan email akun lama.
- Tampilkan dua pilihan (radio button): **Perbarui Token** | **Tambah sebagai Entri Baru**.
- Tombol "Simpan" dinonaktifkan sampai pilihan dipilih.

### 5. Path Simpan ke Database

| Tindakan | Method DB yang dipanggil |
| --- | --- |
| Tambah Baru | `db.insert_or_update_json(json_str, encrypt=bool(password), password=password)` |
| Perbarui Token | `db.update_refresh_token(existing_id, new_token, password=password)` lalu `db.update_account_quotas(existing_id, quota_data)` jika kuota tersedia |

Tidak ada schema change — semua method sudah ada di `AccountDatabase`.

### 6. Status Token di Form

Status ditampilkan sebagai badge teks (bukan ikon gambar, untuk menghindari asset baru):

| Kondisi | Teks | Warna |
| --- | --- | --- |
| Belum divalidasi | "⏳ Memvalidasi…" | Abu-abu |
| Valid | "✅ Token Valid" | Hijau |
| Tidak valid | "❌ Token Tidak Valid: `<kode error>`" | Merah |
| Gagal koneksi | "⚠️ Validasi gagal (timeout/jaringan)" | Oranye |

### 7. Kuota: Format yang Disimpan

Menggunakan format `cachedQuota` internal yang sudah ada (output dari `parse_quota_summary_response`).
Field `cachedQuotaUpdatedAt` diisi dengan `int(time.time())` saat simpan.
Kuota masuk ke tabel `account_quotas` via `update_account_quotas()` (untuk akun baru: dipanggil
setelah insert, menggunakan ID yang baru dibuat).

### 8. Thread Safety

Semua operasi jaringan (validasi token, fetch kuota) dijalankan via `WorkerThread` yang sudah
ada di `src/ui/components/loading_dialog.py`. Dialog menampilkan indikator loading dan
memblokir tombol "Simpan" selama operasi berlangsung.

### 9. Keamanan Token

- Refresh token ditampilkan di form sebagai `SecureLineEdit` (widget yang sudah ada) — teks
  tersembunyi dengan tombol reveal.
- Refresh token tidak pernah ditulis ke `logger` pada level apapun.
- Pesan error yang menyertakan error OAuth hanya menampilkan `error_code`, bukan nilai token.

### 10. Platform Guard

```python
# Di MainWindow saat init_ui atau saat menu dibuka:
available, reason = check_cli_availability()   # fungsi sudah ada di factory.py
import_action.setEnabled(available)
if not available:
    import_action.setToolTip(REASON_MESSAGES.get(reason, "Tidak tersedia"))
```

`REASON_MESSAGES` adalah dict konstanta baru yang dipetakan dari reason code ke teks manusia.

---

## Testing Decisions

### Apa yang membuat test yang baik

- Test hanya menguji **perilaku yang terlihat dari luar** (output, state DB, panggilan ke port),
  bukan implementasi internal (metode privat, urutan baris).
- Setiap test mengatur state awal secara eksplisit lewat fake, bukan membaca DB repo atau
  keyring nyata.
- Test tidak bergantung pada urutan eksekusi satu sama lain.

### Seam Utama: `KeyringReader`

Seam tunggal yang diuji paling dalam. `KeyringReader.read_and_parse(keyring)` dipanggil dengan
`FakeKeyring` yang sudah ada di `tests/fakes.py`. Tidak perlu seam baru.

**Kasus yang diuji:**

| Kasus | Setup FakeKeyring | Hasil yang diverifikasi |
| --- | --- | --- |
| Item ada + JSON valid + id_token punya email | `fake_keyring.write(KEYRING_SERVICE, KEYRING_USERNAME, json_bytes)` | `result.email == "user@example.com"`, `result.refresh_token == "rt_xyz"` |
| Item ada + JSON tanpa id_token | JSON tanpa `id_token` | `result.email is None`, `result.refresh_token` tidak kosong |
| Item tidak ada (None) | Keyring kosong | Raise `KeyringItemNotFoundError` (exception baru, ringan) |
| Keyring tidak tersedia | `fake_keyring.available = False` | Raise `KeyringUnavailableError` (sudah ada di fakes.py) |
| Keyring terkunci | `fake_keyring.locked = True` | Raise `KeyringLockedError` (sudah ada di fakes.py) |
| JSON rusak (bukan JSON valid) | Write bytes non-JSON | Raise `KeyringParseError` (exception baru) |

### Seam Kedua: Logika Simpan di `ImportDialog`

Karena `ImportDialog` adalah widget PyQt6, test memakai harness widget yang sudah ada
(`test_widget_harness.py` sebagai prior art). Dependensi diinjeksi lewat fake.

**Kasus yang diuji:**

| Kasus | Setup | Verifikasi |
| --- | --- | --- |
| Email baru, token valid → Simpan | FakeDB tanpa email, FakeOAuth valid | `db.insert_or_update_json` dipanggil 1x; dialog close Accepted |
| Email duplikat → pilih Perbarui Token → Simpan | FakeDB dengan email sama | `db.update_refresh_token` dipanggil 1x dengan token baru |
| Email duplikat → pilih Tambah Baru → Simpan | FakeDB dengan email sama | `db.insert_or_update_json` dipanggil 1x dengan ID baru |
| Token tidak valid → Simpan tetap bisa (dengan peringatan) | FakeOAuth `fail_with("invalid_grant")` | Simpan berhasil; badge merah tampil |
| Kuota gagal → Simpan tetap bisa | FakeOAuth valid, quota fetch timeout | Simpan berhasil; `update_account_quotas` tidak dipanggil |
| Batal → DB tidak berubah | Tekan Batal | Tidak ada panggilan ke `db.insert_or_update_json` atau `update_refresh_token` |
| Email duplikat → tombol Simpan disabled sampai pilih | FakeDB dengan email sama | `save_button.isEnabled() == False` sebelum pilih; `True` setelah pilih |

### Prior Art

- **`tests/test_widget_harness.py`** — harness QApplication dan widget test; pola yang sama
  digunakan untuk `ImportDialog`.
- **`tests/test_apply_cli_happy_path.py`** — penggunaan `FakeKeyring`, `FakeOAuth`, dan
  `FakeAccountStorage`; pola perakitan fake lewat konstruktor yang sama.
- **`tests/test_quota_service.py`** — test `parse_quota_summary_response` dan
  `exchange_refresh_token_for_access_token` dengan mock HTTP; tidak perlu diulang di test baru.
- **`tests/fakes.py`** — `FakeKeyring` (dengan mode `available=False`, `locked=True`),
  `FakeOAuth` (dengan `respond_for()` dan `fail_with()`), `make_id_token()` — semua dipakai
  ulang tanpa modifikasi.

### File Test Baru

| File | Isi |
| --- | --- |
| `tests/test_keyring_reader.py` | Unit test `KeyringReader` (semua kasus di tabel seam pertama) |
| `tests/test_import_dialog.py` | Widget test `ImportDialog` (semua kasus di tabel seam kedua) |

---

## Out of Scope

- Import dari sumber selain GNOME Keyring (`service=gemini, username=antigravity`).
- Import batch dari beberapa akun; keyring selalu 1 item aktif.
- Modifikasi atau penghapusan data di keyring.
- Dukungan Windows dan macOS (Secret Service hanya Linux).
- Login/consent/OAuth baru — hanya membaca token yang sudah ada.
- Menggantikan alur input JSON manual (`JsonInputWidget`) yang sudah ada.
- Tombol "Validasi Ulang" setelah pengguna mengedit refresh token di form (OQ-1 dari PRD —
  ditunda ke v1.1).
- Penandaan audit ke Turso saat import (hanya SQLite lokal yang terpengaruh; Turso sinkronisasi
  lewat mekanisme yang sudah ada).
- Test integrasi dengan keyring nyata (sudah ada di `tests/integration/test_real_keyring.py`
  sebagai opt-in; tidak ditambah di sini).

---

## Further Notes

### Exception Baru yang Dibutuhkan

Dua exception ringan perlu ditambahkan ke modul baru atau ke `errors.py`:

```python
class KeyringItemNotFoundError(Exception):
    """Item service=gemini/username=antigravity tidak ada di keyring."""

class KeyringParseError(Exception):
    """JSON keyring tidak bisa diparsing atau tidak memiliki field yang diharapkan."""
```

`KeyringUnavailableError` dan `KeyringLockedError` sudah ada di `tests/fakes.py`; pindahkan
atau duplikat ke kode produksi (`errors.py`) agar bisa diimpor tanpa mengimpor modul test.

### Alur Token Baru yang Sudah Dirotasi Google

Jika Google telah merotasi refresh token, exchange akan mengembalikan `refresh_token` baru di
dalam respons. `ImportDialog` harus memprioritaskan token baru ini (dari respons OAuth) sebagai
nilai yang disimpan ke DB, bukan token lama dari keyring. Field refresh token di form diperbarui
otomatis setelah validasi berhasil.

### Tidak Ada Dependensi Pip Baru

`python3-dbus` sudah menjadi dependensi sistem opsional yang ada. `KeyringReader` menggunakan
`KeyringPort` yang sudah diinjeksi — tidak ada `import dbus` langsung di modul baru. Import
D-Bus nyata tetap terisolasi di `factory.py` (`ProductionKeyringPort`).

### Pemetaan ke Kriteria Penerimaan PRD

| AC PRD | Dibuktikan oleh test |
| --- | --- |
| AC-01 | `test_keyring_reader` happy path + `test_import_dialog` email baru token valid |
| AC-02 | `test_keyring_reader` item tidak ada + locked |
| AC-03 | `test_import_dialog` token valid → badge ✅ + kuota terisi |
| AC-04 | `test_import_dialog` FakeOAuth `invalid_grant` → badge ❌ |
| AC-05 | `test_import_dialog` email duplikat → banner + pilihan |
| AC-06 | `test_import_dialog` insert baru → DB check |
| AC-07 | `test_import_dialog` Perbarui Token → `update_refresh_token` dipanggil |
| AC-08 | `test_import_dialog` Batal → tidak ada panggilan DB |
| AC-09 | Dicek manual (log review); tidak ada test otomatis untuk output log |
| AC-10 | `test_import_dialog` mock `sys.platform = 'darwin'` → action disabled |
| AC-11 | Dicek manual atau smoke test; `python3-dbus` mock unavailable |
