#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

VERSION="${1:-1.0.0}"
ARCH="${2:-amd64}"
PACKAGE_NAME="auth-login-manager_${VERSION}_${ARCH}"
BUILD_ROOT="${ROOT_DIR}/build/deb/${PACKAGE_NAME}"
APP_DIR="${ROOT_DIR}/dist/auth-login-manager"

# Versi glibc minimum yang ingin didukung (Ubuntu 24.04 = 2.39).
# Jika paket dibuild di distro yang lebih baru, library bundelan bisa
# membutuhkan glibc lebih tinggi dan gagal di mesin pengguna.
TARGET_GLIBC="${TARGET_GLIBC:-2.39}"

# Hapus plugin GTK dari bundel PyInstaller.
#
# Plugin platformthemes/libqgtk3.so menarik library GTK/glib dari mesin build.
# Akibatnya PyInstaller ikut membundel libglib-2.0.so.0 dan kawan-kawan dari
# distro build. Kalau distro build lebih baru dari distro pengguna, aplikasi
# gagal start dengan error "GLIBC_x.y not found".
#
# Qt tetap berjalan normal tanpa plugin ini (memakai tema XCB/Fusion).
prune_gtk_stack() {
    local internal_dir="${BUILD_ROOT}/usr/lib/auth-login-manager/_internal"
    local removed=0

    if [ -f "${internal_dir}/PyQt6/Qt6/plugins/platformthemes/libqgtk3.so" ]; then
        rm -f "${internal_dir}/PyQt6/Qt6/plugins/platformthemes/libqgtk3.so"
        removed=$((removed + 1))
    fi

    local pattern
    for pattern in \
        'libgtk-3.so*' \
        'libgdk-3.so*' \
        'libgdk_pixbuf-2.0.so*' \
        'libatk-1.0.so*' \
        'libatk-bridge-2.0.so*' \
        'libatspi.so*' \
        'libcairo.so*' \
        'libcairo-gobject.so*' \
        'libpango-1.0.so*' \
        'libpangocairo-1.0.so*' \
        'libpangoft2-1.0.so*' \
        'libharfbuzz.so*' \
        'libepoxy.so*' \
        'libglycin-2.so*' \
        'liblcms2.so*' \
        'libpixman-1.so*' \
        'libfribidi.so*' \
        'libthai.so*' \
        'libgraphite2.so*'; do
        while IFS= read -r -d '' file; do
            rm -f "${file}"
            removed=$((removed + 1))
        done < <(find "${internal_dir}" -maxdepth 1 \
            \( -type f -o -type l \) -name "${pattern}" -print0)
    done

    echo "==> Menghapus ${removed} file plugin/GTK yang tidak diperlukan."
}

# Pastikan tidak ada library bundelan yang membutuhkan glibc lebih baru
# daripada target. Pengecekan ini mencegah paket "berhasil dibuild" tetapi
# tidak bisa dibuka di distro target.
check_glibc_compat() {
    local scan_dir="$1"

    if ! command -v objdump >/dev/null 2>&1 || ! command -v ldd >/dev/null 2>&1; then
        echo "==> objdump/ldd tidak tersedia, lewati pengecekan kompatibilitas glibc."
        return 0
    fi

    local failed=0
    local required
    local newest

    while IFS= read -r -d '' file; do
        required="$(objdump -T "${file}" 2>/dev/null \
            | grep -oE 'GLIBC_[0-9]+\.[0-9]+' \
            | sed 's/^GLIBC_//' \
            | sort -V \
            | tail -n 1 || true)"

        [ -n "${required}" ] || continue

        newest="$(printf '%s\n%s\n' "${TARGET_GLIBC}" "${required}" | sort -V | tail -n 1)"
        if [ "${newest}" != "${TARGET_GLIBC}" ]; then
            echo "  ! $(basename "${file}") membutuhkan GLIBC_${required} (target: ${TARGET_GLIBC})"
            failed=1
        fi
    done < <(find "${scan_dir}" -type f \
        \( -name '*.so' -o -name '*.so.*' -o -name 'auth-login-manager' \) -print0)

    if [ "${failed}" -ne 0 ]; then
        echo "Error: ada library yang membutuhkan glibc lebih baru dari target ${TARGET_GLIBC}."
        echo "       Build paket di Ubuntu 24.04 (glibc 2.39), bukan runner/distro yang lebih baru."
        return 1
    fi

    echo "==> Kompatibilitas glibc OK (target: ${TARGET_GLIBC})."
}

