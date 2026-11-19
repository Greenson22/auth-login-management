import os

from PyQt6.QtWidgets import QApplication

from src.ui.components.account_table import AccountTableWidget
from src.ui.components.config_bar import ConfigBarWidget


def test_widgets_run_on_offscreen_platform(qtbot):
  assert os.environ["QT_QPA_PLATFORM"] == "offscreen"
  assert QApplication.platformName() == "offscreen"


def test_config_bar_can_be_instantiated_offscreen(qtbot):
  widget = ConfigBarWidget()
  qtbot.addWidget(widget)
  widget.show()

  assert widget.isVisible()
  assert widget.lbl_db_status.text()
  assert widget.lbl_crypto_status.text()


def test_account_table_can_be_instantiated_offscreen(qtbot):
  widget = AccountTableWidget()
  qtbot.addWidget(widget)
  widget.show()

  assert widget.isVisible()
  assert widget.table.columnCount() > 0
