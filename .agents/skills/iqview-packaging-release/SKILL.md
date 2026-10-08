---
name: iqview-packaging-release
description: >-
  ALWAYS load and read this skill before preparing releases, version bumping, changelog maintenance,
  building PyPI wheels, Debian packaging (scripts/make_deb.py), or distribution kits for IQView.
---

# IQView Packaging & Release Skill

This skill documents release procedures, version synchronization, Debian `.deb` packaging, and offline distribution.

For complete Debian package internals, TarInfo byte rules, and pip resolution:
- [Packaging & Distribution Internals Reference](./references/packaging_internals.md)

---

## 1. Synchronized Version Bump Checklist

When incrementing the version (e.g. `0.7.2` $\rightarrow$ `0.7.3`):
You **must** update the version string identically across four files:

1. [`pyproject.toml`](file:///d:/Projects/IQView/pyproject.toml):
   ```toml
   [project]
   version = "0.7.3"
   ```
2. [`iqview/__init__.py`](file:///d:/Projects/IQView/iqview/__init__.py):
   ```python
   __version__ = "0.7.3"
   ```
3. [`iqview/main.py`](file:///d:/Projects/IQView/iqview/main.py):
   ```python
   APP_USER_MODEL_ID = "OmerNaf.IQView.0.7.3"
   ```
4. [`changelog.md`](file:///d:/Projects/IQView/changelog.md):
   Add a new section heading following Keep a Changelog conventions:
   ```markdown
   ## [0.7.3] - YYYY-MM-DD

   ### Added
   ...
   ### Changed
   ...
   ### Fixed
   ...
   ```

---

## 2. Build Pipeline & Commands

### 2.1 Standard PyPI Build
```powershell
# 1. Clean previous build artifacts
Remove-Item -Recurse -Force dist, build, iqview.egg-info -ErrorAction SilentlyContinue

# 2. Build wheel and sdist
python -m build
```

### 2.2 Debian Package (.deb) Build
```powershell
# Online .deb (installs from PyPI during apt install):
python scripts/make_deb.py

# Offline .deb (bundles local wheels for air-gapped systems):
python scripts/build_project.py --offline-wheels offline_dist/linux/py312
```

### 2.3 Offline Distribution Kits
Run from repository root to download standalone wheel kits for Python 3.9 through 3.13:
```powershell
python prepare_offline.py
```

### 2.4 Automated PyPI Publishing (GitHub Actions CI/CD)
Publishes to PyPI automatically without manual uploads using PyPI Trusted Publishing (OIDC):
- Workflow file: `.github/workflows/publish.yml`
- Trigger: Tag push (`git push origin v*.*.*`), GitHub Release creation, or manual workflow dispatch.
- PyPI configuration: Settings $\rightarrow$ Publishing $\rightarrow$ Add GitHub publisher (`omernaf/IQView`, workflow `publish.yml`, environment `pypi`).

---

## 3. Packaging Architecture & Critical Gotchas

### 3.1 TarInfo Byte Length vs. Character Count
> [!CRITICAL]
> In [`scripts/make_deb.py`](file:///d:/Projects/IQView/scripts/make_deb.py), `TarInfo.size` **must always** be set using the encoded byte length:
> ```python
> encoded = content.encode('utf-8')
> tar_info.size = len(encoded)   # CORRECT: byte length
> # Never use: tar_info.size = len(content)  # BUG: breaks on multi-byte UTF-8
> ```
> Using character length truncates files containing non-ASCII characters during `dpkg` extraction, breaking `postinst` scripts.

### 3.2 Linux Qt Theme Collision Prevention
When running on Debian/Ubuntu systems, host platform themes can cause symbol collisions with PyQt6 (`Version Qt_6_PRIVATE_API symbol mismatch`).
The launcher script created by `make_deb.py` must strip host theme integration prior to launching Python:
```bash
export QT_QPA_PLATFORMTHEME=""
export QT_STYLE_OVERRIDE=""
exec /opt/iqview/venv/bin/python3 -m iqview "$@"
```

### 3.3 Private Network / Air-Gapped pip Resolution
In `.deb` maintainer scripts running under `sudo dpkg -i`:
- Never assume `HOME=/root` holds the user's pip configuration.
- Use `$SUDO_USER` to resolve the invoking user's home directory (`getent passwd "$SUDO_USER"`) and copy `/home/$SUDO_USER/.config/pip/pip.conf` into `/opt/iqview/venv/pip.conf`.
