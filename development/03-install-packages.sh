#!/bin/bash
if [ -d ${idv_venv_dir} ]
then
	echo "Installing ITER Data Visualization components with args $@"
	[ -d ${iplotlib_up_dir}/iplotlogging ] && pip install $@ ${iplotlib_up_dir}/iplotlogging/
	[ -d ${iplotlib_up_dir}/iplotprocessing ] && pip install $@ ${iplotlib_up_dir}/iplotprocessing/
	[ -d ${iplotlib_up_dir}/iplotdataaccess ] && pip install $@ ${iplotlib_up_dir}/iplotdataaccess/
	[ -d ${iplotlib_src_dir} ] && [ -f ${iplotlib_src_dir}/setup.py ] && pip install $@ ${iplotlib_src_dir}/
	[ -d ${iplotlib_up_dir}/mint ] && pip install $@ ${iplotlib_up_dir}/mint/
else
	echo "A recognized virtual environment does not exist"
fi

