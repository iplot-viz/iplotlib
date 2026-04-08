import pyqtgraph as pg
import pyqtgraph.functions as fn
from datetime import datetime, timedelta
import pandas
from math import ceil, floor, log10
import numpy as np

import iplotLogging.setupLogger as Sl

logger = Sl.get_logger(__name__)


class NanosecondDateFormatter(pg.AxisItem):
    """Date axis formatter that takes into account ns offset if it is defined on this formatter axis
    Additionally it formats date as common_part + postfix and includes nanosecond precision if data is given as int64"""

    """Date segment names constants"""
    YEAR, MONTH, DAY, HOUR, MINUTE, SECOND, MILISECOND, MICROSECOND, NANOSECOND = range(0, 9)

    """pandas attr names for each segment (without milliseconds since it is not supported"""
    attrs = ['year', 'month', 'day', 'hour', 'minute', 'second', 'millisecond', 'microsecond', 'nanosecond']

    """Postfixes after each date segment"""
    postfixes = ['-', '-', 'T', ':', ':', '.', '', '', '']

    """Formats for each date segment"""
    formats = ["{:4d}", "{:02d}", "{:02d}", "{:02d}", "{:02d}", "{:02d}", "{:03d}", "{:03d}", "{:03d}"]

    def __init__(self, postfix_end=True, postfix_start=False, roundh=False, is_date=True, *args, **kwargs):
        # Init before super() because pyqtgraph calls labelString() during __init__
        self.labelUnit = ''
        self._numeric_offset = 0.0
        super().__init__(*args, **kwargs)
        self.postfix_end = postfix_end
        self.postfix_start = postfix_start
        self.offset_str = "N/A"
        self.offset_ns = 0
        self.cut_start = 0
        self._round = roundh
        self.last_values = []
        self.n_ticks = 7
        self.last_range = 0
        self.offset = 0
        self.is_date = is_date
        self._spacing = 0.0
        if kwargs['orientation'] == 'bottom':
            self.common_label = pg.LabelItem(text='', justify='right')
        else:
            self.common_label = pg.LabelItem(text='', justify='left')

        self.enableAutoSIPrefix(False)

    def __call__(self, x, pos=None):
        if self.is_date:
            return self.date_fmt(int(x), self.cut_start + 1, self.cut_start + 4)
        else:
            return f"{x:g}"

    def get_spacing_label(self):
        """Return a human-readable label for the current tick spacing (oscilloscope style)."""
        s = abs(self._spacing)
        if s == 0:
            return ""
        if self.is_date:
            # Spacing is in nanoseconds
            if s >= 86400e9:
                return f"{s / 86400e9:.3g}D/div"
            elif s >= 3600e9:
                return f"{s / 3600e9:.3g}h/div"
            elif s >= 60e9:
                return f"{s / 60e9:.3g}min/div"
            elif s >= 1e9:
                return f"{s / 1e9:.3g}s/div"
            elif s >= 1e6:
                return f"{s / 1e6:.3g}ms/div"
            elif s >= 1e3:
                return f"{s / 1e3:.3g}μs/div"
            else:
                return f"{s:.3g}ns/div"
        else:
            # Numeric axis
            if s >= 1e9:
                return f"{s / 1e9:.3g}G/div"
            elif s >= 1e6:
                return f"{s / 1e6:.3g}M/div"
            elif s >= 1e3:
                return f"{s / 1e3:.3g}k/div"
            elif s >= 1:
                return f"{s:.3g}/div"
            elif s >= 1e-3:
                return f"{s * 1e3:.3g}m/div"
            elif s >= 1e-6:
                return f"{s * 1e6:.3g}μ/div"
            else:
                return f"{s * 1e9:.3g}n/div"

    def set_offset(self, offset):
        self.offset = offset

    def date_part(self, ts_numeric, part):
        """Extract date part from numerical timestamp"""
        ts = pandas.Timestamp(ts_numeric)

        if part == self.MILISECOND:
            return int(ts.microsecond / 1000)
        elif part == self.MICROSECOND:
            return ts.microsecond % 1000
        else:
            return getattr(ts, self.attrs[part])

    def date_fmt(self, date, start=YEAR, end=NANOSECOND, postfix_end=False, postfix_start=False):
        """Formats date and returns only part between start segment and end segment"""
        ret = ""
        if end is None:
            end = self.NANOSECOND
        for i in range(start, end + 1):
            if i > 0 and i == start and postfix_start:
                ret += self.postfixes[i - 1]

            if i < len(self.formats):
                ret += self.formats[i].format(self.date_part(date, i))

            if (i < end or postfix_end) and i < len(self.postfixes):
                ret += self.postfixes[i]

        if self._round and 'T' in ret:
            # Implemented rounding only at the hour level, so the separator must be in that exact position
            if ret[2] == 'T' or ret[5] == 'T':
                return self.round_hour(ret)
        return ret

    @staticmethod
    def round_hour(ret):
        parts = ret.split('T')
        hour_str = parts[1]

        if len(hour_str) == 5:
            hour = datetime.strptime(hour_str, '%H:%M')
        else:
            hour = datetime.strptime(hour_str, '%H:%M:%S')

        if hour.minute >= 30:
            hour += timedelta(hours=1)

        if len(hour_str) == 5:
            hour = hour.replace(minute=0)
            round_hour_str = hour.strftime('%H:%M')
        else:
            hour = hour.replace(minute=0, second=0)
            round_hour_str = hour.strftime('%H:%M:%S')

        new_ret = f"{parts[0]}T{round_hour_str}"

        return new_ret

    def lcp(self, start, end):
        """Returns last common segment of two dates given as start and end"""
        for i in range(self.YEAR, self.NANOSECOND + 1):
            val_s, val_e = self.date_part(start, i), self.date_part(end, i)

            if val_s != val_e:
                return i - 1

        return 0

    def set_ticks_number(self, tick_number: int):
        self.n_ticks = tick_number

    def tickValues(self, minVal, maxVal, size):
        # Limit tick count to what fits without overlapping labels
        n = self.n_ticks
        if size > 0:
            font = self.style.get('tickFont') or self.font()
            fm = pg.Qt.QtGui.QFontMetricsF(font)
            sample = "00:00:00.000" if self.is_date else "0.00000"
            label_w = fm.horizontalAdvance(sample) + 10
            n = max(2, min(n, int(size / label_w)))

        # Detect range change
        last_range = maxVal - minVal

        # Recalculate if range changed or tick count changed (e.g. window resize)
        if len(self.last_values) == 0 or last_range != self.last_range or len(self.last_values) != n:
            # First time we generate evenly spaced values
            if self.is_date:
                spacing = last_range / n
                values = [minVal + spacing / 2 + i * spacing for i in range(n)]
            else:
                spacing, offset = super().tickSpacing(minVal, maxVal, size)[0]  # Major ticks level
                start = (ceil((minVal - offset) / spacing) * spacing) + offset
                values = (np.arange(n) * spacing + start).tolist()
            self.last_range = last_range
        else:
            # Adjust previous ticks to new range
            values = [v for v in self.last_values if minVal <= v <= maxVal]

            # Add new ticks if needed
            while len(values) < n:
                # Add to the end or to the beginning
                if values and values[-1] + (values[1] - values[0]) <= maxVal:
                    values.append(values[-1] + (values[1] - values[0]))
                elif values and values[0] - (values[1] - values[0]) >= minVal:
                    values.insert(0, values[0] - (values[1] - values[0]))
                else:
                    break
            values = sorted(values)

        # Thin out if too many ticks for available space
        while len(values) > n and len(values) > 2:
            values = values[::2]

        # Save current state and spacing
        self.last_values = values
        if len(values) >= 2:
            self._spacing = values[1] - values[0]
        elif last_range > 0:
            self._spacing = last_range / max(n, 1)

        if self.is_date:
            self.cut_start = self.lcp(self.get_real_value(int(values[0])), self.get_real_value(int(values[-1])))

            self.offset_str = 'UTC:' + self.date_fmt(self.get_real_value(values[0]), self.YEAR, self.cut_start,
                                                     postfix_end=self.postfix_end, postfix_start=self.postfix_start)

            spacing = abs(values[1] - values[0]) if len(values) >= 2 else (maxVal - minVal)
        else:
            spacing, offset = super().tickSpacing(minVal, maxVal, size)[0]

            if self.orientation == 'bottom':
                # X axis: custom exponent logic
                val_range = maxVal - minVal
                max_val = max(abs(minVal), abs(maxVal))

                if max_val > 0 and val_range > 0 and val_range / max_val < 1e-3:
                    oom = floor(log10(val_range))
                    self._numeric_offset = round(minVal, -oom)
                else:
                    self._numeric_offset = 0.0

                if self._numeric_offset != 0:
                    ref_val = max(abs(minVal - self._numeric_offset),
                                  abs(maxVal - self._numeric_offset))
                    if ref_val == 0:
                        ref_val = val_range
                else:
                    ref_val = max_val if max_val > 0 else abs(spacing)

                oom = floor(log10(ref_val)) if ref_val > 0 else 0
                if -2 <= oom <= 5 and self._numeric_offset == 0:
                    scale = 1.0
                else:
                    scale = 10.0 ** (-oom)
                prefix = ''

                self.set_scale(scale, prefix)
                self._tick_spacing = spacing
            else:
                # Y axis with fn.siScale
                self._numeric_offset = 0.0
                if self.logMode:
                    _range = 10 ** np.array(self.range)
                else:
                    _range = self.range
                (scale, prefix) = fn.siScale(max(abs(_range[0] * self.scale), abs(_range[1] * self.scale)))
                self.set_scale(scale, prefix)

        return [(spacing, values)]  # major ticks

    def tickStrings(self, values, scale, spacing):
        if self.is_date:
            values = list(
                map(lambda v: self.date_fmt(self.get_real_value(int(v)), self.cut_start + 1, self.cut_start + 5),
                    values))
            self.common_label.prepareGeometryChange()
            self.common_label.setText(self.offset_str)
        else:
            if self.orientation == 'bottom':
                # X axis: custom exponent formatting
                adjusted = [v - self._numeric_offset for v in values] if self._numeric_offset != 0 else values
                scale_factor = self.autoSIPrefixScale
                if scale_factor != 1.0:
                    precision = int(-log10(abs(scale_factor))) + 10
                    values = [f"{round(v * scale_factor, precision):g}" for v in adjusted]
                else:
                    values = [f"{v:g}" for v in adjusted]
                self.common_label.setText("")
                self._updateLabel()
            else:
                # Y axis: fn.siScale formatting
                if self.labelUnit in ['', 'k']:
                    values = [f"{v:g}" for v in values]
                    self.common_label.setText("")
                else:
                    values = super().tickStrings(values, scale, spacing)
                    if self.common_label.text != self.offset_str:
                        self.common_label.setText(self.offset_str)

        return values

    def set_scale(self, scale, prefix):
        exponent = int(round(-np.log10(scale)))
        self.offset_str = f"1e{exponent}"
        self.autoSIPrefixScale = scale
        self.labelUnit = prefix

    def labelString(self) -> str:
        """Generate label string with exponent prefix for bottom axis."""
        if self.labelUnits == '':
            if not self.autoSIPrefix or self.autoSIPrefixScale == 1.0:
                units = ''
            else:
                units = f'(x{1.0 / self.autoSIPrefixScale:g})'
        else:
            units = f'({self.labelUnitPrefix}{self.labelUnits})'

        has_scaling = self.autoSIPrefixScale != 1.0
        if self.orientation == 'bottom' and hasattr(self, 'offset_str') and self.offset_str and has_scaling:
            s = f'{self.offset_str}  {self.labelText}'.strip()
        else:
            s = f'{self.labelText} {units}'.strip()

        style = ';'.join([f'{k}: {self.labelStyle[k]}' for k in self.labelStyle])

        return f"<span style='{style}'>{s}</span>"

    def get_real_value(self, value):
        if self.offset == 100_000:
            return value * self.offset
        else:
            return value + self.offset
