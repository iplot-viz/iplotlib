import os
import tempfile
import unittest

import numpy as np
from iplotDataAccess.dataAccess import DataAccess
from iplotlib.impl.matplotlib.matplotlibCanvas import MatplotlibParser
from iplotlib.impl.matplotlib.tests.QAppOffscreenTestAdapter import QAppOffscreenTestAdapter
from iplotlib.interface import AccessHelper

ROOT = os.path.dirname(__file__)
data_dir = os.path.join(ROOT, 'csv', 'ITER')

dscfg_csv = """
{
    "csv": {
        "path": "%s",
        "type": "CSV"
    }
}
"""


class MatplotlibTesting(QAppOffscreenTestAdapter):
    def setUp(self) -> None:
        super().setUp()

        self.da = DataAccess()
        self.ds = "csv"

        # Use forward slashes for JSON compatibility on all platforms
        data_dir_escaped = data_dir.replace('\\', '/')
        dscfg = dscfg_csv % data_dir_escaped

        # Create temp file - on Windows we need to close it before reading
        self.temp_config_path = tempfile.mktemp(suffix='.cfg')
        with open(self.temp_config_path, 'w') as f:
            f.write(dscfg)

        os.environ.update({'IPLOT_SOURCES_CONFIG': os.path.abspath(self.temp_config_path)})
        if self.da.load_config(self.temp_config_path):
            AccessHelper.da = self.da

    def tearDown(self) -> None:
        # Clean up temp file
        if hasattr(self, 'temp_config_path'):
            try:
                os.unlink(self.temp_config_path)
            except OSError:
                pass
        super().tearDown()

    # --------------------------
    #           TESTS
    # --------------------------

    def test_01_null_refresh(self):
        self.mpl_parser = MatplotlibParser()
        self.mpl_parser.process_ipl_canvas(None)

        self.assertIsNone(self.mpl_parser.canvas)

    def test_CSVAccessByPulse(self) -> None:
        test_cases = [
            {
                "varname": "MAG-MCTB-F1:VAR1",
                "pulse": "ITER:MCTB-TEST/111",
                "expected_x_shape": (11,),
                "expected_y_shape": (11,),
                "expected_x_values": [-5.0, -4.0, -3.0, 0.0, 1.0, 1.1, 1.5, 2.0, 2.5, 3.0, 3.5],
                "expected_y_values": [0, 1, 2, 10, 11, 12, 12, 12, 12, 14, 0]
            },
            {
                "varname": "MAG-MCTB-F1:VAR2",
                "pulse": "ITER:MCTB-TEST/111",
                "expected_x_shape": (11,),
                "expected_y_shape": (11,),
                "expected_x_values": [-5.0, -4.0, -3.0, 0.0, 1.0, 1.1, 1.5, 2.0, 2.5, 3.0, 3.5],
                "expected_y_values": [1, 2, 3, 11, 12, 13, 13, 13, 13, 15, 0],
            },
        ]

        for test_case in test_cases:
            varname = test_case["varname"]
            pulse = test_case["pulse"]
            expected_x_shape = test_case["expected_x_shape"]
            expected_y_shape = test_case["expected_y_shape"]

            dobj = self.da.get_data(self.ds, varname=varname, pulse=pulse)

            self.assertEqual(np.shape(dobj.xdata), expected_x_shape)
            self.assertEqual(np.shape(dobj.ydata), expected_y_shape)
            self.assertIsInstance(dobj.xdata, (np.ndarray, list))
            self.assertIsInstance(dobj.ydata, (np.ndarray, list))

    def test_CSVAccessByPulseWithTime(self) -> None:
        test_cases = [
            {
                "varname": "MAG-MCTB-F1:VAR1",
                "pulse": "ITER:MCTB-TEST/111",
                "tsS": -3.0,
                "tsE": 3.0,
                "expected_x_shape": (8,),
                "expected_y_shape": (8,),
            },
            {
                "varname": "MAG-MCTB-F1:VAR2",
                "pulse": "ITER:MCTB-TEST/111",
                "tsS": 0.0,
                "tsE": 2.0,
                "expected_x_shape": (5,),
                "expected_y_shape": (5,),
            }
        ]

        for test_case in test_cases:
            varname = test_case["varname"]
            pulse = test_case["pulse"]
            tsS = test_case["tsS"]
            tsE = test_case["tsE"]
            expected_x_shape = test_case["expected_x_shape"]
            expected_y_shape = test_case["expected_y_shape"]

            dobj = self.da.get_data(self.ds, varname=varname, pulse=pulse, tsS=tsS, tsE=tsE)

            self.assertEqual(np.shape(dobj.xdata), expected_x_shape)
            self.assertEqual(np.shape(dobj.ydata), expected_y_shape)
            self.assertIsInstance(dobj.xdata, (np.ndarray, list))
            self.assertIsInstance(dobj.ydata, (np.ndarray, list))


if __name__ == '__main__':
    unittest.main()
