.. _adding_new_plot_type:

How to add a new plot type
===========================================

This document describes the standard procedure for implementing and integrating a new plot type in MINT. It is intended
for developers who need to extend the visualization system while respecting the existing modular architecture.


Involved Classes and Interfaces
-------
When adding a new plot type, the following classes and components are involved:

    - MTMainWindow

    - MTSignalConfigurator

    - MTSignalsModel

    - Plot

    - Canvas

    - Preferences system

    - Graphics backend

The new plot must respect the public interfaces defined by these classes.


Requirements and Conventions
----------------------------
Before implementing a new plot, the following conventions must be met:

    - The plot must inherit from the corresponding base class.

    - The class name must follow the ``Plot<Name>`` naming convention.

    - The new class must be located in the plots module.

    - The signal type supported by the new plot must be defined. If the plot requires a signal type other than ``SignalXY`` or
      ``SignalContour``, the new signal type must also be implemented.

.. note:: In addition to the technical requirements, design and functional aspects must also be considered.

    - A plot may consist of a single element, such as ``PlotXY``, or be composed of multiple elements. A representative case
      is ``PlotXYWithSlider``, which combines a ``PlotXY`` with a slider.

    - Multiple signals can be drawn within the same plot:

      - ``PlotXY``: supports multiple signals.
      - ``PlotContour``: does not support multiple signals.

    - Plot stacking is supported. Currently, only ``PlotXY`` plots can be stacked.


Creating a New Plot Type
-----------------------

Step 1: Create the Plot Class
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Create a new class inheriting from the base plot class.

Minimal example:

.. code-block:: python

    @dataclass
    class PlotExample(Plot):
        pass

        def __post_init__(self):
            super().__post_init__()

        def reset_preferences(self):
            super().reset_preferences()

        def merge(self, old_plot: dict):
            super().merge(old_plot)


Step 2: System Registration
^^^^^^^^^^^^^^^^^^^^^^^^^^

The new plot must be registered so that the system can instantiate it dynamically.

To do this, it must be associated with the following enum defined in the ``MTMainWindow`` file.

.. code-block:: python

    self.plot_classes = {"PlotXY": PlotXY,
                        "PlotContour": PlotContour,
                        "PlotXYWithSlider": PlotXYWithSlider,
                        "PlotExample": PlotExample}


Step 3: Canvas Integration
^^^^^^^^^^^^^^^^^^^^^^^^^

The plot must be able to:

    - Be added to and removed from the ``Canvas``.

    - Respond to global events (resize, refresh, clear).

    - Update correctly when the underlying data changes.

The ``Canvas`` must not require specific modifications to support the new plot.



Preferences and Properties Management
-------------------------------------

Each plot may define its own properties. These properties must:

    - Be explicitly declared in the plot class.

    - Be integrated with the hierarchical preferences system.

    - Respect propagation from higher levels.

Example definition using ``@dataclass``:

.. code-block:: python

    @dataclass
    class PlotExample(Plot):
        signals: Dict[int, List[SignalXY]] = None
        plot_title: str = 'PlotExample Title'

Any property meant to be propagated must be defined within its corresponding structure. To allow these properties to be modified from
the graphical user interface, the associated Form must be created.

Example of a properties form for ``PlotContour``:

.. code-block:: python

    class PlotContourForm(IplotPreferencesForm):
    """
    Map the properties of a Plot object to the widgets in a GUI form.
    """

    def __init__(self, parent: typing.Optional[QWidget] = None, f: Qt.WindowFlags = Qt.Widget):
        prototype = [
            {"label": "Title", "property": "title", "widget": self.create_lineedit()},
            {"label": "Grid", "property": "grid", "widget": self.create_checkbox()},
            {"label": "Legend format", "property": "legend_format",
             "widget": self.default_plot_contour_legend_format_widget()},
            {"label": "Font size", "property": "font_size", "widget": self.default_fontsize_widget()},
            {"label": "Font color", "property": "font_color", "widget": ColorPicker("font_color")},
            {"label": "Background color", "property": "background_color", "widget": ColorPicker("background_color")},
            {"label": "Contour Levels", "property": "contour_levels", "widget": self.default_contour_levels_widget()},
            {"label": "Contour Filled", "property": "contour_filled", "widget": self.create_checkbox()},
            {"label": "Equivalent Units", "property": "equivalent_units", "widget": self.create_checkbox()}]

        super().__init__(fields=prototype, label="A plot", parent=parent, f=f)


Once the Form has been created, it must be added to the ``_forms`` attribute of the
``IplotQtPreferencesWindow`` class in order to display the new form correctly.

.. code-block:: python

        self._forms = {
            Canvas: CanvasForm(self),
            PlotXY: PlotXYForm(self),
            PlotXYWithSlider: PlotXYForm(self),
            PlotContour: PlotContourForm(self),
            PlotExample: PlotExampleForm(self),  # New
            LinearAxis: AxisForm(self),
            SignalXY: SignalXYForm(self),
            SignalContour: SignalContourForm(self),
            type(None): QPushButton("Select item", parent=self)
        }



Interaction and Event Handling
------------------------------
The new plot must clearly define:

    - Which events it supports (zoom, pan, focus, add marker).

    - How it responds to user interactions.

    - How it notifies changes to the system.

UI-specific logic must not be implemented outside the plot’s responsibilities.


Graphics Backend
----------------
Currently, MINT supports the following graphics backends:

    - matplotlib

    - PyQtGraph

Therefore:

    - The plotting layer should not depend on backend-specific implementations.

    - Backend-specific dependencies must be properly isolated.

    - Design patterns should be followed.

Any backend-specific limitations must be explicitly documented.

Simplified example of a ``PlotXY`` implementation for different backends:

- Common abstraction in the ``impl_base`` file:

.. code-block:: python

    def do_impl_line_plot_xy(self, signal: SignalXY, impl_plot: Any, plot: PlotXY, cache_item, x_data, y_data):

        if x_data.ndim == 1 and y_data.ndim == 1:
            plot_lines = self.create_plot_lines_1D(impl_plot, x_data, y_data, style)
            self._update_marker_by_point_count(plot_lines[0], x_data, style)

        elif x_data.ndim == 1 and y_data.ndim == 2:
            plot_lines = self.create_plot_lines_2D(draw_fn, signal, x_data, y_data, style)

    signal.lines = plot_lines

    return plot_lines

- Matplotlib implementation

.. code-block:: python

    def create_plot_lines_1D(self, impl_plot: MPLAxes, x_data, y_data, style):
        return impl_plot.plot(x_data, y_data, **style)  # type: List[Line2D]

- PyQtGraph implementation

.. code-block:: python

    def create_plot_lines_1D(self, impl_plot: PlotItem, x_data, y_data, style):
        return [impl_plot.plot(x=x_data, y=y_data, **style)]  # type: List[PlotDataItem]


Testing the New Plot
-------------------
Every new plot must include at least minimal testing. Recommended test types include:

    - Unit tests for the plot class.

    - Integration tests with the ``Canvas``.

    - Tests using large, empty, or invalid datasets.

Tests must verify that the new plot does not break global functionality or introduce regressions.