
# Welcome to the VTK backend for ITER Plotting Library (iplotlib)

## Dev notes:

  + The core linkage to VTK is implemented under `iplotlib/impl/vtk/vtkCanvas.py`
    + For simplicity and with a goal to keep the API methods clean, `VTKCanvas` is derived from the abstract iplotlib `Canvas`.
    + `VTKCanvas` will hold reference to a `vtkChartMatrix` instance.
    + `VTKCanvas` is responsible for translating the abstract iplotlib `Canvas->[Plot->[Signal,..],....]` data structure into `vtkChartMatrix->[(vtkChart|vtkChartMatrix)->[vtkPlot,..],....]`
    + The most troublesome part is the inverted row numbering.
    + See `VTKCanvas::get_internal_row_id` for implementation details.
    + In order to update the layout, the exposed API is of the form `refresh_[construct]`. 
    + Here *construct* could mean one of *plot*, *signal*. 
    + There is another method named simply `refresh` and not `refresh_canvas` for obvious reasons. This method calls the `refresh_[plot/signal]` variants by traversing the Canvas::plots data member.
    + For the canvas title, use a vtkPythonItem and paint the string. Compute string bounds with VTK and set 
      the bounding rectangle for the title.
      + **Debugging tip**: Set `self._py_title_item.debug_rect=True` to draw a light yellow rectangle for the title context area.
    + Resize event is received from QtVTKCanvas.
      + Resize title's rectangular area.
      + Resize chart matrix rectangular area.
    + DateTime ticker logic is covered in [slides](https://confluence.iter.org/display/PMA/Meeting%2C+Notes+and+Actions?preview=/316087944/316087965/Handling%20of%2064-bit%20data.pptx)
  + The core linkage to VTK+Qt is implemented under `iplotlib/impl/vtk/qt/qtVTKCanvas.py`
    + Again, for simplicity and clean API, it subclasses the abstract iplotlib `QtPlotCanvas`
    + VTK provides Qt embed capabilities via `QVTKRenderWindowInteractor`.
    + `QtVTKCanvas` will simply place that widget in a vertical layout and maintain
        a `VTKCanvas` member. It's view is linked to the widget's renderwindow.
    + `set_canvas` is implemented to forward all base-class attributes to the internal `VTKCanvas` instance.
  + Testing is similar to VTK's testing.
    + `impl/vtk/utils.py` has implemented lots of methods two help compare to images on a pixel-by-pixel basis. This is done with `vtkImageDifference`
    + There is also a `screenshot` method to capture current contents of the render window and save to a file. (`*.png`) with a timestamp if no filename is specified.
    + The images under `impl/vtk/baseline/` are what we want and those are the valid images.
    + `regression_test` compares the screenshot of the test script's render-window against the baseline image corresponding to the test script.

## Install

This implementation uses the latest development features of VTK. Two specific pull-requests to mainline VTK are necessary.
    
+ [8053](https://gitlab.kitware.com/vtk/vtk/-/merge_requests/8053): Merged
+ [8228](https://gitlab.kitware.com/vtk/vtk/-/merge_requests/8228): Merged

Hence it is necessary to pull in the master branch and build VTK from source for now. I've built VTK in my home directory. 

Here is my environ.sh
```bash
#!/bin/bash

# Clean slate
module purge

# Data Access library
#module load DataAccess/0.0.0-foss-2020b # brings in [proc/0.0.0, logging2/0.0.0, uda-ccs/2.1.2]-foss-2020b

# Graphics backend requirements
module load matplotlib/3.3.3-foss-2020b
# module load VTK/9.0.1-foss-2020b
export VTKPYTHONPATH=${HOME}/builds/vtk/dev/gcc-10.2.0/debug/lib64/python3.8/site-packages
export PYTHONPATH=${PYTHONPATH}:${VTKPYTHONPATH}

# Graphical User Interface backends
module load QtPy/1.9.0-GCCcore-10.2.0
```

