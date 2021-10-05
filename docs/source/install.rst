.. _installation:

Installation
------------

To use iplotlib, follow these steps on an SDCC-login node.

.. code-block:: bash

    # 1. Clone the git repository and checkout latest release
    # tip: Use ssh-keys to avoid password prompts.
    $ git clone ssh://git@git.iter.org/vis/iplotlib.git
    $ cd iplotlib
    $ git checkout x.y.z # see output of $ git describe --tags `git rev-list --tags --max-count=1` for the latest tag.
    
    # 2. Initialize your environment.
    $ source environ.sh
    
    # 3. Install with pip
    $ pip install .

.. _devinstallation:

Installation for developers
---------------------------

To develop and contribute to **iplotlib**, follow these steps on an SDCC-login node.

.. code-block:: bash

    # 1. Clone the git repository and checkout develop branch
    # tip: Use ssh-keys to avoid password prompts.
    $ git clone ssh://git@git.iter.org/vis/iplotlib.git
    $ cd iplotlib
    $ git checkout develop
    
    # 2. Initialize your environment.
    $ source environ.sh
    
    # 3. Install with the -e flag.
    $ pip install -e .
