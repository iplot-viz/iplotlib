#!/bin/bash

# 3-fingered-claw 
function yell () 
{ 
  echo "$0: $*" >&2
}

function die () 
{ 
  yell "$*"; exit 1
}

function try () 
{ 
  "$@" || die "cannot $*" 
}


# Default to foss toolchain
if [[ "$1" == "foss" || -z $1 ]];
then
    toolchain=foss
elif [[ "$1" == "intel" ]];
then
    toolchain=intel
fi
echo "Toolchain: $toolchain"

# Clean slate
try module purge

case $toolchain in

  "foss")
    # Other IDV components
    try module load iplotLogging/0.0.0-GCCcore-10.2.0
    try module load iplotProcessing/0.0.0-foss-2020b
    try module load iplotDataAccess/0.0.0-foss-2020b

    # Graphics backend requirements
    try module load matplotlib/3.3.3-foss-2020b
    try module load VTK/20210803-foss-2020b

    # Graphical User Interface backends
    try module load QtPy/1.9.0-GCCcore-10.2.0
    ;;

  "intel")
    # Other IDV components
    try module load iplotLogging/0.0.0-GCCcore-10.2.0
    try module load iplotProcessing/0.0.0-intel-2020b
    try module load iplotDataAccess/0.0.0-intel-2020b

    # Graphics backend requirements
    try module load matplotlib/3.3.3-intel-2020b
    try module load VTK/20210803-intel-2020b

    # Graphical User Interface backends
    try module load QtPy/1.9.0-GCCcore-10.2.0
    ;;
   *)
    echo "Unknown toolchain $toolchain"
    ;;
esac

try module list -t 2>&1
