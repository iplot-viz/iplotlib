# iplotlib- ITER plotting library
A high-level abstract plotting library. In development

| Graphics|GUI|
|----------|:-------------:|
| matplotlib|PyQt5, PySide2|
| gnuplot|PyQt5|
| vtk|PyQt5, PySide2|

# Requirements
See [requirements.txt](/requirements.txt)

# Install on sdcc-login nodes
1. Download repository
    ```bash
    git clone ssh://git@git.iter.org/vis/iplotlib.git
    ```
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
