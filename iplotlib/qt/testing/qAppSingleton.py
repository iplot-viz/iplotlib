"""Shared QApplication singleton for the iplotlib test suite.

Qt only allows one QApplication per process. When multiple test modules
run in the same pytest session, each must reuse the existing instance
instead of creating a new one.
"""

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from matplotlib import font_manager


def _register_bundled_font(app: QApplication) -> None:
    """Register matplotlib's bundled DejaVu Sans so text renders on the
    offscreen platform, which otherwise has no access to system fonts
    (notably on Windows offscreen, where Qt falls back to an empty
    QBasicFontDatabase and glyphs render as empty boxes)."""
    try:
        ttf_path = font_manager.findfont("DejaVu Sans", fallback_to_default=True)
        if QFontDatabase.addApplicationFont(ttf_path) != -1:
            app.setFont(QFont("DejaVu Sans", 10))
    except Exception:
        pass


def ensure_qapp() -> QApplication:
    """Return the running QApplication or create an offscreen one."""
    existing = QApplication.instance()
    if existing is not None:
        return existing
    app = QApplication(['iplotlib_tests', '-platform', 'offscreen'])
    _register_bundled_font(app)
    return app
