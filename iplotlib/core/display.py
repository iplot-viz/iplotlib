"""
Display metrics and the single UI scale factor applied to size-like properties.

Sizes in iplotlib (``font_size``, ``line_size``, ``marker_size`` ...) are absolute
numbers tuned for a 96 DPI FullHD panel. On a 4K panel they stay the same
*logical* size, which means half the physical size whenever the session does not
scale by itself. This module resolves a single multiplier that
:class:`~iplotlib.core.property_manager.PropertyManager` applies on top of the
resolved property value, so no call site needs to change.

Resolution order (first rule that yields a value wins):

1. ``IPLOT_UI_SCALE``      -- ``off``, ``auto`` or a float. Site/env override.
2. :meth:`DisplayScale.configure` -- what an application persists for the user
   (MINT does this from its Appearance menu).
3. ``auto`` detection, see :func:`scale_from_metrics`.

Why detection is layered rather than a single formula: the metric one would
naturally use, ``QScreen.physicalDotsPerInch()``, is derived from the physical
display size reported by the display server. It is trustworthy on a local
session, and frequently nonsense over NX/VNC/Xvfb (a 1000x1000 mm fake screen
yields ~25 DPI). ``devicePixelRatio`` is authoritative when it is greater than
one but silent otherwise, and raw pixel resolution is the only metric every
remote protocol reports honestly. So each is used where it is meaningful and
the reason is recorded for :func:`describe`.
"""

# Author: added for HiDPI/4K support

import os
import typing

from iplotLogging import setupLogger as Sl

logger = Sl.get_logger(__name__)

#: Properties scaled by default.
#:
#: The rule is whether the cost of the property scales with the number of
#: samples. A font is drawn a fixed number of times per plot however much data
#: is loaded, and the crosshair is two line segments, so both are safe.
#:
#: line_size and marker_size are NOT in this set even though they are sizes.
#: A pen wider than one pixel leaves Qt's fast single-pixel line path and goes
#: through the stroker for every segment; with antialiasing on and a few hundred
#: thousand points that is the difference between a redraw and a locked-up UI.
#: pyqtgraph passes these straight to mkPen/symbolSize with no downsampling of
#: its own, so scaling line_size from 1 to 2 silently moved every default plot
#: onto the slow path on any high-DPI screen. Marker symbols are worse still:
#: each one is a separate painter path.
#:
#: They can be opted into (see SCALABLE_PROPERTIES) for a matplotlib-only setup
#: or for plots with modest point counts, but they must not be the default.
DEFAULT_SCALED_PROPERTIES = frozenset({
    'font_size',
    'crosshair_line_width',
})

#: Everything that MAY be scaled, i.e. what ui_scale_properties can name.
SCALABLE_PROPERTIES = frozenset({
    'font_size',
    'crosshair_line_width',
    'line_size',
    'marker_size',
})

#: Properties whose rendering cost grows with the sample count. Naming one of
#: these in ui_scale_properties is a deliberate trade of performance for size.
DATA_COST_PROPERTIES = frozenset({'line_size', 'marker_size'})

#: Kept as a module-level name for callers that only need the default set.
SCALED_PROPERTIES = DEFAULT_SCALED_PROPERTIES

MODE_AUTO = 'auto'
MODE_OFF = 'off'
MODE_FIXED = 'fixed'
MODES = (MODE_AUTO, MODE_OFF, MODE_FIXED)

REFERENCE_DPI = 96.0
MIN_SCALE = 1.0
MAX_SCALE = 3.0
#: Quantisation step. Keeps derived point sizes on whole/half numbers instead of
#: producing 8 -> 11.37 pt, which renders unevenly.
SCALE_STEP = 0.25
#: A logical/physical DPI outside this range is treated as not reported.
PLAUSIBLE_DPI = (72.0, 400.0)
#: Only believe a DPI-derived scale once it is meaningfully above the reference.
DPI_DEADBAND = 1.15

ENV_SCALE = 'IPLOT_UI_SCALE'
ENV_REFERENCE_DPI = 'IPLOT_UI_REFERENCE_DPI'
ENV_SCALE_PROPERTIES = 'IPLOT_UI_SCALE_PROPERTIES'

