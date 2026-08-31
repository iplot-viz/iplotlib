import datetime
import re as _re

from matplotlib.ticker import ScalarFormatter, Locator, MaxNLocator
from matplotlib.axis import XAxis
import pandas

from iplotlib.core.date_ticks import (
    pick_interval as _pick_interval,
    generate_ticks as _generate_ticks,
    segments_for_interval as _segments_for_interval,
)
import iplotLogging.setupLogger as Sl

logger = Sl.get_logger(__name__)

# ---------------------------------------------------------------------------
# Engineering time-unit decomposition for a *relative* (seconds) X axis.
#
# At deep zoom a relative-seconds axis like 0.007690452 s reads badly when the
# whole value is printed on every tick (the constant high-order digits swamp the
# few that change). Instead we split the value into s / ms / us / ns groups,
# factor the groups that are constant across the view into a single common label
# (e.g. "7ms690us"), and label the ticks with the finest changing group plus its
# unit (e.g. 452 / 467 with the axis reading "[ns]").
# ---------------------------------------------------------------------------
_DUR_UNITS = [('d', 86_400_000_000_000), ('h', 3_600_000_000_000),
              ('min', 60_000_000_000), ('s', 1_000_000_000),
              ('ms', 1_000_000), ('us', 1_000), ('ns', 1)]
_DUR_UNAME = {scale: name for name, scale in _DUR_UNITS}


