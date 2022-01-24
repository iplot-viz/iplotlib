#!/bin/bash
base_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" > /dev/null && pwd )"
echo "Make sure you source this file ${BASH_SOURCE[0]}"
export iplotlib_src_dir="$( dirname ${base_dir} )"
export iplotlib_up_dir="$( dirname ${iplotlib_src_dir} )"

source ${base_dir}/01-create-env.sh idv
source ${idv_venv_dir}/bin/activate
source ${base_dir}/02-post-env-activate.sh
source ${base_dir}/03-install-packages.sh --no-deps -e

function idv_env_deactivate()
{
	deactivate
	echo "Ignore the warning shown below."
	module purge
	module purge
}

function uninstall_idv()
{
	${base_dir}/04-uninstall-packages.sh
}