"""In a dark application palette the canvases draw in its colours what they draw in black and white in a light one,
in both backends, and they draw as before once the palette is light again. Colours set by the user stay."""

import unittest
from types import SimpleNamespace

import numpy as np
from matplotlib.colors import to_hex
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from iplotlib.core import property_manager
from iplotlib.core.axis import LinearAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.impl.matplotlib.matplotlibCanvas import apply_theme_rc
from iplotlib.interface.iplotSignalAdapter import AccessHelper, ParserHelper
from iplotlib.qt.gui.iplotCanvasToolbar import IplotQtCanvasToolbar
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp
from iplotlib.qt.utils.icon_loader import svg_icon_image

T0 = 1_788_873_880_000_000_000
BASE, TEXT = '#2d2d2d', '#ffffff'


class _DataAccess:
    def get_data(self, data_s_name, **kwargs):
        x = np.linspace(kwargs['tsS'], kwargs['tsE'], 200).astype(np.int64)
        return SimpleNamespace(errcode=0, errdesc='', xdata=x, ydata=np.sin(np.linspace(0, 6, 200)), xunit='ns',
                               yunit='A', resolved_pulse=None)

    def get_data_source(self, name):
        return None


def _dark_palette() -> QPalette:
    palette = QPalette()
    for role, colour in (('Window', '#1e1e1e'), ('WindowText', TEXT), ('Base', BASE), ('Text', TEXT),
                         ('Button', '#3c3c3c'), ('ButtonText', TEXT)):
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(colour))
    return palette


class DarkPaletteTest(unittest.TestCase):
    def setUp(self):
        self.app = ensure_qapp()
        ParserHelper.env.clear()
        self.addCleanup(ParserHelper.env.clear)
        self.addCleanup(setattr, AccessHelper, 'da', AccessHelper.da)
        AccessHelper.da = _DataAccess()
        self.addCleanup(self._light)

    def _light(self):
        self.app.setPalette(QPalette())
        self._settle()
        apply_theme_rc(None)
        property_manager.set_theme_colors({})

    def _settle(self):
        for _ in range(5):
            self.app.processEvents()

    def _drawn(self, backend, **plot):
        canvas = Canvas(1, 1, title='theme')
        ipl_plot = PlotXY(axes=[LinearAxis(is_date=True), [LinearAxis()]], **plot)
        ipl_plot.add_signal(SignalXY(name='VAR', label='VAR', data_source='uda', ts_start=T0, ts_end=T0 + 10 ** 12))
        canvas.add_plot(ipl_plot, 0)
        qt_canvas = IplotQtCanvasFactory.new(backend)
        self.addCleanup(qt_canvas.deleteLater)
        qt_canvas.resize(800, 500)
        qt_canvas.set_canvas(canvas)
        self._settle()
        return qt_canvas, qt_canvas._parser, ipl_plot

    @staticmethod
    def _colours(backend, parser, ipl_plot):
        """The background of the figure and of the plot, and the colour of the tick labels."""
        impl_plot = parser._plot_impl_plot_lut.get(id(ipl_plot))[0]
        if backend == 'matplotlib':
            ticks = impl_plot.yaxis.get_ticklabels()[0].get_color()
            return (to_hex(parser.figure.get_facecolor()), to_hex(impl_plot.get_facecolor()), to_hex(ticks))
        return (parser.figure.backgroundBrush().color().name(),
                impl_plot.getViewBox().background.brush().color().name(),
                impl_plot.getAxis('left').textPen().color().name())

    def test_a_canvas_draws_in_the_colours_of_a_dark_palette_and_as_before_in_a_light_one(self):
        for backend in ('matplotlib', 'pyqt'):
            with self.subTest(backend=backend):
                qt_canvas, parser, ipl_plot = self._drawn(backend)
                light = self._colours(backend, parser, ipl_plot)
                self.assertEqual(light, ('#ffffff', '#ffffff', '#000000'))

                self.app.setPalette(_dark_palette())
                self._settle()
                self.assertEqual(self._colours(backend, parser, ipl_plot), (BASE, BASE, TEXT))

                self.app.setPalette(QPalette())
                self._settle()
                self.assertEqual(self._colours(backend, parser, ipl_plot), light)

    def test_a_colour_set_by_the_user_stays(self):
        for backend in ('matplotlib', 'pyqt'):
            with self.subTest(backend=backend):
                qt_canvas, parser, ipl_plot = self._drawn(backend, background_color='#ffffe0')
                self.app.setPalette(_dark_palette())
                self._settle()
                self.assertEqual(self._colours(backend, parser, ipl_plot)[1], '#ffffe0')

    def test_the_icons_take_the_grey_of_the_palette(self):
        toolbar = IplotQtCanvasToolbar()
        self.addCleanup(toolbar.deleteLater)
        home = toolbar.homeAction.icon().cacheKey()
        changes = []
        toolbar.homeAction.changed.connect(lambda *_: changes.append(1))
        grey = svg_icon_image('home', 32).pixelColor(16, 16).name()
        # Another light palette: the tool bar keeps its icons.
        light = QPalette(self.app.palette())
        light.setColor(QPalette.ColorRole.Highlight, QColor('#ff8800'))
        self.app.setPalette(light)
        self._settle()
        self.assertEqual(changes, [])
        self.app.setPalette(_dark_palette())
        self._settle()
        dark = svg_icon_image('home', 32).pixelColor(16, 16)
        self.assertEqual(grey, '#3b3b3b')
        self.assertGreater(dark.lightness(), 150)
        self.assertNotEqual(toolbar.homeAction.icon().cacheKey(), home)


if __name__ == "__main__":
    unittest.main()
