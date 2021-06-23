from matplotlib.ticker import ScalarFormatter
import pandas

import logging2.setupLogger as ls

logger = ls.get_logger(__name__)

class NanosecondDateFormatter(ScalarFormatter):
    """Date axis formatter that takes into account ns offset if it is defined on this formatter axis
    Additionaly it formats date as common_part + postfix and includes nanosecond precision if data is given as int64"""

    """Date segment names constants"""
    YEAR, MONTH, DAY, HOUR, MINUTE, SECOND, MILISECOND, MICROSECOND, NANOSECOND = range(0, 9)

    """pandas attr names for each segment (without milliseconds since it is not supported"""
    attrs = ['year', 'month', 'day', 'hour', 'minute', 'second', 'millisecond', 'microsecond', 'nanosecond']

    """Postfixes after each date segment"""
    postfixes = ['-', '-', 'T', ':', ':', '.', '', '', '']

    """Formats for each date segment"""
    formats = ["{:4d}", "{:02d}", "{:02d}", "{:02d}", "{:02d}", "{:02d}", "{:03d}", "{:03d}", "{:03d}"]

    def __init__(self, label_segments=4, postfix_end=True, postfix_start=False):
        super().__init__()
        self.postfix_end = postfix_end
        self.posfix_start = postfix_start
        self.label_segments = label_segments
        self.offset_str = "N/A"
        self.cut_start = -1

    @property
    def offsetns(self):
        if hasattr(self.axis, '_offset'):
            return self.axis._offset
        return 0

    def set_locs(self, locs):
        if locs is not None and len(locs) > 0:
            if (self.offsetns):
                self.cut_start = self.lcp(self.offsetns + int(locs[0]), self.offsetns + int(locs[-1]))
            else:
                self.cut_start = self.lcp(self.offsetns + locs[0], self.offsetns + locs[-1])

            if self.cut_start is None:
                self.cut_start = 0
            self.offset_str = 'UTC:' + self.date_fmt(self.offsetns + locs[0], self.YEAR, self.cut_start,
                                            postfix_end=self.postfix_end, postfix_start=self.posfix_start)

        super().set_locs(locs)

    def __call__(self, x, pos=None):
        return self.date_fmt(int(self.offsetns) + int(x), self.cut_start + 1, self.cut_start + self.label_segments)

    def format_data_short(self, value):
        return self.date_fmt(int(self.offsetns) + int(value), self.cut_start + 1, self.cut_start + self.label_segments)

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

        return ret

    def lcp(self, start, end):
        """Returns last common segment of two dates given as start and end"""
        for i in range(self.YEAR, self.NANOSECOND + 1):
            val_s, val_e = self.date_part(start, i), self.date_part(end, i)

            if val_s != val_e:
                return i - 1

        return None
