import json
import os
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


class PropertyManager:
    """
    This class provides an API that returns attributes in the iplotlib hierarchy.
    """

    def __init__(self):
        self.default = properties

    def get_value(self, obj: any, attr_name: str):
        value = getattr(obj, attr_name, None)
        if value is not None:
            return value
        if hasattr(obj, 'parent'):
            return self.get_value(obj.parent(), attr_name)
        return self.default.get(attr_name, None)