#: Environment markers for sessions where the reported physical display size
#: describes the server's idea of a screen rather than a real panel.
REMOTE_ENV_MARKERS = (
    'SSH_CONNECTION', 'SSH_CLIENT', 'SSH_TTY',
    'NXSESSIONID', 'NXDIR', 'NXCLIENT_VERSION',
    'VNCDESKTOP', 'VNCSERVER', 'X2GO_SESSION',
    'RDP_SESSION', 'CITRIX_SESSION',
)


def quantize(factor: float, step: float = SCALE_STEP) -> float:
    """Round ``factor`` to the nearest ``step``."""
    if step <= 0:
        return float(factor)
    return round(round(float(factor) / step) * step, 4)


def clamp(factor: float, low: float = MIN_SCALE, high: float = MAX_SCALE) -> float:
    return max(low, min(high, float(factor)))


def parse_scale_setting(value) -> typing.Tuple[str, float]:
    """Interpret a user/env scale setting as a ``(mode, value)`` pair.

    Accepts ``'auto'``, ``'off'``/``'1'``/``'none'`` and any float-like string.
    Unparseable input falls back to ``auto`` with a warning so a stale QSettings
    value or a typo in a deployment script never stops the application.
    """
    if value is None:
        return MODE_AUTO, 1.0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return MODE_FIXED, float(value)
    text = str(value).strip().lower()
    if text in ('', MODE_AUTO):
        return MODE_AUTO, 1.0
    if text in (MODE_OFF, 'none', 'no', 'false', '0'):
        return MODE_OFF, 1.0
    try:
        return MODE_FIXED, float(text)
    except ValueError:
        logger.warning(f"Unrecognised UI scale setting {value!r}, using '{MODE_AUTO}'")
        return MODE_AUTO, 1.0


def parse_scaled_properties(value) -> frozenset:
    """Interpret a comma-separated property list, ignoring unknown names.

    Anything outside :data:`SCALABLE_PROPERTIES` is dropped with a warning: a
    typo must not silently scale nothing, and an arbitrary property name must
    not be scaled just because someone wrote it in a config file.
    """
    if value is None:
        return DEFAULT_SCALED_PROPERTIES
    if isinstance(value, (set, frozenset, list, tuple)):
        names = [str(v).strip() for v in value]
    else:
        names = [part.strip() for part in str(value).split(',')]
    names = [n for n in names if n]
    if not names:
        return frozenset()
    if len(names) == 1 and names[0].lower() in ('default', 'defaults'):
        return DEFAULT_SCALED_PROPERTIES
    known, unknown = set(), []
    for name in names:
        if name in SCALABLE_PROPERTIES:
            known.add(name)
        else:
            unknown.append(name)
    if unknown:
        logger.warning(f"Ignoring unscalable propert{'y' if len(unknown) == 1 else 'ies'}: "
                       f"{', '.join(unknown)}. Scalable: {', '.join(sorted(SCALABLE_PROPERTIES))}")
    risky = known & DATA_COST_PROPERTIES
    if risky:
        logger.warning(
            f"Scaling {', '.join(sorted(risky))} is enabled. Their rendering cost grows "
            "with the sample count; with the pyqtgraph backend a width above 1 leaves "
            "Qt's fast line path and can make large plots unresponsive.")
    return frozenset(known)


def remote_session_markers(env: typing.Optional[typing.Mapping] = None) -> typing.List[str]:
    """Names of the environment variables suggesting a remote display session."""
    env = os.environ if env is None else env
    found = [name for name in REMOTE_ENV_MARKERS if env.get(name)]
    display = env.get('DISPLAY', '')
    # A DISPLAY with a host part is forwarded rather than local.
    if display and not display.startswith(':') and ':' in display:
        found.append('DISPLAY')
    return found


