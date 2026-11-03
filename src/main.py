import sys
from pathlib import Path

# Tambahkan root folder (satu tingkat di atas folder src) ke sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication
from src.ui import MainWindow

def main():
    app = QApplication(sys.argv)
    icon_path = BASE_DIR / "assets" / "images" / "app_icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()