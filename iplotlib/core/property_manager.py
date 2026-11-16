import json
import os
from iplotlib.core.display import DisplayScale
from iplotLogging import setupLogger as Sl

logger = Sl.get_logger(__name__)

ROOT = os.path.dirname(__file__)
data_dir = os.path.join(ROOT, 'data')
os.makedirs(data_dir, exist_ok=True)
file_name = os.path.join(data_dir, "default_properties.json")

IPLOT_CANVAS_CONFIG = os.environ.get('IPLOT_CANVAS_CONFIG')

#: Where the preferences form writes when the user exports canvas preferences.
#: It lives in the user's home directory, so it follows them to whichever
#: workstation or ssh session they are on -- which an environment variable set
#: in a login profile does not.
USER_CONFIG = os.path.join(os.path.expanduser('~'), '.local', '1DPreferences',
                           'default_properties.json')


def _resolve_config_path() -> str:
    if IPLOT_CANVAS_CONFIG:
        return IPLOT_CANVAS_CONFIG
    if os.path.isfile(USER_CONFIG):
        logger.info(f"Using exported canvas preferences: {USER_CONFIG}")
        return USER_CONFIG
    return file_name


config_path = _resolve_config_path()

try:
    with open(config_path, "r") as f:
        properties = json.load(f)
except FileNotFoundError:
    logger.error(f"Configuration file not found: {config_path}")
    properties = file_name
except Exception as e:
    logger.error(f"Error while loading canvas configuration from {config_path}: {e}")
    properties = file_name


def _configure_display_scale(config: dict):
    """Seed the UI scale from the canvas configuration file.

    The environment variable still wins; see :class:`DisplayScale`.
    """
    if not isinstance(config, dict):
        return
    DisplayScale.instance().configure(
        mode=config.get('ui_scale_mode'),
        value=config.get('ui_scale'),
        reference_dpi=config.get('ui_reference_dpi'),
        min_scale=config.get('ui_scale_min'),
        max_scale=config.get('ui_scale_max'),
        scaled_properties=config.get('ui_scale_properties'),
    )


_configure_display_scale(properties)


def _shipped_colors() -> dict:
    """The colours of the shipped defaults that a theme replaces: an exported configuration may set others."""
    try:
        with open(file_name, "r") as f:
            shipped = json.load(f)
    except Exception:
        return {}
    return {name: str(shipped[name]).lower() for name in ('background_color', 'font_color') if shipped.get(name)}


_SHIPPED_COLORS = _shipped_colors()
#: The colours a theme draws with instead of those of _SHIPPED_COLORS, by property (see set_theme_colors).
_theme_colors = {}


def set_theme_colors(colors: dict):
    """Draw the properties named in `colors` with the colour given for each where they have their shipped default
    colour, as in a dark theme. With none, they are drawn as set."""
    _theme_colors.clear()
    _theme_colors.update(colors)


def themed_value(attr_name: str, value):
    """A property value as drawn in the current theme (see set_theme_colors)."""
    if _theme_colors and attr_name in _theme_colors and isinstance(value, str) \
            and value.lower() == _SHIPPED_COLORS.get(attr_name):
        return _theme_colors[attr_name]
    return value


class PropertyManager:
    """
    This class provides an API that returns attributes in the iplotlib hierarchy.
    """

    def __init__(self):
        self.default = properties
        self._scale = DisplayScale.instance()

    def get_raw_value(self, obj: any, attr_name: str):
        """Resolve a property without applying the display scale.

        This is the value the user set (or the configured default) and is what
        gets persisted: saving a scaled number would bake the current screen's
        factor into the configuration file.
        """
        value = getattr(obj, attr_name, None)
        if value is not None:
            return value
        if hasattr(obj, 'parent'):
            return self.get_raw_value(obj.parent(), attr_name)
        return self.default.get(attr_name, None)

    def get_value(self, obj: any, attr_name: str):
        """Resolve a property as it should be rendered on the current display.

        Size-like properties (see
        :data:`~iplotlib.core.display.SCALED_PROPERTIES`) come back multiplied
        by the UI scale factor, so a canvas configured for FullHD stays legible
        on a 4K panel without every call site knowing about DPI. Colours left
        at their shipped default come back in those of the theme (see
        set_theme_colors).
        """
        return self._scale.apply(attr_name, themed_value(attr_name, self.get_raw_value(obj, attr_name)))
