Usage
=====

The example iplotlib scripts are under `iplotlib/examples/*.py`. You can run the examples with

.. code-block:: bash

    $ iplotlib-qt-canvas -t -impl matplotlib

For development/debug purposes, you can enable the profiler with the `-profile` argument like so. It shows top 10
calls ordered by CPU time.

.. code-block:: bash

    $ iplotlib-qt-canvas -t -impl matplotlib -profile
    Fri Jan 21 15:01:23 2022    /home/ITER/panchuj/Downloads/work/iterplotlib/iplotlib/iplotlib/qt/gui/iplotQtStandaloneCanvas.py.profile

    3734494 function calls (3674398 primitive calls) in 15.398 seconds

    Ordered by: internal time
    List reduced from 5207 to 10 due to restriction <10>

    ncalls  tottime  percall  cumtime  percall filename:lineno(function)
        1    3.458    3.458    6.062    6.062 {built-in method exec_}
        5    2.459    0.492    2.459    0.492 {built-in method uda_client_reader._uda_client_reader_python.UdaClientReaderBase_fetchData}
    20790    1.284    0.000    1.284    0.000 {built-in method posix.lstat}
       11    0.811    0.074    0.811    0.074 matplotlibCanvas.py:674(<listcomp>)
     6285    0.710    0.000    0.711    0.000 {built-in method builtins.max}
      177    0.614    0.003    0.616    0.003 {method 'draw_path' of 'matplotlib.backends._backend_agg.RendererAgg' objects}
    26369    0.399    0.000    0.399    0.000 {built-in method numpy.array}
      693    0.319    0.000    0.319    0.000 {method 'set_text' of 'matplotlib.ft2font.FT2Font' objects}
     4008    0.285    0.000    0.285    0.000 {built-in method posix.stat}
        2    0.269    0.134    0.269    0.134 {method 'show' of 'PySide2.QtWidgets.QWidget' objects}


Lets go through the basic steps necessary to get iplotlib to plot something to the screen.

This section will show you how to use the matplotlib graphics backend coupled
with a Qt user interface. For simplicity, it will use the :data:`~iplotlib.qt.gui.iplotQtStandaloneCanvas.QStandaloneCanvas` class.

.. note:: To get rid of the prompts (`>>>`) in the code sections, click on the `>>>` located in the top right corner next to the copy button.

1. Import the iplotlib classes that we shall use.

.. code-block:: python

    >>> from iplotlib.core import Canvas, PlotXY, SimpleSignal
    >>> from iplotlib.qt.gui.iplotQtStandaloneCanvas import QStandaloneCanvas

2. Create some data.

.. code-block:: python

    >>> import numpy as np
    >>> x = np.linspace(-1, 1, 1000)
    >>> y = (1 - x ** 2) + 100 * (2 - x ** 2) ** 2

2. Create the abstract iplotlib objects.

.. code-block:: python

    >>> s = SimpleSignal(label='signal_1', x_data=x, y_data=y)
    >>> c = Canvas(rows=3, title='My Iplotlib Canvas')
    >>> p = PlotXY()
    >>> p.add_signal(s)
    >>> c.add_plot(p)

3. Prepare the standalone iplotlib window

.. code-block:: python

    >>> app = QStandaloneCanvas('matplotlib', use_toolbar=True)
    >>> app.prepare()

3. Add the abstract canvas to our standalone canvas and run it.

.. code-block:: python

    >>> app.add_canvas(c)

.. note:: You can add more canvases to the window by repeating the above step.

4. Launch the application and run the event loop for interactive features.

.. code-block:: python

    >>> app.exec_()

Here is the full script.

.. code-block:: python

    >>> from iplotlib.core import Canvas, PlotXY, SimpleSignal
    >>> from iplotlib.qt.gui.iplotQtStandaloneCanvas import QStandaloneCanvas
    >>> import numpy as np
    >>> x = np.linspace(-1, 1, 1000)
    >>> y = (1 - x ** 2) + 100 * (2 - x ** 2) ** 2
    >>> s = SimpleSignal(label='signal_1', x_data=x, y_data=y)
    >>> c = Canvas(rows=3, title='My Iplotlib Canvas')
    >>> p = PlotXY()
    >>> p.add_signal(s)
    >>> c.add_plot(p)
    >>> app = QStandaloneCanvas('matplotlib', use_toolbar=True)
    >>> app.prepare()
    >>> app.add_canvas(c)
    >>> app.exec_()

.. note:: After you've pasted the script, hit Return key to execute.
.. note:: You can add more canvases to the `app` from the interpreter after closing the window.


If you wish to build full-sized Qt applications with iplotlib, see :data:`~iplotlib.qt` module.
