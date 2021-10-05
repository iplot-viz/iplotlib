
.. _testing:

Testing
-------

Run the unit tests to verify your installation is stable.

.. code-block:: bash

    $ pytest iplotlib

You should see the following output.

.. code-block:: bash

    ========================================================= test session starts ==========================================================
    platform linux -- Python 3.8.6, pytest-6.2.5, py-1.10.0, pluggy-1.0.0
    rootdir: /home/ITER/panchuj/Downloads/work/iterplotlib/iplotlib
    collected 33 items                                                                                                                     

    iplotlib/core/tests/test_01_property_manager.py ...                                                                              [  9%]
    iplotlib/core/tests/test_02_signal.py ..........                                                                                 [ 39%]
    iplotlib/impl/vtk/tests/test_01_null_refresh.py .                                                                                [ 42%]
    iplotlib/impl/vtk/tests/test_02_canvas_sizing.py .                                                                               [ 45%]
    iplotlib/impl/vtk/tests/test_03_row_inversion_simple.py .                                                                        [ 48%]
    iplotlib/impl/vtk/tests/test_04_row_inversion_complex.py .                                                                       [ 51%]
    iplotlib/impl/vtk/tests/test_05_canvas_simple.py ..                                                                              [ 57%]
    iplotlib/impl/vtk/tests/test_06_canvas_complex.py ..                                                                             [ 63%]
    iplotlib/impl/vtk/tests/test_07_signal_properties.py ..                                                                          [ 69%]
    iplotlib/impl/vtk/tests/test_08_datetime_tics_simple.py ..                                                                       [ 75%]
    iplotlib/impl/vtk/tests/test_09_datetime_tics_complex.py ..                                                                      [ 81%]
    iplotlib/impl/vtk/tests/test_10_crosshair_interactive.py ..                                                                      [ 87%]
    iplotlib/impl/vtk/tests/test_11_mouse_pan_interactive.py ..                                                                      [ 93%]
    iplotlib/impl/vtk/tests/test_12_mouse_zoom_interactive.py ..                                                                     [100%]

    ========================================================= 33 passed in 10.11s ==========================================================