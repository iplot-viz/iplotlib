import pyqtgraph as pg
import pyqtgraph.functions as fn
from datetime import datetime, timedelta, timezone
import pandas
from math import ceil, floor, log10
import numpy as np

import iplotLogging.setupLogger as Sl
import re as _re

logger = Sl.get_logger(__name__)

# ---------------------------------------------------------------------------
# Engineering time-unit decomposition for the relative (non-date) seconds axis.
# Factors the constant high part into a "common" string (e.g. "7ms690us") and
# labels each tick with the finest changing group (e.g. 452 / 467) plus its unit
# (axis reads "[ns]"). Mirrors the matplotlib backend so both look the same.
# ---------------------------------------------------------------------------
_DUR_UNITS = [('d', 86_400_000_000_000), ('h', 3_600_000_000_000),
              ('min', 60_000_000_000), ('s', 1_000_000_000),
              ('ms', 1_000_000), ('us', 1_000), ('ns', 1)]
_DUR_UNAME = {scale: name for name, scale in _DUR_UNITS}


def _fmt_duration(ns: int, min_scale: int) -> str:
    """Concatenated duration groups from the largest non-zero unit down to
    ``min_scale``, sign-prefixed. ``m`` is minutes, ``ms`` milliseconds.
    36250000 ns @ us -> '36ms250us'; 452 ns @ ns -> '452ns'; 0 -> '0<unit>'."""
    r = abs(int(ns))
    sign = '-' if ns < 0 else ''
    parts = []
    for name, scale in _DUR_UNITS:
        if scale < min_scale:
            break
        q = r // scale
        r -= q * scale
        if q:
            parts.append(f"{q}{name}")
    if not parts:
        return f"0{_DUR_UNAME.get(min_scale, 'ns')}"
    return sign + ''.join(parts)


