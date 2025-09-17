import pyqtgraph as pg

from pyqtgraph import PlotItem, AxisItem, PlotDataItem


class pyQtCrosshair:

    def __init__(self, plot: PlotItem):
        self.plot = plot
        self.vLine = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(color='r', width=1))
        self.hLine = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(color='r', width=1))

        self.plot.addItem(self.vLine, ignoreBounds=True)
        self.plot.addItem(self.hLine, ignoreBounds=True)

        """Connect events"""
        self.proxy = pg.SignalProxy(
            self.plot.scene().sigMouseMoved,
            rateLimit=60,
            slot=self.mouse_moved
        )

        # self._cid_motion = self.canvas.mpl_connect('motion_notify_event', self.mouseMoved)
        # self._cid_draw = self.canvas.mpl_connect('draw_event', self.clear)

    def mouse_moved(self, evt):
        pass
