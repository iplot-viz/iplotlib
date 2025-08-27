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
        pos = evt[0]
        if self.plot.sceneBoundingRect().contains(pos):
            mouse_point = self.plot.vb.mapSceneToView(pos)
            x, y = mouse_point.x(), mouse_point.y()
            self.vLine.setPos(x)
            self.hLine.setPos(y)
            """
            index = int(mousePoint.x())
            if index > 0 and index < len(data1):
                label.setText(
                    "<span style='font-size: 12pt'>x=%0.1f,   <span style='color: red'>y1=%0.1f</span>,   <span style='color: green'>y2=%0.1f</span>" % (
                        mousePoint.x(), data1[index], data2[index]))
            vLine.setPos(mousePoint.x())
            hLine.setPos(mousePoint.y())
            """
