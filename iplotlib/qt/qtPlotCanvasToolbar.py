from qtpy.QtWidgets import QHBoxLayout, QRadioButton, QGroupBox


# class QtPlotCanvasToolbar(QGroupBox):
#
#     tools = {"crosshair": "Crosshair", "zoom": "Zoom", "pan": "Pan"}
#
#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         self.canvases = []
#
#         layout = QHBoxLayout()
#         self.setLayout(layout)
#         for key, label in self.tools.items():
#             radio = QRadioButton(label)
#             radio.tool_label = key
#             radio.toggled.connect(self.selected)
#             layout.addWidget(radio)
#
#     def selected(self):
#         rb: QRadioButton = self.sender()
#         if rb.isChecked():
#             for canvas in self.canvases:
#                 canvas.enableTool(rb.tool_label)