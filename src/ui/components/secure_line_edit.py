from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QLineEdit


class SecureLineEdit(QLineEdit):
  """QLineEdit yang memblokir copy, cut, dan paste lewat keyboard maupun context menu.

  Digunakan untuk field sensitif seperti URL database, auth token, dan password enkripsi
  agar nilainya tidak bisa disalin ke clipboard melalui cara apapun dari UI.
  """

  def __init__(self, parent=None):
    super().__init__(parent)
    # Matikan context menu klik-kanan sepenuhnya
    self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

  def keyPressEvent(self, event):
    # Blokir Ctrl+C (Copy), Ctrl+X (Cut), Ctrl+A (Select All)
    if event.matches(QKeySequence.StandardKey.Copy):
      event.ignore()
      return
    if event.matches(QKeySequence.StandardKey.Cut):
      event.ignore()
      return
    if event.matches(QKeySequence.StandardKey.SelectAll):
      event.ignore()
      return
    super().keyPressEvent(event)
