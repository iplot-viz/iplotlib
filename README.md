# ITER plotting library

A high-level abstract plotting library.

| Graphics   |           GUI           |
|------------|:-----------------------:|
| matplotlib | PyQt5, PySide2, PySide6 |
| gnuplot    |          PyQt5          |
| vtk        |     PyQt5, PySide2      |

## Requirements

1. **python <= 3.11**
2. **Dependencies**: Managed
   via [pyproject.toml](https://github.com/iplot-viz/iplotlib/blob/develop/pyproject.toml).

## Installation

Install the package from PyPi:

  ```bash
  pip install iplotlib
  ```

## Usage Example

  ```bash
   from iplotlib.core import Canvas, PlotXY, SimpleSignal
   from iplotlib.qt.gui.iplotQtStandaloneCanvas import QStandaloneCanvas
   import numpy as np
   
   x = np.linspace(-1, 1, 1000)
   y = (1 - x ** 2) + 100 * (2 - x ** 2) ** 2
   
   s = SimpleSignal(label='signal_1', x_data=x, y_data=y)
   
   c = Canvas(rows=3, title='My Iplotlib Canvas')
   
   p = PlotXY()
   p.add_signal(s)
   c.add_plot(p)
   
   app = QStandaloneCanvas('matplotlib', use_toolbar=True)
   app.prepare()
   app.add_canvas(c)
   app.run()
  ```

## Run examples

```bash
iplotlib-qt-canvas -t
```

Click on canvas menu to switch between examples.


## Contributing

1. Fork it!
2. Create your feature branch: ```git checkout -b my-new-feature ```
3. Commit your changes: ```git commit -am 'Add some feature' ```
4. Push to the branch:```git push origin my-new-feature ```
5. Submit a pull request