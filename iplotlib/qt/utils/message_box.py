"""
Show a message box with text and block the event loop.
"""

# Author: Jaswant Sai Panchumarti

from PySide2.QtWidgets import QMessageBox


def show_msg(msg: str, title: str = "", parent=None):
    msg_box = QMessageBox(parent)
    msg_box.setWindowTitle(title)
    msg_box.setText(msg)
    msg_box.exec_()