def eng_time_axis_labels(lo_s, hi_s, ticks_s):
    """Decompose a relative-time view into (common_label, {ns_key: label},
    base_ns, unit_scale). Granularity follows the tick spacing (up to days);
    the common part is the deepest group the *view* shares, factored out so
    only the changing groups remain on each (unit-suffixed) tick. Negative
    views are never offset (no common), and units extend to days/hours/minutes
    for long pulses."""
    to_ns = lambda v: int(round(float(v) * 1e9))
    ticks = [to_ns(t) for t in ticks_s]
    if not ticks:
        return '', {}, 0, 1
    lo, hi = to_ns(lo_s), to_ns(hi_s)
    if lo > hi:
        lo, hi = hi, lo
    span = hi - lo
    st = sorted(ticks)
    diffs = [b - a for a, b in zip(st, st[1:]) if b > a]
    spacing = min(diffs) if diffs else (span if span > 0 else 1)
    if spacing <= 0:
        spacing = max(span, 1)
    g_idx = len(_DUR_UNITS) - 1
    for i, (_name, scale) in enumerate(_DUR_UNITS):
        if scale <= spacing:
            g_idx = i
            break
    g_scale = _DUR_UNITS[g_idx][1]
    base = 0
    common = ''
    if lo >= 0:
        cut_idx = -1
        for i in range(0, g_idx):
            scale = _DUR_UNITS[i][1]
            if lo // scale == hi // scale:
                cut_idx = i
            else:
                break
        if cut_idx >= 0:
            cut_scale = _DUR_UNITS[cut_idx][1]
            base = (lo // cut_scale) * cut_scale
            common = _fmt_duration(base, cut_scale) if base else ''
    labels = {tn: _fmt_duration(tn - base, g_scale) for tn in ticks}
    return common, labels, base, g_scale


# Fixed-ns "nice" step ladder for a relative-time axis (see matplotlib twin).
_REL_LADDER = [
    1, 2, 5, 10, 20, 50, 100, 200, 500,
    1_000, 2_000, 5_000, 10_000, 20_000, 50_000, 100_000, 200_000, 500_000,
    1_000_000, 2_000_000, 5_000_000, 10_000_000, 20_000_000, 50_000_000,
    100_000_000, 200_000_000, 500_000_000,
    1_000_000_000, 2_000_000_000, 5_000_000_000,
    10_000_000_000, 15_000_000_000, 30_000_000_000,
    60_000_000_000, 120_000_000_000, 300_000_000_000,
    600_000_000_000, 900_000_000_000, 1_800_000_000_000,
    3_600_000_000_000, 7_200_000_000_000, 10_800_000_000_000,
    21_600_000_000_000, 43_200_000_000_000,
    86_400_000_000_000, 172_800_000_000_000, 432_000_000_000_000,
    864_000_000_000_000, 2_592_000_000_000_000, 8_640_000_000_000_000,
]


def _rel_time_ticks(lo_ns: int, hi_ns: int, n: int):
    """Nice tick positions (integer ns, anchored at 0) for ~n ticks across the
    relative-time view [lo, hi]."""
    if hi_ns < lo_ns:
        lo_ns, hi_ns = hi_ns, lo_ns
    span = hi_ns - lo_ns
    if span <= 0:
        return [lo_ns]
    target = span / max(n, 1)
    step = _REL_LADDER[-1]
    for s in _REL_LADDER:
        if s >= target:
            step = s
            break
    import math
    first = math.ceil(lo_ns / step) * step
    out = []
    t = first
    while t <= hi_ns + step * 1e-9:
        out.append(int(round(t)))
        t += step
    return out


# ---------------------------------------------------------------------------
# Grafana-style "nice" interval ladder, in integer nanoseconds (UTC).
#
# Used by NanosecondDateFormatter.tickValues to place ticks on round civil-time
# boundaries (:00, :15, day, week, month, year) instead of on evenly spaced
# range/n positions. Sub-day steps use a 1/2/5 ladder anchored to UTC midnight;
# day/week/month/year steps are stepped on the actual calendar.
# ---------------------------------------------------------------------------
_NS = 1
_US = 1_000
_MS = 1_000_000
_SEC = 1_000_000_000
_MIN = 60 * _SEC
_HOUR = 60 * _MIN
_DAY = 24 * _HOUR
_WEEK = 7 * _DAY

# Segment indices (mirror NanosecondDateFormatter constants).
_YEAR, _MONTH, _DAY_SEG, _HOUR_SEG, _MINUTE, _SECOND, _MILI, _MICRO, _NANO = range(9)

_LADDER = [
    (1 * _NS, "fixed"),   (2 * _NS, "fixed"),   (5 * _NS, "fixed"),
    (10 * _NS, "fixed"),  (20 * _NS, "fixed"),  (50 * _NS, "fixed"),
    (100 * _NS, "fixed"), (200 * _NS, "fixed"), (500 * _NS, "fixed"),
    (1 * _US, "fixed"),   (2 * _US, "fixed"),   (5 * _US, "fixed"),
    (10 * _US, "fixed"),  (20 * _US, "fixed"),  (50 * _US, "fixed"),
    (100 * _US, "fixed"), (200 * _US, "fixed"), (500 * _US, "fixed"),
    (1 * _MS, "fixed"),   (2 * _MS, "fixed"),   (5 * _MS, "fixed"),
    (10 * _MS, "fixed"),  (20 * _MS, "fixed"),  (50 * _MS, "fixed"),
    (100 * _MS, "fixed"), (200 * _MS, "fixed"), (500 * _MS, "fixed"),
    (1 * _SEC, "fixed"),  (2 * _SEC, "fixed"),  (5 * _SEC, "fixed"),
    (10 * _SEC, "fixed"), (15 * _SEC, "fixed"), (30 * _SEC, "fixed"),
    (1 * _MIN, "fixed"),  (2 * _MIN, "fixed"),  (5 * _MIN, "fixed"),
    (10 * _MIN, "fixed"), (15 * _MIN, "fixed"), (30 * _MIN, "fixed"),
    (1 * _HOUR, "fixed"), (2 * _HOUR, "fixed"), (3 * _HOUR, "fixed"),
    (6 * _HOUR, "fixed"), (12 * _HOUR, "fixed"),
    (1 * _DAY, "day"),    (2 * _DAY, "day"),
    (1 * _WEEK, "week"),
    (1, "month"),         (3, "month"),         (6, "month"),
    (1, "year"),          (2, "year"),          (5, "year"),
    (10, "year"),         (20, "year"),         (50, "year"),
    (100, "year"),
]
_APPROX = {"month": 30 * _DAY, "year": 365 * _DAY}
_LADDER_APPROX_NS = [s * _APPROX[k] if k in _APPROX else s for s, k in _LADDER]
_UTC = timezone.utc


def _utc_dt(ns):
    return datetime.fromtimestamp(int(ns) // _SEC, tz=_UTC)


def _pick_interval(span_ns, target_ticks):
    span_ns = max(int(span_ns), 1)
    ideal = span_ns / max(int(target_ticks), 1)
    for approx, (step, kind) in zip(_LADDER_APPROX_NS, _LADDER):
        if approx >= ideal:
            return step, kind
    return _LADDER[-1]


def _gen_fixed(lo, hi, step):
    midnight = (int(lo) // _DAY) * _DAY
    k = (lo - midnight + step - 1) // step
    t = midnight + k * step
    out = []
    while t <= hi:
        out.append(t)
        t += step
    return out


def _gen_calendar_day(lo, hi, ndays, weekly):
    anchor = (int(lo) // _DAY) * _DAY
    if weekly:
        anchor -= _utc_dt(anchor).weekday() * _DAY
    step = (7 if weekly else ndays) * _DAY
    out = []
    t = anchor
    while t < lo:
        t += step
    while t <= hi:
        out.append(t)
        t += step
    return out


def _gen_month(lo, hi, nmonths):
    d = _utc_dt(lo)
    y, m = d.year, ((d.month - 1) // nmonths) * nmonths + 1
    out = []
    while True:
        ns = int(datetime(y, m, 1, tzinfo=_UTC).timestamp()) * _SEC
        if ns > hi:
            break
        if ns >= lo:
            out.append(ns)
        m += nmonths
        while m > 12:
            m -= 12
            y += 1
    return out


def _gen_year(lo, hi, nyears):
    y = (_utc_dt(lo).year // nyears) * nyears
    out = []
    while True:
        ns = int(datetime(y, 1, 1, tzinfo=_UTC).timestamp()) * _SEC
        if ns > hi:
            break
        if ns >= lo:
            out.append(ns)
        y += nyears
    return out


def _generate_ticks(lo_ns, hi_ns, step, kind):
    if hi_ns < lo_ns:
        lo_ns, hi_ns = hi_ns, lo_ns
    if kind == "fixed":
        return _gen_fixed(lo_ns, hi_ns, step)
    if kind == "day":
        return _gen_calendar_day(lo_ns, hi_ns, step // _DAY, weekly=False)
    if kind == "week":
        return _gen_calendar_day(lo_ns, hi_ns, 7, weekly=True)
    if kind == "month":
        return _gen_month(lo_ns, hi_ns, step)
    if kind == "year":
        return _gen_year(lo_ns, hi_ns, step)
    return []


def _segments_for_interval(step, kind):
    """Deepest date segment index needed to label this interval."""
    if kind == "year":
        return _YEAR
    if kind == "month":
        return _MONTH
    if kind in ("day", "week"):
        return _DAY_SEG
    if step >= _MIN:        # hour & minute steps -> HH:MM
        return _MINUTE
    if step >= _SEC:
        return _SECOND
    if step >= _MS:
        return _MILI
    if step >= _US:
        return _MICRO
    return _NANO


def is_time_label(label) -> bool:
    """True when an axis label marks a relative-time axis (iplotlib labels such
    an axis 'Time', optionally with a unit). Any other non-date X axis is a
    different quantity and must not get duration formatting."""
    return label is not None and 'time' in str(label).lower()


# ---------------------------------------------------------------------------
# Log-scaled Y axis ticks. Mirrors the matplotlib backend so both look the
# same: a sub-decade view reads as round mantissas under a single common power
# of ten (e.g. 120..200 with the corner showing 1e-6); a wider view reads as
# decade powers.
# ---------------------------------------------------------------------------
_LOG_STEPS = (1.0, 2.0, 2.5, 5.0, 10.0)


def _nice_ticks(lo, hi, n):
    """Up to ``n`` evenly spaced 'nice' (1/2/2.5/5 x 10^k) values within
    [lo, hi]."""
    if not (hi > lo) or n < 2:
        return [lo]
    raw = (hi - lo) / n
    mag = 10.0 ** floor(log10(raw))
    step = _LOG_STEPS[-1] * mag
    for s in _LOG_STEPS:
        if s * mag >= raw:
            step = s * mag
            break
    first = ceil(lo / step - 1e-9)
    last = floor(hi / step + 1e-9)
    return [(first + i) * step for i in range(last - first + 1)]


def _common_exp(maxabs):
    """Common power-of-ten factor, snapped to a multiple of 3 to match the
    engineering exponent used on the linear axis."""
    if maxabs <= 0:
        return 0
    return 3 * floor(log10(maxabs) / 3)


def log_axis_ticks(lo, hi, n):
    """Adaptive major ticks for a log Y axis. Returns ``(values, exp)``:
    sub-decade -> nice mantissas labelled under the common factor ``10**exp``;
    multi-decade -> decade powers (``exp`` is None, plain decimal labels)."""
    if lo <= 0 or hi <= lo:
        return [], None
    if log10(hi) - log10(lo) < 1.0:
        vals = _nice_ticks(lo, hi, n)
        return vals, (_common_exp(max(abs(v) for v in vals)) if vals else 0)
    e0, e1 = floor(log10(lo)), floor(log10(hi))
    subs = (1, 2, 5) if (e1 - e0) < 3 else (1,)
    vals = [s * 10.0 ** e for e in range(e0, e1 + 1) for s in subs
            if lo <= s * 10.0 ** e <= hi]
    return sorted(vals), None


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
        self._date_label_end = self.NANOSECOND
        # Engineering time decomposition state (relative non-date X axis)
        self._eng_common = ''
        self._eng_labels = None
        self._eng_base = 0
        self._eng_gscale = 1
        # Common power-of-ten factor for a sub-decade log Y axis (None -> plain
        # decade labels); set in tickValues, consumed in tickStrings.
        self._log_exp = None
        # Optional explicit relative-time override (set by the minimap, which
        # builds its own axis without copying the 'Time' label). None -> decide
        # from the label text.
        self._force_is_time = None
        if kwargs['orientation'] == 'bottom':
            self.common_label = pg.LabelItem(text='', justify='right')
        else:
            self.common_label = pg.LabelItem(text='', justify='left')

        self.enableAutoSIPrefix(False)

    def _is_rel_time(self) -> bool:
        """True only for a relative-*time* bottom axis. A non-date bottom axis
        is treated as time when its label is 'Time' (iplotlib convention), or
        when explicitly forced (minimap). Any other quantity keeps plain numeric
        ticks."""
        if self.is_date or self.orientation != 'bottom':
            return False
        if self._force_is_time is not None:
            return bool(self._force_is_time)
        return is_time_label(getattr(self, 'labelText', '') or '')

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

        if self.is_date:
            # Place ticks on round UTC civil-time boundaries (Grafana-style)
            # instead of evenly spaced range/n positions. All math is done in
            # absolute nanoseconds; values are returned in axis coordinates.
            abs_lo = self.get_real_value(minVal)
            abs_hi = self.get_real_value(maxVal)
            step_ns, kind = _pick_interval(abs(abs_hi - abs_lo), n)
            # In 100 us-unit mode the axis cannot resolve below 100 us, so never
            # pick a finer step (keeps back-conversion on exact integers).
            if self.offset == 100_000 and kind == "fixed" and step_ns < 100_000:
                step_ns, kind = 100_000, "fixed"
            ticks_abs = _generate_ticks(abs_lo, abs_hi, step_ns, kind)
            values = [self._abs_to_axis(t) for t in ticks_abs]

            self.last_values = values
            self.last_range = maxVal - minVal
            self._spacing = step_ns  # nanoseconds, for the "/div" spacing label
            self._date_label_end = _segments_for_interval(step_ns, kind)

            if values:
                a0 = self.get_real_value(int(values[0]))
                a1 = self.get_real_value(int(values[-1]))
                self.cut_start = self.lcp(a0, a1)
                self.offset_str = 'UTC:' + self.date_fmt(self.get_real_value(values[0]), self.YEAR,
                                                         self.cut_start, postfix_end=self.postfix_end,
                                                         postfix_start=self.postfix_start)
                tuple_spacing = abs(values[1] - values[0]) if len(values) >= 2 else (maxVal - minVal)
            else:
                tuple_spacing = maxVal - minVal
            return [(tuple_spacing, values)]

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

            if self.orientation == 'bottom' and self._is_rel_time():
                # Relative time (seconds) X axis. Replace the generic 1/2/5
                # decimal positions with round-duration ticks (1d, 12h, 5m, ...)
                # anchored at 0, then factor the constant part into the corner
                # (e.g. 36ms250us) and label each tick with the changing groups
                # + unit (e.g. 150ns). Negative views are not offset; units
                # extend to days for long pulses.
                rel = _rel_time_ticks(int(round(minVal * 1e9)),
                                      int(round(maxVal * 1e9)), n)
                if rel:
                    values = [t / 1e9 for t in rel]
                common, labels, base, g_scale = eng_time_axis_labels(
                    minVal, maxVal, list(values))
                self._eng_common = common
                self._eng_labels = labels
                self._eng_base = base
                self._eng_gscale = g_scale
                self._numeric_offset = 0.0
                self.autoSIPrefixScale = 1.0
                self.labelUnit = ''
                self.offset_str = common
                if len(values) >= 2:
                    spacing = values[1] - values[0]
                self._tick_spacing = spacing
            elif self.orientation == 'bottom':
                # Non-time relative X axis (some other quantity): keep the plain
                # evenly spaced positions and plain numeric labels. Crucially we
                # do NOT apply fn.siScale/set_scale here (that path is for the
                # vertical axis); doing so on the bottom axis suppressed the
                # ticks entirely.
                self._eng_labels = None
                self._eng_common = ''
                self._numeric_offset = 0.0
                self.autoSIPrefixScale = 1.0
                self.labelUnit = ''
                self.offset_str = ''
                if len(values) >= 2:
                    spacing = values[1] - values[0]
                self._tick_spacing = spacing
            else:
                # Y axis. Clear any stale duration state.
                self._eng_labels = None
                self._eng_common = ''
                self._numeric_offset = 0.0
                if self.logMode:
                    # Adaptive log ticks (mirrors the matplotlib backend):
                    # positions are log10 of the chosen data values, and a
                    # sub-decade view carries a common factor in the corner. Use
                    # the unclamped tick target so the tick set matches the
                    # matplotlib LogYLocator exactly (which does not pixel-clamp).
                    lo, hi = sorted((10.0 ** minVal, 10.0 ** maxVal))
                    tick_vals, exp = log_axis_ticks(lo, hi, self.n_ticks)
                    if tick_vals:
                        values = [log10(v) for v in tick_vals]
                        self.last_values = values
                    self._log_exp = exp
                    self.offset_str = f"1e{exp}" if exp else ''
                    self.autoSIPrefixScale = 1.0
                    self.labelUnit = ''
                    if len(values) >= 2:
                        spacing = values[1] - values[0]
                else:
                    # fn.siScale formatting.
                    _range = self.range
                    (scale, prefix) = fn.siScale(max(abs(_range[0] * self.scale), abs(_range[1] * self.scale)))
                    self.set_scale(scale, prefix)

        return [(spacing, values)]  # major ticks

    def tickStrings(self, values, scale, spacing):
        if self.is_date:
            end = max(self.cut_start + 1, getattr(self, '_date_label_end', self.NANOSECOND))
            values = list(
                map(lambda v: self.date_fmt(self.get_real_value(int(v)), self.cut_start + 1, end),
                    values))
            self.common_label.prepareGeometryChange()
            self.common_label.setText(self.offset_str)
        else:
            if self.orientation == 'bottom':
                # Relative time X axis: each tick is the finest changing group
                # (keyed by integer ns so the lookup is exact); the constant part
                # lives in the common (corner) label.
                if self._eng_labels is not None:
                    out = []
                    for v in values:
                        key = int(round(float(v) * 1e9))
                        lbl = self._eng_labels.get(key)
                        if lbl is None:
                            lbl = _fmt_duration(key - self._eng_base, self._eng_gscale)
                        out.append(lbl)
                    values = out
                else:
                    values = [f"{v:g}" for v in values]
                self.common_label.setText(self._eng_common)
                self._updateLabel()
            elif self.logMode:
                # Y axis in log mode: un-log to data space, then either factor
                # out the common power (sub-decade) or show plain decades.
                data = [10.0 ** v for v in values]
                if self._log_exp:
                    factor = 10.0 ** self._log_exp
                    values = [f"{d / factor:g}" for d in data]
                    self.common_label.setText(self.offset_str)
                else:
                    values = [f"{d:g}" for d in data]
                    self.common_label.setText("")
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
        # Integer arithmetic: the offset is ~1.8e18, whose float ULP is a few
        # hundred ns, so a float add would quantise away nanoseconds and can
        # collapse a narrow (ns) span. int(round(x)) + int(offset) keeps the
        # difference between ticks exact (the constant offset cancels).
        if self.offset == 100_000:
            return int(round(float(value))) * 100_000
        return int(round(float(value))) + int(self.offset)

    def _abs_to_axis(self, abs_ns):
        """Inverse of get_real_value: absolute ns -> axis coordinate.

        Uses int(offset) so the round-trip abs -> axis -> abs is exact. A float
        subtraction here (offset ~1.8e18, ULP a few hundred ns) would jitter the
        reconstructed tick value, e.g. labelling a 300 us tick as 294/299."""
        if self.offset == 100_000:
            return abs_ns / 100_000
        else:
            return abs_ns - int(self.offset)

    def format_full(self, value):
        """Full absolute UTC timestamp (year..nanosecond) for the crosshair readout,
        e.g. 2026-06-26T14:30:45.000000456. Unlike the tick labels, this is never
        truncated to the segments that vary across the visible range."""
        return self.date_fmt(self.get_real_value(value), self.YEAR, self.NANOSECOND)
