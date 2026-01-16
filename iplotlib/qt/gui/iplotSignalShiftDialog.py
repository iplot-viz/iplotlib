"""
Dialog for displaying distance measurements and applying signal shifts.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QDoubleSpinBox, QPushButton, QGroupBox, QFormLayout, QCheckBox
)


class SignalShiftDialog(QDialog):
    """
    Dialog that shows dx, dy, dz values and allows selecting a signal to shift.
    """

    # Signal emitted when Apply is clicked: (signal_uid, signal_name, data_source, pulse_nb, dx, dy, duplicate)
    shiftRequested = Signal(str, str, str, str, float, float, bool)

    def __init__(self, parent=None, dx=0.0, dy=0.0, dz=0.0, signals=None, dx_is_datetime=False):
        super().__init__(parent)
        self.setWindowTitle("Distance & Signal Shift")
        self.setMinimumWidth(350)

        self._dx_raw = dx
        self._dy_raw = dy
        self._dz_raw = dz
        self._dx_is_datetime = dx_is_datetime
        self._signals = signals or []
        self._signal_map = {}  # uid -> signal object

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Distance display group
        dist_group = QGroupBox("Measured Distance")
        dist_layout = QFormLayout(dist_group)

        dx_display = str(self._dx_raw)
        self._dx_label = QLabel(dx_display)
        self._dy_label = QLabel(f"{self._dy_raw:.6g}")
        self._dz_label = QLabel(f"{self._dz_raw:.6g}")

        dist_layout.addRow("dx:", self._dx_label)
        dist_layout.addRow("dy:", self._dy_label)
        dist_layout.addRow("dz:", self._dz_label)

        layout.addWidget(dist_group)

        # Signal shift group
        shift_group = QGroupBox("Apply Shift to Signal")
        shift_layout = QVBoxLayout(shift_group)

        # Signal selector
        signal_layout = QFormLayout()
        self._signal_combo = QComboBox()
        self._signal_combo.addItem("-- Select signal --", None)
        for sig in self._signals:
            display_name = getattr(sig, 'label', None) or getattr(sig, 'name', None) or str(sig.uid)[:8]
            self._signal_combo.addItem(display_name, sig.uid)
            self._signal_map[sig.uid] = sig
        signal_layout.addRow("Signal:", self._signal_combo)
        shift_layout.addLayout(signal_layout)

        # Shift values (editable)
        values_layout = QFormLayout()

        self._dx_spin = QDoubleSpinBox()
        self._dx_spin.setRange(-1e12, 1e12)
        self._dx_spin.setDecimals(6)
        self._dx_spin.setValue(float(self._dx_raw) if not self._dx_is_datetime else 0.0)
        self._dx_spin.setEnabled(not self._dx_is_datetime)

        self._dy_spin = QDoubleSpinBox()
        self._dy_spin.setRange(-1e12, 1e12)
        self._dy_spin.setDecimals(6)
        self._dy_spin.setValue(float(self._dy_raw))

        values_layout.addRow("Shift X:", self._dx_spin)
        values_layout.addRow("Shift Y:", self._dy_spin)

        if self._dx_is_datetime:
            note = QLabel("Note: X shift disabled for datetime axis")
            note.setStyleSheet("color: gray; font-style: italic;")
            values_layout.addRow(note)

        shift_layout.addLayout(values_layout)
        layout.addWidget(shift_group)

        # Duplicate signal checkbox (unchecked by default)
        self._duplicate_checkbox = QCheckBox("Duplicate signal (keep original visible)")
        self._duplicate_checkbox.setChecked(False)
        layout.addWidget(self._duplicate_checkbox)

        # Buttons
        btn_layout = QHBoxLayout()

        self._apply_btn = QPushButton("Apply Shift")
        self._apply_btn.clicked.connect(self._on_apply)
        self._apply_btn.setEnabled(False)

        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.accept)

        btn_layout.addStretch()
        btn_layout.addWidget(self._apply_btn)
        btn_layout.addWidget(self._close_btn)

        layout.addLayout(btn_layout)

        # Connect signal selector
        self._signal_combo.currentIndexChanged.connect(self._on_signal_selected)

    def _on_signal_selected(self, index):
        """Enable apply button only when a signal is selected."""
        self._apply_btn.setEnabled(index > 0)

    def set_dx_text(self, text: str):
        """Set the dx label text (used for datetime display)."""
        self._dx_label.setText(text)

    def _on_apply(self):
        """Emit shift request signal."""
        signal_uid = self._signal_combo.currentData()
        if signal_uid:
            sig = self._signal_map.get(signal_uid)
            signal_name = getattr(sig, 'name', '') if sig else ''
            data_source = getattr(sig, 'data_source', '') if sig else ''
            pulse_nb = getattr(sig, 'pulse_nb', '') if sig else ''
            # pulse_nb can be a list, convert to string for matching
            if isinstance(pulse_nb, list):
                pulse_nb = pulse_nb[0] if pulse_nb else ''
            pulse_nb = str(pulse_nb) if pulse_nb else ''
            dx = self._dx_spin.value()
            dy = self._dy_spin.value()
            duplicate = self._duplicate_checkbox.isChecked()
            self.shiftRequested.emit(signal_uid, signal_name, data_source, pulse_nb, dx, dy, duplicate)
            self.accept()

