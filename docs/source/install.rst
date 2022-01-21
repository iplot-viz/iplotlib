.. _installation:

Installation
------------

To use iplotlib, follow these steps on an SDCC-login node.

1. Clone the git repository and checkout latest release

.. code-block:: bash

    git clone ssh://git@git.iter.org/vis/iplotlib.git
    cd iplotlib
    git checkout x.y.z 

.. note::
    1. Use ssh-keys to avoid password prompts.
    2. See output of `git describe --tags `git rev-list --tags --max-count=1`` for the latest tag.

2. Initialize your environment.

.. code-block:: bash

    module load matplotlib/3.3.3-foss-2020b
    module load VTK/9.1.0-foss-2020b
    module load PySide2/5.14.2.3-GCCcore-10.2.0
    module load coverage/5.5-GCCcore-10.2.0
    module load iplotLogging/0.1.0-GCCcore-10.2.0    
    
# 3. Install with pip

.. code-block:: bash

    pip install .

.. _devinstallation:


.. note::
    1. If you wish to develop and contribute to **iplotlib**, checkout the `develop` branch instead of a release tag.
