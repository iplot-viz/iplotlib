.. _installation:

Installing iplotlib
===========================================

To get started, you can install it from `pypi.org <https://pypi.org/>`_:

.. code-block:: bash

    pip install iplotlib

Local installation from sources
-------
Clone the iplotlib repository and then run pip install:

.. code-block:: bash

    python3 -m venv ./venv
    . venv/bin/activate

    git clone https://github.com/iplot-viz/iplotlib.git
    cd iplotlib
    pip install .


Development installation
-------
For development, an installation in editable mode may be more convenient and you will need some extra dependencies to run the test suite and build documentation.

.. code-block:: bash

    pip install -e .[test,docs]

.. note:: If you plan on developing the IDV components, clone other repositories like so:

.. code-block:: bash

    # Your dev root should look like this.
    iplotlib/
        |-iplotlib
        |-pyproject.toml
        |-...
    iplotdataaccess
        |-iplotDataAccess
        |-pyproject.toml
        |-...
    iplotprocessing
        |-iplotProcessing
        |-pyproject.toml
        |-...
    iplotlogging
        |-iplotLogging
        |-pyproject.toml
        |-...
    iplotwidgets
        |-iplotWidgets
        |-pyproject.toml
        |-...
    mint
        |-mint
        |-pyproject.toml
        |-...
    $ cd iplotlib
    $ source development/setup-sdcc-dev.sh
    # To build documentation, execute this script
    $ ./development/setup-iplotlib-docs.sh
    # If you wish to exit, run
    $ idv_env_deactivate