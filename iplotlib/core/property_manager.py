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

config_path = IPLOT_CANVAS_CONFIG if IPLOT_CANVAS_CONFIG else file_name

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
        the preferences forms must show and persist: scaling on the way out and
        then saving the scaled number would bake the current screen's factor
        into the configuration file.
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
        on a 4K panel without every call site knowing about DPI.
        """
        return self._scale.apply(attr_name, self.get_raw_value(obj, attr_name))
