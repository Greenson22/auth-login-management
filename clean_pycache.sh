#!/usr/bin/env bash

# Skrip untuk membersihkan semua folder __pycache__ dan file .pyc/.pyo di project
# Mengecualikan folder virtual environment (.env / .venv) agar aman

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Membersihkan __pycache__ di $PROJECT_DIR..."

find "$PROJECT_DIR" \( -name ".env*" -o -name ".venv*" \) -prune -o -type d -name "__pycache__" -exec rm -rf {} +
find "$PROJECT_DIR" \( -name ".env*" -o -name ".venv*" \) -prune -o -type f \( -name "*.pyc" -o -name "*.pyo" \) -exec rm -f {} +

echo "Selesai! Semua __pycache__ berhasil dihapus."
