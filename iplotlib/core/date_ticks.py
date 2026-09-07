# Description: Civil-time tick intervals for date axes, shared by the
#              matplotlib and pyqtgraph date formatters.

"""Tick ladders shared by the matplotlib and pyqtgraph formatters.

Date axes place their ticks on round civil-time boundaries (:00, :15, day,
week, month, year), relative-time axes on round durations anchored at zero,
and plain numeric axes on 1/2/5 decimal positions. The ladders, the
interval choice and the tick generation live here so the two backends
cannot drift apart.

The configured tick count is a floor: the chosen step is the largest one
that still yields at least that many ticks, so asking for more ticks always
gives more, and never fewer than asked (only the axis resolution or a lack
of room can leave fewer).

Every generator anchors to absolute boundaries (midnight, Monday, the
calendar, zero, multiples of the step) rather than to the view edge, so
panning slides ticks in and out of the window instead of moving them.
"""

import datetime
import math

_NS = 1
_US = 1_000
_MS = 1_000_000
_SEC = 1_000_000_000
_MIN = 60 * _SEC
_HOUR = 60 * _MIN
_DAY = 24 * _HOUR
_WEEK = 7 * _DAY

# Segment indices, mirroring the NanosecondDateFormatter constants
# (YEAR=0 .. NANOSECOND=8) that both backends define identically.
_YEAR, _MONTH, _DAY_SEG, _HOUR_SEG, _MINUTE, _SECOND, _MILI, _MICRO, _NANO = range(9)

# (step, kind). kind drives anchoring: "fixed" steps are a fixed ns count
# anchored to UTC midnight; "day"/"week"/"month"/"year" step on the calendar.
# Consecutive rungs stay within ~2.5x of each other so the closest-count
# choice in pick_interval never lands far from the requested tick count.
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
    (1 * _DAY, "day"),    (2 * _DAY, "day"),    (3 * _DAY, "day"),
    (4 * _DAY, "day"),
    (1 * _WEEK, "week"),  (2 * _WEEK, "week"),
    (1, "month"),         (2, "month"),         (3, "month"),
    (6, "month"),
    (1, "year"),          (2, "year"),          (5, "year"),
    (10, "year"),         (20, "year"),         (50, "year"),
    (100, "year"),
]

_APPROX = {"month": 30 * _DAY, "year": 365 * _DAY}
_LADDER_DESC = sorted(
    ((s * _APPROX[k] if k in _APPROX else s, s, k) for s, k in _LADDER),
    key=lambda r: -r[0])

_UTC = datetime.timezone.utc

# First Monday after the epoch (1970-01-05), the anchor for week steps.
_MONDAY = 4 * _DAY


