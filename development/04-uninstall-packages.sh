#!/bin/bash
if [ -d ${idv_venv_dir} ]
then
	echo "Uninstalling ITER Data Visualization components.."
	pip uninstall iplotlogging iplotprocessing iplotlib iplotdataaccess mint
else
	echo "A recognized virtual environment does not exist"
fi