def collect_metrics() -> dict:
    """Snapshot the screen metrics used by :func:`scale_from_metrics`.

    Returns an empty-ish mapping when no ``QGuiApplication`` exists yet (CLI
    export, unit tests), which :func:`scale_from_metrics` treats as "unknown"
    and answers 1.0 for.
    """
    metrics = {
        'available': False,
        'device_pixel_ratio': 1.0,
        'logical_dpi': 0.0,
        'physical_dpi': 0.0,
        'width_px': 0,
        'height_px': 0,
        'screen_name': '',
        'screen_count': 0,
        'remote_markers': remote_session_markers(),
        'session_type': os.environ.get('XDG_SESSION_TYPE', ''),
        'qt_scale_factor': os.environ.get('QT_SCALE_FACTOR', ''),
        'qt_font_dpi': os.environ.get('QT_FONT_DPI', ''),
    }
    try:
        from PySide6.QtGui import QGuiApplication
    except ImportError:  # pragma: no cover - Qt is optional for core use
        return metrics
    if QGuiApplication.instance() is None:
        return metrics
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return metrics
    geometry = screen.geometry()
    metrics.update({
        'available': True,
        'device_pixel_ratio': float(screen.devicePixelRatio()),
        'logical_dpi': float(screen.logicalDotsPerInch()),
        'physical_dpi': float(screen.physicalDotsPerInch()),
        # geometry() is in device-independent pixels; multiply back out so the
        # value describes the panel rather than the scaled desktop.
        'width_px': int(geometry.width() * screen.devicePixelRatio()),
        'height_px': int(geometry.height() * screen.devicePixelRatio()),
        'screen_name': screen.name(),
        'screen_count': len(QGuiApplication.screens()),
    })
    return metrics


def _bucket_from_width(width_px: int) -> typing.Optional[float]:
    """Scale implied by raw pixel width.

    Pixel counts are the only metric NX, VNC and X2Go report honestly, so this
    is the fallback when no DPI can be trusted.
    """
    if width_px >= 3840:
        return 2.0
    if width_px >= 2560:
        return 1.5
    return None


def scale_from_metrics(metrics: dict,
                       reference_dpi: float = REFERENCE_DPI,
                       min_scale: float = MIN_SCALE,
                       max_scale: float = MAX_SCALE) -> typing.Tuple[float, str]:
    """Resolve ``(factor, reason)`` from a :func:`collect_metrics` snapshot.

    ``reason`` names the rule that fired and is surfaced by
    ``iplotlib-display-info``, so a user report of "the text is too small on
    this workstation" says which branch was taken.
    """
    if not metrics.get('available'):
        return 1.0, "no screen available (headless or pre-QApplication), assuming 1.0"

    dpr = float(metrics.get('device_pixel_ratio') or 1.0)
    if dpr > 1.01:
        # Qt (via the compositor, Xft.dpi or QT_SCALE_FACTOR) is already scaling
        # every logical pixel and point size. Scaling again would double-apply.
        return 1.0, f"session already scales (devicePixelRatio={dpr:g}), no extra scaling"

    logical = float(metrics.get('logical_dpi') or 0.0)
    if (PLAUSIBLE_DPI[0] <= logical <= PLAUSIBLE_DPI[1]
            and logical >= reference_dpi * DPI_DEADBAND):
        factor = quantize(clamp(logical / reference_dpi, min_scale, max_scale))
        return factor, f"logical DPI {logical:g} / {reference_dpi:g}"

    remote = metrics.get('remote_markers') or []
    physical = float(metrics.get('physical_dpi') or 0.0)
    if not remote and PLAUSIBLE_DPI[0] <= physical <= PLAUSIBLE_DPI[1]:
        if physical >= reference_dpi * DPI_DEADBAND:
            factor = quantize(clamp(physical / reference_dpi, min_scale, max_scale))
            return factor, f"physical DPI {physical:g} / {reference_dpi:g}"
        return 1.0, f"physical DPI {physical:g} at or below reference, no scaling"

    width = int(metrics.get('width_px') or 0)
    bucket = _bucket_from_width(width)
    why_dpi = ("remote session (%s), physical DPI not trusted" % ','.join(remote)) if remote \
        else "no usable DPI reported"
    if bucket is not None:
        factor = quantize(clamp(bucket, min_scale, max_scale))
        return factor, f"{why_dpi}; {width}px wide -> {factor:g}"
    return 1.0, f"{why_dpi}; {width}px wide -> no scaling"


