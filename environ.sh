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
try module load PySide6/6.6.2-GCCcore-13.2.0
# For test coverage:
try module load coverage/7.4.4-GCCcore-13.2.0

case $config in
    "prod")
      try module load iplotLogging
      ;;
    "dev" )
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
          try module load m-uda-client/7.2.0-gfbf-2023b #module load UDA-CCS/6.3-foss-2020b
          ;;
        "prod")
          try module load iplotProcessing
          try module load iplotDataAccess
          ;;
        * ) 
          echo "Unknown configuration $config"
          ;;
    esac

    # Graphics backend requirements
    try module load matplotlib/3.8.2-gfbf-2023b
    try module load VTK/9.3.0-foss-2023b
    ;;

  "intel")
    # Other IDV components
    case $config in
        "dev")
          try module load m-uda-client/7.2.0-gfbf-2023b #UDA-CCS/6.3-intel-2020b
          ;;
        "prod")
          try module load iplotProcessing
          try module load iplotDataAccess
          ;;
        * ) 
          echo "Unknown configuration $config"
          ;;
    esac

    # Graphics backend requirements
    try module load matplotlib/3.8.2-iimkl-2023b
    try module load VTK/9.3.0-intel-2023b
    ;;
   *)
    echo "Unknown toolchain $toolchain"
    ;;
esac

export HOME=$PWD
echo "HOME was set to $HOME"
