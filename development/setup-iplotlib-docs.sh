#!/bin/bash
base_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" > /dev/null && pwd )"
source ${base_dir}/setup-sdcc-dev.sh

if [ "${iplotlib_src_dir}" != "" ] && [ -d ${iplotlib_src_dir} ] && [ -f ${iplotlib_src_dir}/setup.py ]
then
	pushd ${iplotlib_src_dir}/docs
	pip install -r requirements-docs.txt
	make clean && make html
	# TODO: do something with the docs build. upload to a site.
	popd
	idv_env_deactivate
else
	echo "Cannot build docs. No iplotlib sources were found."
fi