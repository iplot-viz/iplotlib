# iplotlib- ITER plotting library
A high-level abstract plotting library. In development

| Graphics|GUI|
|----------|:-------------:|
| matplotlib|PyQt5, PySide2, PySide6|
| gnuplot|PyQt5|
| vtk|PyQt5, PySide2|

# Requirements
See [requirements.txt](https://git.iter.org/projects/VIS/repos/iplotlib/browse/requirements.txt)

# Install on sdcc-login nodes
1. Download repository
    ```bash
    git clone ssh://git@git.iter.org/vis/iplotlib.git
    ```

Note: If you plan on developing the IDV components, clone other repositories like so:
```bash
# Your dev root should look like this.
iplotlib/
    |-iplotlib
    |-setup.py
    |-...
iplotdataaccess
    |-iplotDataAccess
    |-setup.py
    |-...
iplotprocessing
    |-iplotProcessing
    |-setup.py
    |-...
iplotlogging
    |-iplotLogging
    |-setup.py
    |-...
mint
    |-mint
    |-setup.py
    |-...
$ cd iplotlib
$ source development/setup-sdcc-dev.sh
# To build documentation, execute this script
$ ./development/setup-iplotlib-docs.sh
# If you wish to exit, run
$ idv_env_deactivate
```

The remaining steps below are not required if your are developing iplotlib.

2. Prepare your environment.
    ``` bash
    cd iplotlib
    source environ.sh  # loads reuired modules on sdcc
    ```
3. Install `iplotlib`
    ``` bash
    pip install --user .
    ```
4. For developer installation (no copy)
    ``` bash
    pip install --user -e .
    ```
5. For system-wide installs with Easybuild
    1. Use PythonPackage easyblock with `use_pip=True`
    2. Prepare module file with dependencies from environ.sh

# Run tests
```bash
pytest iplotlib
```

# Run examples
```bash
iplotlib-qt-canvas -t
```
Click on canvas menu to switch between examples.
