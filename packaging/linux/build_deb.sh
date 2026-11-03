#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

VERSION="${1:-1.0.0}"
ARCH="amd64"
PACKAGE_NAME="auth-login-manager_${VERSION}_${ARCH}"
BUILD_ROOT="${ROOT_DIR}/build/deb/${PACKAGE_NAME}"

echo "==> Menyiapkan direktori build .deb di ${BUILD_ROOT}..."
rm -rf "${ROOT_DIR}/build/deb"
mkdir -p "${BUILD_ROOT}/DEBIAN"
mkdir -p "${BUILD_ROOT}/usr/bin"
mkdir -p "${BUILD_ROOT}/usr/lib/auth-login-manager"
mkdir -p "${BUILD_ROOT}/usr/share/applications"
mkdir -p "${BUILD_ROOT}/usr/share/icons/hicolor/256x256/apps"

# 1. Cek folder hasil PyInstaller
if [ ! -d "${ROOT_DIR}/dist/auth-login-manager" ]; then
    echo "Error: Direktori ${ROOT_DIR}/dist/auth-login-manager tidak ditemukan! Jalankan pyinstaller terlebih dahulu."
    exit 1
fi

# Salin isi dist PyInstaller ke /usr/lib/auth-login-manager/
cp -r "${ROOT_DIR}/dist/auth-login-manager/"* "${BUILD_ROOT}/usr/lib/auth-login-manager/"

# 2. Buat launcher wrapper di /usr/bin/auth-login-manager
cat << 'EOF' > "${BUILD_ROOT}/usr/bin/auth-login-manager"
#!/bin/sh
exec /usr/lib/auth-login-manager/auth-login-manager "$@"
EOF
chmod +x "${BUILD_ROOT}/usr/bin/auth-login-manager"

# 3. Salin Desktop Entry file
cp "${SCRIPT_DIR}/auth-login-manager.desktop" "${BUILD_ROOT}/usr/share/applications/"
chmod 644 "${BUILD_ROOT}/usr/share/applications/auth-login-manager.desktop"

# 4. Salin Icon
cp "${ROOT_DIR}/assets/images/app_icon.png" "${BUILD_ROOT}/usr/share/icons/hicolor/256x256/apps/auth-login-manager.png"
chmod 644 "${BUILD_ROOT}/usr/share/icons/hicolor/256x256/apps/auth-login-manager.png"

# 5. Generate DEBIAN/control file
cat <<EOF > "${BUILD_ROOT}/DEBIAN/control"
Package: auth-login-manager
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Maintainer: Lemon Manis <lemon@example.com>
Description: JSON Account Manager
 Aplikasi manajemen akun dan autentikasi JSON berbasis PyQt6 dengan dukungan sinkronisasi SQLite dan Turso.
EOF

# 6. Build .deb dengan dpkg-deb
mkdir -p "${ROOT_DIR}/dist"
dpkg-deb --build --root-owner-group "${BUILD_ROOT}" "${ROOT_DIR}/dist/${PACKAGE_NAME}.deb"

echo "==> Sukses membuat paket: ${ROOT_DIR}/dist/${PACKAGE_NAME}.deb"
