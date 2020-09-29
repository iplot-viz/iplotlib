from PyQt5.QtWidgets import QHBoxLayout, QRadioButton, QGroupBox


class QtPlotCanvasToolbar(QGroupBox):

    tools = {"crosshair" : "Crosshair", "zoom" : "Zoom", "pan" : "Pan"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        layout = QHBoxLayout()
        self.setLayout(layout)
        for key,label in self.tools:
            radio = QRadioButton(label)
            # radio.tool_class = t?
            radio.toggled.connect(self.selected)
            layout.addWidget(radio)

    def selected(self):
        rb: QRadioButton = self.sender()
        if rb.isChecked():
            print("Checked: " + str(rb))