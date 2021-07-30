#!/bin/bash

# Clean slate
module purge

# Data Access library
module load DataAccess/0.0.0-foss-2020b # brings in [proc/0.0.0, logging2/0.0.0, uda-ccs/2.1.2]-foss-2020b

# Graphics backend requirements
module load matplotlib/3.3.3-foss-2020b

# Graphical User Interface backends
module load QtPy/1.9.0-GCCcore-10.2.0
