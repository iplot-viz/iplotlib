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

# Default to production config. (Will use idv components from system instead of sources.)
if [[ "$2" == "prod" || -z $2 ]];
then
    config=prod
elif [[ "$2" == "dev" ]];
then
    config=dev
fi
echo "Configuration: $config"

# Graphical User Interface backend
try module load PySide6/6.2.3-GCCcore-10.2.0
# Testing/Coverage requirements
try module load coverage/5.5-GCCcore-10.2.0 

case $config in
    "prod")
      try module load iplotLogging/0.3.0-GCCcore-10.2.0
      ;;
    "dev" )
      try module load cachetools/4.2.1-GCCcore-10.2.0
      ;;
    * )
      echo "Unknown configuration $config"
      ;;
esac

case $toolchain in
  "foss")
    # Other IDV components
    case $config in
        "dev")
          try module load UDA-CCS/6.3-foss-2020b
          ;;
        "prod")
          try module load iplotProcessing/0.5.0-foss-2020b
          try module load iplotDataAccess/0.5.0-foss-2020b
          ;;
        * ) 
          echo "Unknown configuration $config"
          ;;
    esac

    # Graphics backend requirements
    try module load matplotlib/3.5.1-foss-2020b
    try module load VTK/9.1.0-foss-2020b
    ;;

  "intel")
    # Other IDV components
    case $config in
        "dev")
          try module load UDA-CCS/6.3-intel-2020b
          ;;
        "prod")
          try module load iplotProcessing/0.5.0-intel-2020b
          try module load iplotDataAccess/0.5.0-intel-2020b
          ;;
        * ) 
          echo "Unknown configuration $config"
          ;;
    esac

    # Graphics backend requirements
    try module load matplotlib/3.5.1-intel-2020b
    try module load VTK/9.1.0-intel-2020b
    ;;
   *)
    echo "Unknown toolchain $toolchain"
    ;;
esac

export HOME=$PWD
echo "HOME was set to $HOME"