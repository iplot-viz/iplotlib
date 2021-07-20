#!/bin/bash
module purge &&
export VTK_PATH=/home/ITER/panchuj/public/vtk-gcc-10.2.0-Release/lib64
export VTK_PYTHON_PATH=${VTK_PATH}/python3.8/site-packages
export PYTHONPATH=${PYTHONPATH}:${VTK_PYTHON_PATH}:../ &&
export LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:${VTK_PATH} &&
module load UDA-CCS/2.1.2-foss-2020b &&
module load PySide2/5.14.2-GCCcore-10.2.0 &&
module load matplotlib/3.3.3-foss-2020b