class DisplayScale:
    """Process-wide holder for the resolved UI scale factor.

    A singleton because it is read from the property lookup on every rendered
    primitive and must agree with the widget font the application installed.
    """

    _instance = None  # type: typing.Optional[DisplayScale]

    def __init__(self):
        self._mode = MODE_AUTO
        self._value = 1.0
        self._reference_dpi = REFERENCE_DPI
        self._min_scale = MIN_SCALE
        self._max_scale = MAX_SCALE
        self._cached = None  # type: typing.Optional[float]
        self._reason = 'not resolved yet'
        self._env_locked = False
        self._scaled_properties = DEFAULT_SCALED_PROPERTIES
        self._apply_env()

    @classmethod
    def instance(cls) -> 'DisplayScale':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls):
        """Drop the singleton. For tests."""
        cls._instance = None

    def _apply_env(self):
        raw_dpi = os.environ.get(ENV_REFERENCE_DPI)
        if raw_dpi:
            try:
                self._reference_dpi = float(raw_dpi)
            except ValueError:
                logger.warning(f"Ignoring invalid {ENV_REFERENCE_DPI}={raw_dpi!r}")
        raw_props = os.environ.get(ENV_SCALE_PROPERTIES)
        if raw_props is not None:
            self._scaled_properties = parse_scaled_properties(raw_props)
        raw = os.environ.get(ENV_SCALE)
        if raw:
            self._mode, self._value = parse_scale_setting(raw)
            # An explicit environment setting is a deployment decision and is not
            # overridden by a persisted user preference.
            self._env_locked = True
            logger.info(f"UI scale pinned by {ENV_SCALE}={raw!r} -> mode={self._mode} value={self._value}")

    def configure(self, mode=None, value=None, reference_dpi=None,
                  min_scale=None, max_scale=None, scaled_properties=None, force=False):
        """Set the scale from an application preference.

        Ignored (unless ``force``) when ``IPLOT_UI_SCALE`` is set, so a site-wide
        environment override is not silently undone by a stale user setting.
        """
        if self._env_locked and not force:
            logger.debug(f"UI scale request ignored, {ENV_SCALE} takes precedence")
            return self.factor()
        if scaled_properties is not None and not os.environ.get(ENV_SCALE_PROPERTIES):
            self._scaled_properties = parse_scaled_properties(scaled_properties)
        if reference_dpi is not None:
            self._reference_dpi = float(reference_dpi)
        if min_scale is not None:
            self._min_scale = float(min_scale)
        if max_scale is not None:
            self._max_scale = float(max_scale)
        if mode is not None:
            if value is None and mode not in MODES:
                mode, value = parse_scale_setting(mode)
            if mode not in MODES:
                mode, value = parse_scale_setting(mode)
            self._mode = mode
        if value is not None:
            self._value = float(value)
        self.invalidate()
        return self.factor()

    def invalidate(self):
        """Forget the cached factor. Call when the window changes screen."""
        self._cached = None

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def scaled_properties(self) -> frozenset:
        return self._scaled_properties

    def factor(self) -> float:
        if self._mode == MODE_OFF:
            self._reason = "disabled"
            return 1.0
        if self._mode == MODE_FIXED:
            self._reason = f"fixed at {self._value:g}"
            return clamp(self._value, self._min_scale, self._max_scale)
        if self._cached is not None:
            return self._cached
        metrics = collect_metrics()
        factor, reason = scale_from_metrics(
            metrics, self._reference_dpi, self._min_scale, self._max_scale)
        self._reason = reason
        if metrics.get('available'):
            # Only cache once a real screen answered; otherwise retry after the
            # QApplication comes up.
            self._cached = factor
            logger.info(f"UI scale resolved to {factor:g} ({reason})")
        return factor

    def apply(self, attr_name: str, value):
        """Scale ``value`` when ``attr_name`` names a size property."""
        if value is None or attr_name not in self._scaled_properties:
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value
        factor = self.factor()
        if factor == 1.0:
            return value
        scaled = value * factor
        if isinstance(value, int):
            # Keep a non-zero size visible after rounding.
            return max(1, int(round(scaled)))
        return scaled

    def px(self, value) -> int:
        """Scale a widget pixel constant (minimum heights, margins ...)."""
        return max(1, int(round(value * self.factor())))

    def describe(self) -> dict:
        """Every metric plus the resolved factor, for diagnostics."""
        info = dict(collect_metrics())
        info['mode'] = self._mode
        info['configured_value'] = self._value
        info['reference_dpi'] = self._reference_dpi
        info['factor'] = self.factor()
        info['reason'] = self._reason
        info['env_locked'] = self._env_locked
        info['scaled_properties'] = ','.join(sorted(self._scaled_properties))
        return info


