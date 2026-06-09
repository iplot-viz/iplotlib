import datetime

from matplotlib.ticker import ScalarFormatter
from matplotlib.axis import XAxis
import pandas

import iplotLogging.setupLogger as Sl

logger = Sl.get_logger(__name__)


class ExponentScalarFormatter(ScalarFormatter):
    """Formatter that displays exponent (1eN) before axis label."""

    def __init__(self, label_props: dict = None):
        super().__init__(useOffset=True, useMathText=False)
        self.set_powerlimits((-3, 3))
        self._label_props = label_props or {}

    def _get_base_label(self) -> str:
        """Extract base label from axis, removing any exponent prefix."""
        if not self.axis:
            return ''
        current_label = self.axis.get_label().get_text()
        if current_label and '1e' in current_label:
            parts = current_label.split('  ', 1)
            if len(parts) > 1 and parts[0].startswith('1e'):
                return parts[1]
        return current_label or ''

    def get_offset(self):
        """Return offset string; embed exponent in label only for linear X axis."""
        # Native matplotlib offsetText already renders in a usable position for Y axis
        # (above the plot) and for log X axis. Label embedding is only needed for the
        # linear X axis case where the native offset clashes with right-edge ticks.
        use_native_offset = False
        if self.axis is not None and self.axis.axes is not None:
            if isinstance(self.axis, XAxis):
                use_native_offset = self.axis.axes.get_xscale() == 'log'
            else:
                use_native_offset = True

        base_label = self._get_base_label()

        if not use_native_offset and self.orderOfMagnitude and self.orderOfMagnitude != 0:
            exp_str = f'1e{self.orderOfMagnitude}'
            if self.axis:
                new_label = f'{exp_str}  {base_label}'.strip()
                current_label = self.axis.get_label().get_text()
                if current_label != new_label:
                    self.axis.set_label_text(new_label, **self._label_props)
            return ''

        if self.axis and base_label:
            current_label = self.axis.get_label().get_text()
            if current_label != base_label and '1e' in current_label:
                self.axis.set_label_text(base_label, **self._label_props)
        return super().get_offset()


class NanosecondDateFormatter(ScalarFormatter):
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

    def __init__(self, ax_idx: int, label_segments=4, postfix_end=True, postfix_start=False, offset_lut: list = None,
                 roundh=False):
        super().__init__()
        self.postfix_end = postfix_end
        self.postfix_start = postfix_start
        self.label_segments = label_segments
        self.offset_str = "N/A"
        self.cut_start = 0
        self._offset_lut = offset_lut
        self._ax_idx = ax_idx
        self._round = roundh

    @property
    def offset_ns(self):
        if not self._offset_lut:
            return 0
        if len(self._offset_lut) > self._ax_idx and self._offset_lut[self._ax_idx] is not None:
            return self._offset_lut[self._ax_idx]
        return 0

    def set_locs(self, locs) -> None:
        if locs is None or len(locs) == 0:
            return

        if self.offset_ns == 100_000:
            self.cut_start = self.lcp(self.offset_ns * int(locs[0]), self.offset_ns * int(locs[-1]))
            self.offset_str = 'UTC:' + self.date_fmt(self.offset_ns * locs[0], self.YEAR, self.cut_start,
                                                     postfix_end=self.postfix_end, postfix_start=self.postfix_start)
        else:
            self.cut_start = self.lcp(self.offset_ns + int(locs[0]), self.offset_ns + int(locs[-1]))
            self.offset_str = 'UTC:' + self.date_fmt(self.offset_ns + locs[0], self.YEAR, self.cut_start,
                                                 postfix_end=self.postfix_end, postfix_start=self.postfix_start)

        super().set_locs(locs)

    def __call__(self, x, pos=None):
        if self.offset_ns == 100_000:
            return self.date_fmt(int(self.offset_ns) * int(x), self.cut_start + 1, self.cut_start + self.label_segments)
        else:
            return self.date_fmt(int(self.offset_ns) + int(x), self.cut_start + 1, self.cut_start + self.label_segments)

    def format_data_short(self, value):
        if self.offset_ns == 100_000:
            return self.date_fmt(int(self.offset_ns) * int(value), self.cut_start + 1, self.cut_start + self.label_segments)
        else:
            return self.date_fmt(int(self.offset_ns) + int(value), self.cut_start + 1, self.cut_start + self.label_segments)

    def format_data(self, value):
        return super().format_data(value)

    def get_offset(self):
        return self.offset_str

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
            hour = datetime.datetime.strptime(hour_str, '%H:%M')
        else:
            hour = datetime.datetime.strptime(hour_str, '%H:%M:%S')

        if hour.minute >= 30:
            hour += datetime.timedelta(hours=1)

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
