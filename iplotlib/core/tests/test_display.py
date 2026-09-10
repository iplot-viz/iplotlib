"""
Tests for the UI scale resolution.

These cover the decision table rather than the rendering: the point is that a
given set of screen metrics always yields the same factor, including on the
remote-session paths that cannot be reproduced on a build machine.
"""

import unittest

from iplotlib.core.display import (DATA_COST_PROPERTIES,
                                   DEFAULT_SCALED_PROPERTIES, DisplayScale,
                                   MODE_FIXED, MODE_OFF, ScaledPixels,
                                   parse_scale_setting,
                                   parse_scaled_properties, quantize,
                                   remote_session_markers, scale_from_metrics)


def metrics(**kwargs):
    base = dict(available=True, device_pixel_ratio=1.0, logical_dpi=96.0,
                physical_dpi=96.0, width_px=1920, height_px=1080,
                remote_markers=[])
    base.update(kwargs)
    return base


class ScaleFromMetricsTest(unittest.TestCase):

    def test_fullhd_local_is_unscaled(self):
        factor, _ = scale_from_metrics(metrics(physical_dpi=94.0))
        self.assertEqual(factor, 1.0)

    def test_unscaled_4k_scales_up(self):
        factor, why = scale_from_metrics(metrics(physical_dpi=163.0, width_px=3840))
        self.assertGreater(factor, 1.0)
        self.assertIn('physical DPI', why)

    def test_session_scaling_is_not_double_applied(self):
        # The compositor already scaled every logical pixel and point size, so
        # applying our own factor on top would double the sizes.
        factor, why = scale_from_metrics(
            metrics(device_pixel_ratio=2.0, logical_dpi=192.0,
                    physical_dpi=163.0, width_px=3840))
        self.assertEqual(factor, 1.0)
        self.assertIn('devicePixelRatio', why)

    def test_logical_dpi_wins_over_physical(self):
        # Xft.dpi is an explicit user choice; honour it rather than the panel.
        factor, why = scale_from_metrics(
            metrics(logical_dpi=144.0, physical_dpi=163.0, width_px=3840))
        self.assertEqual(factor, 1.5)
        self.assertIn('logical DPI', why)

    def test_remote_session_ignores_bogus_physical_dpi(self):
        # NX/Xvfb commonly report a 1000x1000 mm screen, i.e. ~25 DPI, which
        # would otherwise clamp the factor to the minimum on a 4K session.
        factor, why = scale_from_metrics(
            metrics(physical_dpi=25.4, width_px=3840,
                    remote_markers=['NXSESSIONID']))
        self.assertEqual(factor, 2.0)
        self.assertIn('remote session', why)

    def test_remote_fullhd_stays_unscaled(self):
        factor, _ = scale_from_metrics(
            metrics(width_px=1920, remote_markers=['SSH_CONNECTION']))
        self.assertEqual(factor, 1.0)

    def test_headless_is_unscaled_and_not_cached(self):
        factor, why = scale_from_metrics({'available': False})
        self.assertEqual(factor, 1.0)
        self.assertIn('no screen', why)

    def test_factor_is_clamped(self):
        factor, _ = scale_from_metrics(
            metrics(physical_dpi=600.0, width_px=7680), max_scale=2.0)
        self.assertEqual(factor, 2.0)

    def test_reference_dpi_is_configurable(self):
        factor, _ = scale_from_metrics(
            metrics(physical_dpi=192.0, width_px=3840), reference_dpi=192.0)
        self.assertEqual(factor, 1.0)


