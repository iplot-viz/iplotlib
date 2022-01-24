#!/bin/bash
if [ -d ${idv_venv_dir} ]
then
	echo "Make sure you source this file ${BASH_SOURCE[0]}"

	source ${iplotlib_src_dir}/environ.sh foss dev

	echo "pip = `which pip`"
	echo "Upgrading pip.."
	pip install --upgrade pip wheel python-dateutil pytz pyparsing
	echo "pip = `which pip`"

	echo "Installing dependencies.."
	pip install sseclient-py pytest psutil requests
	echo "pytest = `which pytest`"

	deactivate && source ${idv_venv_dir}/bin/activate
	echo "pytest = `which pytest`"
else
	echo "A recognized virtual environment does not exist"
fi
