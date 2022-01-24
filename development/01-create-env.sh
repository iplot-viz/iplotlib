#!/bin/bash
# This script creates or loads an existing python virtual environment.

venv_name="$1"
if [ "${venv_name}" == "" ]
then
	echo "First argument must be the name of virtual environment"
else
	echo "Make sure you source this file ${BASH_SOURCE[0]}"
	base_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" > /dev/null && pwd )"

	module purge &&
	module load Python/3.8.6-GCCcore-10.2.0 &&

	abi_tag=`python -c 'import sys;print(f"{sys.implementation.name}-{sys.implementation.version.major}{sys.implementation.version.minor}{sys.implementation.version.micro}")'`

	venv_full_name="${venv_name}-${abi_tag}"
	export idv_venv_dir="${base_dir}/${venv_full_name}"

	if [ -d ${idv_venv_dir} ]
	then
		echo "Reusing virtual env at ${idv_venv_dir}"
	else
		echo "Setting up a virtual environment at ${idv_venv_dir}"
		mkdir ${idv_venv_dir}
		python -m venv ${idv_venv_dir}
	fi
fi