def _utc_dt(ns: int) -> datetime.datetime:
    """UTC datetime for the whole-seconds part of an absolute-ns timestamp."""
    return datetime.datetime.fromtimestamp(int(ns) // _SEC, tz=_UTC)


def pick_interval(lo_ns, hi_ns, target_ticks: int, min_step_ns: int = 0):
    """Largest ladder (step, kind) whose real tick count over [lo, hi]
    reaches ``target_ticks``, so the configured count acts as a minimum.

    The count is measured on the generated ticks, not on span/step: calendar
    steps anchor to real boundaries, and e.g. a 16-day window holds only two
    Mondays, far fewer than span/week would suggest.

    ``min_step_ns`` floors the choice at the axis resolution (100 us units or
    the adaptive unit scale), below which the axis cannot address positions;
    it is the only reason fewer ticks than asked can come back.
    """
    lo, hi = int(min(lo_ns, hi_ns)), int(max(lo_ns, hi_ns))
    if hi == lo:
        hi = lo + 1
    # The cap keeps a nonsense request from descending to nanosecond rungs,
    # where generating the candidate ticks over a wide window would not return.
    target = max(1, min(int(target_ticks), 500))
    finest = None  # last rung the resolution still allows
    for approx, step, kind in _LADDER_DESC:
        if approx < min_step_ns:
            break
        if len(generate_ticks(lo, hi, step, kind)) >= target:
            return step, kind
        finest = (step, kind)
    return finest


def _gen_fixed(lo, hi, step):
    # Anchored to UTC midnight; every fixed step divides a day exactly, so
    # the same positions come back regardless of which day lo falls on.
    midnight = (int(lo) // _DAY) * _DAY
    k = (lo - midnight + step - 1) // step
    t = midnight + k * step
    out = []
    while t <= hi:
        out.append(t)
        t += step
    return out


def _gen_day(lo, hi, ndays):
    # Multi-day steps anchor to epoch-aligned multiples (always UTC midnight)
    # so the positions do not depend on where the view starts.
    step = ndays * _DAY
    t = ((int(lo) + step - 1) // step) * step
    out = []
    while t <= hi:
        out.append(t)
        t += step
    return out


def _gen_week(lo, hi, step):
    # Mondays, epoch-aligned so alternate weeks stay the same alternates.
    t = -((_MONDAY - int(lo)) // step) * step + _MONDAY
    out = []
    while t <= hi:
        out.append(t)
        t += step
    return out


def _gen_month(lo, hi, nmonths):
    d = _utc_dt(lo)
    y, m = d.year, ((d.month - 1) // nmonths) * nmonths + 1
    out = []
    while True:
        ns = int(datetime.datetime(y, m, 1, tzinfo=_UTC).timestamp()) * _SEC
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
        ns = int(datetime.datetime(y, 1, 1, tzinfo=_UTC).timestamp()) * _SEC
        if ns > hi:
            break
        if ns >= lo:
            out.append(ns)
        y += nyears
    return out


def generate_ticks(lo_ns, hi_ns, step, kind):
    if hi_ns < lo_ns:
        lo_ns, hi_ns = hi_ns, lo_ns
    if kind == "fixed":
        return _gen_fixed(lo_ns, hi_ns, step)
    if kind == "day":
        return _gen_day(lo_ns, hi_ns, step // _DAY)
    if kind == "week":
        return _gen_week(lo_ns, hi_ns, step)
    if kind == "month":
        return _gen_month(lo_ns, hi_ns, step)
    if kind == "year":
        return _gen_year(lo_ns, hi_ns, step)
    return []


# Round-duration steps for a relative-time axis, anchored at zero:
# 1/2/5 decimals up to seconds, then minute/hour/day-based durations.
_REL_LADDER = [
    1, 2, 5, 10, 20, 50, 100, 200, 500,
    1_000, 2_000, 5_000, 10_000, 20_000, 50_000, 100_000, 200_000, 500_000,
    1_000_000, 2_000_000, 5_000_000, 10_000_000, 20_000_000, 50_000_000,
    100_000_000, 200_000_000, 500_000_000,
    1 * _SEC, 2 * _SEC, 5 * _SEC, 10 * _SEC, 15 * _SEC, 30 * _SEC,
    1 * _MIN, 2 * _MIN, 5 * _MIN, 10 * _MIN, 15 * _MIN, 30 * _MIN,
    1 * _HOUR, 2 * _HOUR, 3 * _HOUR, 6 * _HOUR, 12 * _HOUR,
    1 * _DAY, 2 * _DAY, 3 * _DAY, 4 * _DAY, 5 * _DAY, 10 * _DAY,
    30 * _DAY, 100 * _DAY,
]


def relative_ticks(lo_ns: int, hi_ns: int, target_ticks: int):
    """Round-duration tick positions (integer ns, anchored at 0) for a
    relative-time axis: the largest duration step still giving at least
    ``target_ticks`` over [lo, hi]."""
    if hi_ns < lo_ns:
        lo_ns, hi_ns = hi_ns, lo_ns
    span = hi_ns - lo_ns
    if span <= 0:
        return [lo_ns]
    # A step no larger than span/target guarantees at least target multiples
    # inside the window, since the anchoring at zero costs at most one.
    limit = span / max(1, min(int(target_ticks), 500))
    step = _REL_LADDER[0]
    for s in _REL_LADDER:
        if s > limit:
            break
        step = s
    first = -((-lo_ns) // step) * step
    out = []
    t = first
    while t <= hi_ns:
        out.append(int(t))
        t += step
    return out


def linear_ticks(lo: float, hi: float, target_ticks: int):
    """Nice (1/2/5 x 10^k) tick positions within [lo, hi]: the largest such
    step still giving at least ``target_ticks``. Positions are multiples of
    the step, so they hold still while the view pans."""
    if hi < lo:
        lo, hi = hi, lo
    span = hi - lo
    if span <= 0 or not math.isfinite(span):
        return [lo]
    limit = span / max(1, min(int(target_ticks), 500))
    mag = 10.0 ** math.floor(math.log10(limit))
    step = mag
    for m in (2.0, 5.0):
        if m * mag <= limit:
            step = m * mag
    # Multiply the index instead of accumulating the step: a running sum
    # drifts (0.2 is not exact in binary) and rendered zero as -5.6e-17.
    eps = step * 1e-9
    k0 = math.ceil(lo / step - 1e-9)
    k1 = math.floor(hi / step + 1e-9)
    return [k * step for k in range(k0, k1 + 1) if lo - eps <= k * step <= hi + eps]


def segments_for_interval(step, kind):
    """Deepest date segment index needed to label this interval.

    Mapping uses the formatter's segment constants (YEAR=0 .. NANOSECOND=8).
    Hour/minute steps go down to MINUTE so labels read HH:MM.
    """
    if kind == "year":
        return _YEAR
    if kind == "month":
        return _MONTH
    if kind in ("day", "week"):
        return _DAY_SEG
    if step >= _MIN:
        return _MINUTE
    if step >= _SEC:
        return _SECOND
    if step >= _MS:
        return _MILI
    if step >= _US:
        return _MICRO
    return _NANO
