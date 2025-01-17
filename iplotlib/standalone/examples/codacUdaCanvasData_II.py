"""
Demonstrate usage of iplotlib by plotting data obtained from a CODAC-UDA server, including setting canvas parameters.
"""

import os
from iplotlib.core import Canvas
import json


def get_canvas():
    module_dir = os.path.dirname(__file__)
    json_file_path = os.path.join(module_dir + '_json', 'simple_data.json')

    with open(json_file_path, 'r') as f:
        data = json.load(f)
        canvas_dict = data.get('main_canvas')
        c = Canvas.from_dict(canvas_dict)
        # Set title
        c.title = os.path.basename(__file__).replace('.py', '')
        return c
