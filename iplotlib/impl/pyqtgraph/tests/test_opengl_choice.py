import unittest
from unittest import mock

import pyqtgraph as pg

from iplotlib.impl.pyqtgraph import pyQtGraphCanvas as canvas


class OpenGLChoiceTest(unittest.TestCase):
    """IPLOT_PYQTGRAPH_OPENGL asks for OpenGL; it is used only where a graphics card draws it."""

    def setUp(self):
        self.saved = (canvas.use_open_gl, canvas._opengl_in_use, pg.getConfigOption('useOpenGL'))
        canvas._opengl_in_use = None

    def tearDown(self):
        canvas.use_open_gl, canvas._opengl_in_use, used = self.saved
        pg.setConfigOptions(useOpenGL=used)

    def choose(self, asked, renderer):
        canvas.use_open_gl = asked
        with mock.patch.object(canvas, 'opengl_renderer', return_value=renderer) as probe:
            chosen = canvas.opengl_in_use()
            again = canvas.opengl_in_use()
        self.assertEqual(chosen, again)
        self.assertEqual(pg.getConfigOption('useOpenGL'), chosen)
        return chosen, probe.call_count

    def test_graphics_card(self):
        self.assertEqual(self.choose(True, 'NVIDIA Tesla T4/PCIe/SSE2'), (True, 1))
        canvas._opengl_in_use = None
        self.assertEqual(self.choose(True, 'Intel(R) Graphics'), (True, 1))

    def test_drawn_by_the_processor(self):
        for renderer in ('llvmpipe (LLVM 20.1.8, 256 bits)', 'softpipe', 'Software Rasterizer',
                         'GDI Generic', 'Microsoft Basic Render Driver'):
            canvas._opengl_in_use = None
            self.assertEqual(self.choose(True, renderer), (False, 1), renderer)

    def test_no_opengl(self):
        self.assertEqual(self.choose(True, ''), (False, 1))

    def test_not_asked_for_does_not_look(self):
        self.assertEqual(self.choose(False, 'NVIDIA Tesla T4/PCIe/SSE2'), (False, 0))


if __name__ == '__main__':
    unittest.main()