def _fmt_duration(ns: int, min_scale: int) -> str:
    """Render an integer-ns duration as concatenated groups from the largest
    non-zero unit down to ``min_scale``, sign-prefixed. Note ``m`` is minutes
    and ``ms`` is milliseconds. Examples: 90061e9 ns @ s -> '1d1h1m1s';
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
    """Decompose a relative-time (seconds) view into
    (common_label, {ns_key: label}, base_ns, unit_scale).

    The tick *granularity* unit is chosen from the tick spacing (5 ns steps read
    in ns, 2 us steps in us, 12 h steps in h, ...). The *common* part is the
    deepest group the **view** shares, factored out so only the changing groups
    remain on the ticks (e.g. common '36ms250us', ticks 0ns/150ns/...). Each tick
    label carries its own unit. Two deliberate rules:
      * negative views are never offset (lo < 0 -> no common), since subtracting
        a base from a negative time is counter-intuitive; the ticks show the full
        signed duration instead;
      * units extend up to days, so long pulses read '1d', '2d', '1d12h', ...
    """
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
    # granularity = largest unit whose scale fits in one tick step
    g_idx = len(_DUR_UNITS) - 1
    for i, (_name, scale) in enumerate(_DUR_UNITS):
        if scale <= spacing:
            g_idx = i
            break
    g_scale = _DUR_UNITS[g_idx][1]
    # common = deepest group above the granularity that the *view* shares, but
    # only for non-negative views (never offset negative time).
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


# Fixed-ns "nice" step ladder for a relative-time axis (a duration from 0, so no
# calendar/leap concerns): 1/2/5 through sub-second, then 1/2/5/10/15/30 s,
# 1/2/5/10/15/30 m, 1/2/3/6/12 h, then days. Lets a multi-day pulse land on
# round boundaries ("1d", "12h", "5m") instead of decimal seconds.
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
    """Nice tick positions (integer ns, anchored at 0) for a relative-time axis,
    aiming for ~n ticks across [lo, hi]."""
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
    # small epsilon so the last boundary isn't dropped by float error
    while t <= hi_ns + step * 1e-9:
        out.append(int(round(t)))
        t += step
    return out


# Tick intervals and generators for the date axis are shared with the
# pyqtgraph backend (iplotlib.core.date_ticks). The companion locator
# (NiceNanosecondLocator) snaps tick positions to round UTC civil-time
# boundaries instead of round *numbers of nanoseconds* the way MaxNLocator
# would.


class RelativeTimeLocator(Locator):
    """Major-tick locator for a non-date X axis. When the axis is a relative
    *time* axis (label 'Time'), it places ticks on round duration boundaries
    (1d, 12h, 5m, 100ms, ...) anchored at 0 via the shared _rel_time_ticks
    ladder, so long pulses read '1d'/'2d'. For any other quantity it defers to a
    plain MaxNLocator. The label is read live at draw time, because it is only
    applied during signal processing (after this locator is attached)."""

    def __init__(self, nbins: int = 7, force_time: bool = False):
        self.nbins = max(int(nbins), 2)
        self._force_time = bool(force_time)
        self._fallback = MaxNLocator(self.nbins)

    def set_axis(self, axis):
        super().set_axis(axis)
        try:
            self._fallback.set_axis(axis)
        except Exception:
            pass

    def _axis_is_time(self) -> bool:
        if self._force_time:
            return True
        try:
            return is_time_label(self.axis.get_label().get_text())
        except Exception:
            return False

    def __call__(self):
        vmin, vmax = self.axis.get_view_interval()
        return self.tick_values(vmin, vmax)

    def tick_values(self, vmin, vmax):
        if not self._axis_is_time():
            return self._fallback.tick_values(vmin, vmax)
        if vmin == vmax:
            return [vmin]
        ticks_ns = _rel_time_ticks(int(round(float(vmin) * 1e9)),
                                   int(round(float(vmax) * 1e9)), self.nbins)
        return [t / 1e9 for t in ticks_ns]


def is_time_label(label) -> bool:
    """True when an axis label marks a relative-time axis. The iplotlib
    convention labels such an axis 'Time' (optionally with a unit, e.g.
    'Time [s]'); any other non-date X axis is some other quantity and must not
    get duration formatting."""
    return label is not None and 'time' in str(label).lower()


class ExponentScalarFormatter(ScalarFormatter):
    """Formatter for a relative (non-date) axis.

    When the axis is a relative-*time* X axis (``is_time=True``, i.e. its label
    is 'Time'), it renders durations in engineering groups: the constant high
    part is factored into the corner offset (e.g. ``36ms250us``) and each tick
    shows the changing groups with their unit (e.g. ``150ns``, ``1d``). A
    non-time X axis (some other relative quantity) and the Y axis keep the plain
    exponent behaviour."""

    def __init__(self, label_props: dict = None, is_time: bool = False):
        super().__init__(useOffset=True, useMathText=False)
        self.set_powerlimits((-3, 3))
        self._label_props = label_props or {}
        self._is_time = bool(is_time)
        self._eng_common = ''
        self._eng_labels = None
        self._eng_base = 0
        self._eng_gscale = 1

    def _is_time_axis(self) -> bool:
        if not isinstance(self.axis, XAxis):
            return False
        if self._is_time:
            return True
        # The 'Time' label is applied during signal processing, after this
        # formatter is constructed, so read it live at draw time rather than
        # trusting a flag captured at setup.
        try:
            return is_time_label(self.axis.get_label().get_text())
        except Exception:
            return False

    def _set_order_of_magnitude(self):
        # Engineering notation for the Y axis (and any non-time fallback): snap
        # the common exponent to a multiple of 3 so it reads 1e-6 instead of
        # 1e-5. The X time axis is handled by the decomposition below and does
        # not rely on this.
        super()._set_order_of_magnitude()
        if self.orderOfMagnitude:
            self.orderOfMagnitude = 3 * (int(self.orderOfMagnitude) // 3)

    def set_locs(self, locs) -> None:
        self._eng_labels = None
        if self._is_time_axis() and locs is not None and len(locs):
            try:
                lo, hi = self.axis.get_view_interval()
                common, labels, base, g_scale = eng_time_axis_labels(
                    lo, hi, list(locs))
                self._eng_common = common
                self._eng_labels = labels
                self._eng_base = base
                self._eng_gscale = g_scale
            except Exception:
                self._eng_labels = None
        super().set_locs(locs)

    def __call__(self, x, pos=None):
        if self._is_time_axis() and self._eng_labels is not None:
            key = int(round(float(x) * 1e9))
            label = self._eng_labels.get(key)
            if label is None:
                # off-grid tick (rare): derive the same duration label
                label = _fmt_duration(key - self._eng_base, self._eng_gscale)
            return label
        return super().__call__(x, pos)

    def format_data_short(self, value):
        # Crosshair / status bar on a relative-time X axis: full human-readable
        # duration (e.g. 36ms250us452ns, -4ms500us). A non-time axis keeps the
        # default numeric short format.
        if self._is_time_axis():
            return _fmt_duration(int(round(float(value) * 1e9)), 1)
        return super().format_data_short(value)

    def get_offset(self):
        """Y axis / non-time X axis: plain exponent. Relative-time X axis: the
        constant ``common`` duration shown in the corner offset (the per-tick
        unit lives on the ticks, and the axis-label unit is left untouched)."""
        if not self._is_time_axis():
            return super().get_offset()

        if self._eng_labels is not None:
            return self._eng_common

        # Fallback (e.g. before any locs are set): plain engineering exponent.
        if self.orderOfMagnitude and self.orderOfMagnitude != 0:
            return f'1e{self.orderOfMagnitude}'
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
                 roundh=False, nice_locator: "NiceNanosecondLocator" = None):
        super().__init__()
        self.postfix_end = postfix_end
        self.postfix_start = postfix_start
        self.label_segments = label_segments
        self.offset_str = "N/A"
        self.cut_start = 0
        self._offset_lut = offset_lut
        self._ax_idx = ax_idx
        self._round = roundh
        # When linked to a NiceNanosecondLocator, label precision tracks the
        # interval the locator chose for the current zoom (so we never print
        # spurious trailing zeros, and always show enough digits).
        self._nice_locator = nice_locator

    @property
    def offset_ns(self):
        if not self._offset_lut:
            return 0
        if len(self._offset_lut) > self._ax_idx and self._offset_lut[self._ax_idx] is not None:
            return self._offset_lut[self._ax_idx]
        return 0

    def _apply_locator_precision(self):
        """If linked to a nice locator, set label_segments from its interval."""
        if self._nice_locator is None:
            return
        interval = self._nice_locator.current_interval()
        if interval is None:
            return
        step, kind = interval
        needed = _segments_for_interval(step, kind)
        self.label_segments = max(1, needed - self.cut_start)

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

        self._apply_locator_precision()
        super().set_locs(locs)

    def __call__(self, x, pos=None):
        if self.offset_ns == 100_000:
            return self.date_fmt(int(self.offset_ns) * int(x), self.cut_start + 1, self.cut_start + self.label_segments)
        else:
            return self.date_fmt(int(self.offset_ns) + int(x), self.cut_start + 1, self.cut_start + self.label_segments)

    def format_data_short(self, value):
        # Used by the crosshair / coordinate readout (Axes.format_xdata).
        # Unlike the tick labels (__call__), which show only the segments that
        # vary at the current zoom, the cursor shows the full absolute UTC
        # timestamp from year down to nanosecond, e.g.
        # 2026-06-26T14:30:45.000000456
        # (The axis offset text already carries the 'UTC:' marker.)
        if self.offset_ns == 100_000:
            ts = int(self.offset_ns) * int(round(float(value)))
        else:
            ts = int(self.offset_ns) + int(round(float(value)))
        return self.date_fmt(ts, self.YEAR, self.NANOSECOND)

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


class NiceNanosecondLocator(Locator):
    """Tick locator that places ticks on round UTC civil-time boundaries.

    It is the time-aware replacement for ``MaxNLocator`` on iplotlib date
    axes. It reads the same per-axis offset table as
    :class:`NanosecondDateFormatter` and converts between matplotlib axis
    coordinates and absolute nanoseconds-since-epoch using exactly the
    convention of ``ImplementationPlotCacheTable.transform_value``:

        * ``offset is None`` / ``0`` -> ``abs_ns = x``                (identity)
        * ``offset == 100_000``      -> ``abs_ns = x * 100_000``      (100 us units, wide windows)
        * otherwise                  -> ``abs_ns = x + int(offset)``  (offset base, narrow windows)

    Tick positions are chosen in absolute ns (always UTC) from the Grafana-style
    ladder and converted back to axis coordinates, so positions and the
    formatter's labels always agree.

    Parameters
    ----------
    ax_idx : int
        Axis index used to look up the offset in ``offset_lut`` (0 = x).
    offset_lut : dict | list
        The per-axis offsets (pass ``cache_item.offsets``), shared with the
        formatter.
    target_ticks : int
        Desired number of major ticks (``tick_number`` from the axis params).
    """

    def __init__(self, ax_idx: int = 0, offset_lut=None, target_ticks: int = 6):
        self._ax_idx = ax_idx
        self._offset_lut = offset_lut
        self.target_ticks = max(int(target_ticks), 2)
        self._last_interval = None  # (step, kind) of the most recent computation

    # --- offset handling, mirrors NanosecondDateFormatter.offset_ns ---------
    @property
    def offset_ns(self):
        if not self._offset_lut:
            return 0
        if len(self._offset_lut) > self._ax_idx and self._offset_lut[self._ax_idx] is not None:
            return self._offset_lut[self._ax_idx]
        return 0

    def _to_abs(self, x) -> int:
        off = self.offset_ns
        if off == 100_000:
            return int(round(float(x))) * 100_000
        if off in (0, None):
            return int(round(float(x)))
        return int(round(float(x))) + int(off)

    def _to_axis(self, abs_ns: int) -> float:
        off = self.offset_ns
        if off == 100_000:
            return abs_ns / 100_000
        if off in (0, None):
            return float(abs_ns)
        return float(abs_ns - int(off))

    def current_interval(self):
        """(step, kind) chosen on the most recent call; used by the formatter."""
        return self._last_interval

    # --- matplotlib Locator API ---------------------------------------------
    def tick_values(self, vmin, vmax):
        if vmin == vmax:
            vmax = vmin + 1
        lo = self._to_abs(min(vmin, vmax))
        hi = self._to_abs(max(vmin, vmax))
        # In 100 us-unit mode the axis cannot resolve below 100 us, so never
        # choose a finer step (keeps back-conversion on exact integers).
        min_step = 100_000 if self.offset_ns == 100_000 else 0
        step, kind = _pick_interval(lo, hi, self.target_ticks, min_step)
        self._last_interval = (step, kind)
        ticks_abs = _generate_ticks(lo, hi, step, kind)
        return self.raise_if_exceeds([self._to_axis(t) for t in ticks_abs])

    def __call__(self):
        vmin, vmax = self.axis.get_view_interval()
        return self.tick_values(vmin, vmax)
