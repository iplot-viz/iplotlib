from PyQt5.QtWidgets import QHBoxLayout, QRadioButton, QGroupBox


class QtPlotCanvasToolbar(QGroupBox):

    def setData(self, tools, canvases):
        self.canvases = canvases

        layout = QHBoxLayout()
        self.setLayout(layout)
        for t in tools:
            radio = QRadioButton(str(t.__name__))
            radio.tool_class = t
            radio.toggled.connect(self.selected)
            layout.addWidget(radio)

    def selected(self):
        rb: QRadioButton = self.sender()
        if rb.isChecked():
            for c in self.canvases:
                if c.overlay is not None:
                    c.overlay.activateTool(rb.tool_class())
