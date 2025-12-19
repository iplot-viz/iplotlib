"""
Demonstrate usage of iplotlib by plotting data obtained from a CODAC-UDA server, including setting canvas parameters.
"""

import os
import tempfile
import json
import weakref

from iplotDataAccess.dataAccess import DataAccess
from iplotlib.core import Canvas
from iplotlib.interface import AccessHelper

dscfg = """{
    "codacuda": {
        "type": "CODAC_UDA",
        "host": "io-ls-udasrv1.iter.org",
        "port": 3090,
        "rturl": "http://io-ls-udaweb1.iter.org/dashboard/backend/sse",
        "rtheaders": "REMOTE_USER:$USERNAME,User-Agent:python_client",
        "rtauth": null,
        "default": true
    }
}"""


def get_canvas():
    da = DataAccess()

    with tempfile.NamedTemporaryFile(mode='w+') as fp:
        fp.write(dscfg)
        fp.seek(0)
        os.environ.update({'IPLOT_SOURCES_CONFIG': os.path.abspath(fp.name)})
        if da.load_config(fp.name):
            AccessHelper.da = da

            module_dir = os.path.dirname(__file__)
            json_file_path = os.path.join(module_dir + '_json', 'detail_data.json')

            with open(json_file_path, 'r') as f:
                data = json.load(f)
                canvas_dict = data.get('main_canvas')
                c = Canvas.from_dict(canvas_dict)
                # Set title
                c.title = os.path.basename(__file__).replace('.py', '')
                for col in c.plots:
                    for plot in col:
                        if plot:
                            plot.parent = weakref.ref(c)
                            for signals in plot.signals.values():
                                for signal in signals:
                                    signal.parent = weakref.ref(plot)

                return c