class ScaledPixels:
    """A widget pixel constant that follows the UI scale.

    Deliberately lazy: module-level constants are created at import time, long
    before the QApplication exists and therefore before any screen can be
    queried. Call :meth:`px` at the point of use.

        MINIMAP_MIN_HEIGHT = ScaledPixels(110)
        widget.setMinimumHeight(MINIMAP_MIN_HEIGHT.px())
    """

    __slots__ = ('base',)

    def __init__(self, base: float):
        self.base = base

    def px(self) -> int:
        return DisplayScale.instance().px(self.base)

    def __int__(self) -> int:
        return self.px()

    def __repr__(self) -> str:  # pragma: no cover
        return f"ScaledPixels({self.base})"


def factor() -> float:
    """Shorthand for ``DisplayScale.instance().factor()``."""
    return DisplayScale.instance().factor()


def screen_pixel_width() -> int:
    """Widest screen in *physical* pixels, 0 when unknown.

    ``QScreen.geometry()`` is in device-independent pixels, so on a scaled
    session it under-reports the panel. Used for the decimation sample count,
    where the point is how many samples the hardware can actually resolve.
    """
    try:
        from PySide6.QtGui import QGuiApplication
    except ImportError:  # pragma: no cover
        return 0
    if QGuiApplication.instance() is None:
        return 0
    widest = 0
    for screen in QGuiApplication.screens():
        widest = max(widest, int(screen.geometry().width() * screen.devicePixelRatio()))
    return widest


def apply_hidpi_policy(rounding: typing.Optional[str] = None):
    """Configure Qt high-DPI behaviour. Must run *before* the QApplication.

    ``rounding`` is a :class:`Qt.HighDpiScaleFactorRoundingPolicy` name, or None
    to take ``IPLOT_HIDPI_ROUNDING``. ``PassThrough`` (the Qt 6 default) keeps
    fractional scale factors; ``Round`` snaps them to integers, which renders
    1px borders more crisply on a 4K panel at 150%.
    """
    name = rounding or os.environ.get('IPLOT_HIDPI_ROUNDING')
    if not name:
        return
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
    except ImportError:  # pragma: no cover
        return
    policy = getattr(Qt.HighDpiScaleFactorRoundingPolicy, name, None)
    if policy is None:
        logger.warning(f"Unknown high-DPI rounding policy: {name}")
        return
    if QGuiApplication.instance() is not None:
        logger.warning("High-DPI rounding policy must be set before the QApplication; ignoring")
        return
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(policy)
    logger.info(f"High-DPI scale factor rounding policy: {name}")


def print_display_info() -> int:
    """Console entry point: dump display metrics and the resolved scale."""
    import sys
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 is not available; cannot query screens.")
        return 1
    app = QApplication.instance() or QApplication(sys.argv)
    info = DisplayScale.instance().describe()
    width = max(len(k) for k in info)
    print("iplotlib display info")
    print("-" * (width + 40))
    for key in sorted(info):
        print(f"{key:<{width}} : {info[key]}")
    print("-" * (width + 40))
    print(f"Override with {ENV_SCALE}=<off|auto|1.5|2.0>")
    del app
    return 0
