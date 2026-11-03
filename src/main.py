import sys
from pathlib import Path

# Tambahkan root folder (satu tingkat di atas folder src) ke sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from PyQt6.QtWidgets import QApplication
from src.ui import MainWindow

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()