echo "==> Menyiapkan direktori build .deb di ${BUILD_ROOT}..."
rm -rf "${ROOT_DIR}/build/deb"
mkdir -p "${BUILD_ROOT}/DEBIAN"
mkdir -p "${BUILD_ROOT}/usr/bin"
mkdir -p "${BUILD_ROOT}/usr/lib/auth-login-manager"
mkdir -p "${BUILD_ROOT}/usr/share/applications"
mkdir -p "${BUILD_ROOT}/usr/share/icons/hicolor/256x256/apps"

# 1. Cek folder hasil PyInstaller
if [ ! -d "${APP_DIR}" ]; then
    echo "Error: Direktori ${APP_DIR} tidak ditemukan! Jalankan PyInstaller terlebih dahulu."
    exit 1
fi

# Salin isi dist PyInstaller ke /usr/lib/auth-login-manager/
cp -r "${APP_DIR}/." "${BUILD_ROOT}/usr/lib/auth-login-manager/"

# 2. Buang plugin dan library GTK yang tidak dipakai Qt.
prune_gtk_stack

# 3. Periksa kompatibilitas glibc sebelum paket dibuat.
check_glibc_compat "${BUILD_ROOT}/usr/lib/auth-login-manager"

# 4. Buat launcher wrapper di /usr/bin/auth-login-manager
cat << 'EOF' > "${BUILD_ROOT}/usr/bin/auth-login-manager"
#!/bin/sh
exec /usr/lib/auth-login-manager/auth-login-manager "$@"
EOF
chmod +x "${BUILD_ROOT}/usr/bin/auth-login-manager"

# 5. Salin Desktop Entry file
cp "${SCRIPT_DIR}/auth-login-manager.desktop" "${BUILD_ROOT}/usr/share/applications/"
chmod 644 "${BUILD_ROOT}/usr/share/applications/auth-login-manager.desktop"

# 6. Salin Icon
cp "${ROOT_DIR}/assets/images/app_icon.png" \
    "${BUILD_ROOT}/usr/share/icons/hicolor/256x256/apps/auth-login-manager.png"
chmod 644 "${BUILD_ROOT}/usr/share/icons/hicolor/256x256/apps/auth-login-manager.png"

# 7. Salin maintainer scripts (refresh menu & icon cache)
for script in postinst postrm; do
    if [ -f "${SCRIPT_DIR}/${script}" ]; then
        install -m 0755 "${SCRIPT_DIR}/${script}" "${BUILD_ROOT}/DEBIAN/${script}"
    fi
done

# 8. Generate DEBIAN/control file
cat <<EOF > "${BUILD_ROOT}/DEBIAN/control"
Package: auth-login-manager
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Maintainer: Lemon Manis <lemon@example.com>
Depends: libc6 (>= 2.39), libgl1, libegl1, libxkbcommon-x11-0,
 libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1,
 libxcb-randr0, libxcb-render-util0, libxcb-shape0,
 libxcb-xinerama0, libxcb-xkb1, libfontconfig1, libdbus-1-3
Description: JSON Account Manager
 Aplikasi manajemen akun dan autentikasi JSON berbasis PyQt6 dengan dukungan sinkronisasi SQLite dan Turso.
EOF

# 9. Build .deb dengan dpkg-deb
mkdir -p "${ROOT_DIR}/dist"
dpkg-deb --build --root-owner-group "${BUILD_ROOT}" "${ROOT_DIR}/dist/${PACKAGE_NAME}.deb"

echo "==> Sukses membuat paket: ${ROOT_DIR}/dist/${PACKAGE_NAME}.deb"
