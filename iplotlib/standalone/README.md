# iplotlib Standalone Qt Canvas

This file implements a standalone Canvas using iplotlib and PySide6, designed as a test application.

## Features

- **Standalone Canvas**: Works as a standalone Qt application.
- **Support for Multiple Graphic Backends**: Designed to be flexible with various backends like `matplotlib`.
- **Optional Toolbar**: Configurable based on the user's needs.
- **Predefined Examples**: Ready-to-use examples included in the `examples` and `examples_json` folders.
- **Menu System**: Interactive menu to select and manage active canvases.

---

## Usage

### Basic Execution

To start the application, run the main file from the command line:

```bash
python iplotQtStandaloneCanvas.py
```

### Optional Arguments

The application supports the following arguments to customize its behavior:

- `-impl`: Specifies the graphic backend (default: `matplotlib`).
- `-t`: Enables the toolbar (disabled by default).
- `-use-fallback-samples`: Uses fallback resolution samples for large displays.
- `-profile`: Activates profiling mode for performance debugging.

Example:

```bash
python iplotQtStandaloneCanvas.py -impl matplotlib -t
```

### Adding Canvases

Canvases are automatically added at startup by analyzing the `examples` module. All examples containing the `get_canvas`
function are loaded.

---

## Project Structure

- **Main File (`iplotQtStandaloneCanvas`)**
    - Runs and manages the Qt application.
    - Includes the classes and functions necessary to initialize the main window and canvases.

- **`examples`:**
    - Contains scripts with predefined canvas examples to demonstrate different functionalities. Each
      example must implement the `get_canvas` function, which returns a `Canvas` object.

- **`examples_json`:**
    - Provides JSON configurations to automatically generate canvases based on predefined settings.