class SettingParseTest(unittest.TestCase):

    def test_known_settings(self):
        self.assertEqual(parse_scale_setting('auto')[0], 'auto')
        self.assertEqual(parse_scale_setting('off')[0], MODE_OFF)
        self.assertEqual(parse_scale_setting('1.5'), (MODE_FIXED, 1.5))
        self.assertEqual(parse_scale_setting(2), (MODE_FIXED, 2.0))

    def test_unparseable_setting_falls_back_to_auto(self):
        # A stale QSettings value must never stop the application starting.
        self.assertEqual(parse_scale_setting('mostly')[0], 'auto')

    def test_quantize(self):
        self.assertEqual(quantize(1.6979), 1.75)
        self.assertEqual(quantize(1.1), 1.0)

    def test_scaled_property_parsing(self):
        self.assertEqual(parse_scaled_properties(None), DEFAULT_SCALED_PROPERTIES)
        self.assertEqual(parse_scaled_properties('default'), DEFAULT_SCALED_PROPERTIES)
        self.assertEqual(parse_scaled_properties('font_size'), frozenset({'font_size'}))
        self.assertEqual(parse_scaled_properties(['font_size', 'line_size']),
                         frozenset({'font_size', 'line_size'}))

    def test_unscalable_property_names_are_dropped(self):
        # A typo must not silently scale nothing, and an arbitrary property must
        # not be scaled just because it appears in a config file.
        self.assertEqual(parse_scaled_properties('font_sizes,tick_number'), frozenset())
        self.assertEqual(parse_scaled_properties('font_size,nonsense'),
                         frozenset({'font_size'}))

    def test_remote_markers_detect_forwarded_display(self):
        self.assertIn('DISPLAY', remote_session_markers({'DISPLAY': 'host:10.0'}))
        self.assertEqual(remote_session_markers({'DISPLAY': ':0'}), [])


class ApplyTest(unittest.TestCase):

    def setUp(self):
        DisplayScale.reset()
        self.scale = DisplayScale.instance()

    def tearDown(self):
        DisplayScale.reset()

    def test_only_size_properties_are_scaled(self):
        self.scale.configure(mode=MODE_FIXED, value=2.0, force=True)
        self.assertEqual(self.scale.apply('font_size', 8), 16)
        self.assertEqual(self.scale.apply('crosshair_line_width', 1), 2)
        self.assertEqual(self.scale.apply('tick_number', 7), 7)
        self.assertEqual(self.scale.apply('marker', 'o'), 'o')
        self.assertIs(self.scale.apply('grid', True), True)
        self.assertIsNone(self.scale.apply('font_size', None))

    def test_per_sample_sizes_are_not_scaled_by_default(self):
        # Regression: scaling line_size from 1 to 2 puts every default plot on
        # Qt's slow stroked-line path, and with a few hundred thousand points
        # the pyqtgraph backend becomes unresponsive. Legibility on a 4K screen
        # is a font problem; line width is not worth that cliff by default.
        self.scale.configure(mode=MODE_FIXED, value=2.0, force=True)
        self.assertEqual(self.scale.apply('line_size', 1), 1)
        self.assertEqual(self.scale.apply('marker_size', 1), 1)
        self.assertFalse(DATA_COST_PROPERTIES & DEFAULT_SCALED_PROPERTIES)

    def test_per_sample_sizes_can_be_opted_into(self):
        self.scale.configure(mode=MODE_FIXED, value=2.0,
                             scaled_properties='font_size,line_size', force=True)
        self.assertEqual(self.scale.apply('line_size', 1), 2)
        self.assertEqual(self.scale.apply('font_size', 8), 16)
        # Not named, so no longer scaled.
        self.assertEqual(self.scale.apply('crosshair_line_width', 1), 1)

    def test_empty_property_list_disables_scaling_of_everything(self):
        self.scale.configure(mode=MODE_FIXED, value=2.0,
                             scaled_properties='', force=True)
        self.assertEqual(self.scale.apply('font_size', 8), 8)

    def test_int_sizes_never_round_to_zero(self):
        self.scale.configure(mode=MODE_FIXED, value=1.0, force=True)
        self.assertEqual(self.scale.apply('line_size', 1), 1)

    def test_off_mode_is_identity(self):
        self.scale.configure(mode=MODE_OFF, force=True)
        self.assertEqual(self.scale.apply('font_size', 8), 8)

    def test_scaled_pixels_is_lazy(self):
        constant = ScaledPixels(110)
        self.scale.configure(mode=MODE_FIXED, value=1.0, force=True)
        self.assertEqual(constant.px(), 110)
        self.scale.configure(mode=MODE_FIXED, value=2.0, force=True)
        self.assertEqual(constant.px(), 220)


if __name__ == '__main__':
    unittest.main()
