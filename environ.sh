#!/bin/bash
module purge &&
export VTK_PATH=/home/ITER/panchuj/public/vtk-gcc-10.2.0-Release/lib64
export VTK_PYTHON_PATH=${VTK_PATH}/python3.8/site-packages
export PYTHONPATH=${PYTHONPATH}:${VTK_PYTHON_PATH}:../ &&
export LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:${VTK_PATH} &&
module load UDA-CCS &&
module load PySide2 &&
module load PyQt5 &&
module load matplotlib
