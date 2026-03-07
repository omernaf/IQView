# Distribution Folder

This folder contains the build artifacts for IQView.

---

## For Developers — Regenerating Offline Kits

Run these steps from the **project root** when you want to update/rebuild everything.

### 1. Build the IQView wheel
```powershell
# Clean old builds (optional)
Remove-Item -Recurse -Force dist, build, iqview.egg-info

# Build
python -m build
```

### 2. Download offline wheels for all Python versions
```powershell
python prepare_offline.py
```

This creates an `offline_dist/` folder with sub-folders for each Python version:
```
offline_dist/
  py39/   ← wheels + install_offline.bat for Python 3.9
  py310/  ← wheels + install_offline.bat for Python 3.10
  py311/  ← ...
  py312/
  py313/
```

Each sub-folder is a **self-contained offline install kit** for its Python version.

---

## For End Users — Installing Offline

1. Find out which Python version is on the target machine:
   ```powershell
   python --version
   ```

2. Copy the matching sub-folder from `offline_dist/` to the target machine (e.g. `py311/` for Python 3.11).

3. Run the installer — either double-click `install_offline.bat` or from a terminal:
   ```powershell
   pip install --no-index --find-links=. iqview-0.1.0-py3-none-any.whl
   ```

---

## Online Installation (standard)

```powershell
pip install iqview
```
