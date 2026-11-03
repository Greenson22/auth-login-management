from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)


class WorkerThread(QThread):
  """Thread latar belakang untuk menjalankan fungsi berat / I/O tanpa membekukan antarmuka."""

  success = pyqtSignal(object)
  failed = pyqtSignal(Exception)

  def __init__(self, task_func, *args, **kwargs):
    super().__init__()
    self.task_func = task_func
    self.args = args
    self.kwargs = kwargs

  def run(self):
    try:
      result = self.task_func(*self.args, **self.kwargs)
      self.success.emit(result)
    except Exception as e:
      self.failed.emit(e)


class LoadingDialog(QDialog):
  """Dialog loading modal dengan progress bar animasi (indeterminate) dan teks status informatif."""

  def __init__(self, parent=None, title="Memproses...", message="Mohon tunggu sebentar..."):
    super().__init__(parent)
    self.setWindowTitle(title)
    self.setWindowModality(Qt.WindowModality.ApplicationModal)
    self.setWindowFlags(
        Qt.WindowType.Dialog
        | Qt.WindowType.CustomizeWindowHint
        | Qt.WindowType.WindowTitleHint
    )
    self.setFixedSize(360, 120)

    layout = QVBoxLayout(self)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)

    self.lbl_message = QLabel(message)
    self.lbl_message.setStyleSheet("font-size: 13px; font-weight: bold; color: #1a73e8;")
    self.lbl_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.lbl_message.setWordWrap(True)

    self.progress_bar = QProgressBar()
    self.progress_bar.setRange(0, 0)  # Animasi bergerak bolak-balik (indeterminate)
    self.progress_bar.setTextVisible(False)
    self.progress_bar.setStyleSheet(
        """
        QProgressBar {
            border: 1px solid #c0c0c0;
            border-radius: 4px;
            height: 8px;
            background-color: #f1f3f4;
        }
        QProgressBar::chunk {
            background-color: #1a73e8;
            border-radius: 4px;
        }
        """
    )

    layout.addWidget(self.lbl_message)
    layout.addWidget(self.progress_bar)

  def set_message(self, message: str):
    self.lbl_message.setText(message)
