# Distribution Folder

This folder contains the build artifacts for the IQView application and its dependencies for offline installation.

## Regeneration Instructions

To regenerate the application wheel and update the offline dependencies, follow these steps from the project root:

### 1. Build the Application Wheel
This creates the `iqview-0.1.0-py3-none-any.whl` file based on the current source code.
```powershell
# Optional: Clean old builds first
Remove-Item -Recurse -Force dist, build, iqview.egg-info

# Build the package
python -m build
```

### 2. Download Dependencies for Offline Use
This downloads all required third-party libraries (PyQt6, numpy, etc.) into this directory.
```powershell
python -m pip download -d dist .
```

## How to Install (Offline)
On the target machine, navigate to the folder containing these files and run:
```powershell
pip install --no-index --find-links . iqview-0.1.0-py3-none-any.whl
```
