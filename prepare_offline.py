"""
prepare_offline.py
==================
Run this script on your development machine (with internet access) to pre-download
all IQView dependency wheels for every supported Python version.

Each Python version gets its own sub-folder under `offline_dist/`, e.g.:
    offline_dist/py39/
    offline_dist/py311/
    ...

The iqview wheel is also copied into every sub-folder so each folder is a
self-contained, single-command install kit.

Usage:
    python prepare_offline.py

Requirements:
    - Internet access
    - pip >= 22 (for cross-platform --platform downloads)
    - The iqview wheel must already be built in ./dist/
      Run `python -m build` first if needed.
"""

import glob
import shutil
import subprocess
import sys
import argparse
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────────────

# Dependencies listed in pyproject.toml (iqview itself is added separately)
DEPENDENCIES = [
    "numpy",
    "PyQt6",
    "pyqtgraph >= 0.13.0",
    "PyOpenGL",
    "scipy",
]

# (python_tag, abi_tag) pairs to download for.
# python_tag  → used for --python-version (e.g. "3.11")
# folder_name → sub-folder inside offline_dist/
PYTHON_TARGETS = [
    {"python_version": "3.9",  "folder": "py39"},
    {"python_version": "3.10", "folder": "py310"},
    {"python_version": "3.11", "folder": "py311"},
    {"python_version": "3.12", "folder": "py312"},
    {"python_version": "3.13", "folder": "py313"},
]

# # Dynamic platform targeting based on current OS
# if sys.platform.startswith("linux"):
#     PLATFORM = "manylinux2014_x86_64"
# else:
#     # Default to Windows 64-bit.
#     PLATFORM = "win_amd64"

DIST_DIR    = Path("offline_dist")

# ─────────────────────────────────────────────────────────────────────────────


def find_iqview_wheel() -> Path:
    """Locate the built iqview wheel in ./dist/."""
    matches = sorted(DIST_DIR.glob("iqview-*.whl"))
    if not matches:
        print(
            "\n[ERROR] No iqview wheel found in ./dist/\n"
            "        Run `python -m build` first, then re-run this script.\n"
        )
        sys.exit(1)
    if len(matches) > 1:
        print(f"[WARN] Multiple iqview wheels found; using the newest: {matches[-1].name}")
    return matches[-1]


def download_for_target(target: dict, iqview_wheel: Path, platforms: list, output_root: Path, os_name: str) -> bool:
    """Download all deps for a single Python version target. Returns True on success."""
    folder = output_root / target["folder"]
    folder.mkdir(parents=True, exist_ok=True)

    python_version = target["python_version"]
    print(f"\n{'─'*60}")
    print(f"  Downloading for Python {python_version} / {', '.join(platforms)}")
    print(f"  Output → {folder}")
    print(f"{'─'*60}")

    cmd = [
        sys.executable, "-m", "pip", "download",
        "--python-version", python_version,
        "--only-binary",    ":all:",
        "--dest",           str(folder),
    ]
    for p in platforms:
        cmd.extend(["--platform", p])
    cmd.extend(DEPENDENCIES)

    result = subprocess.run(cmd)

    if result.returncode != 0:
        print(f"\n[WARN] pip download failed for Python {python_version}. "
              "Some wheels may not be available for this version — skipping.\n")
        return False

    # Copy the iqview wheel into this folder
    dest_wheel = folder / iqview_wheel.name
    if not dest_wheel.exists():
        shutil.copy2(iqview_wheel, dest_wheel)
        print(f"  ✓ Copied {iqview_wheel.name} → {dest_wheel}")

    if os_name == "windows":
        # Write install + uninstall bats for convenience
        write_install_bat(folder, iqview_wheel.name, python_version)
        write_uninstall_bat(folder)
    else:
        # Write install + uninstall shell scripts for Linux
        write_install_sh(folder, iqview_wheel.name, python_version)
        write_uninstall_sh(folder)
    return True


def write_install_bat(folder: Path, wheel_name: str, python_version: str):
    """Write install_offline.bat into the target folder."""
    bat_path = folder / "install_offline.bat"
    bat_content = f"""\
@echo off
:: IQView offline installer for Python {python_version} on Windows x64
:: Run this file on the target machine inside this folder.

:: Change to this script's own directory so relative paths work correctly
cd /d "%~dp0"

echo Installing IQView (Python {python_version}) from local wheels...
pip install --no-index --find-links=. {wheel_name}
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Installation failed.
    echo Make sure you are running Python {python_version} and this folder is intact.
    pause
    exit /b 1
)
echo.
echo IQView installed successfully!
echo Run it with:  iqview
pause
"""
    bat_path.write_text(bat_content, encoding="utf-8")
    print(f"  ✓ Wrote {bat_path.name}")


def write_uninstall_bat(folder: Path):
    """Write uninstall_iqview.bat into the target folder."""
    bat_path = folder / "uninstall_iqview.bat"
    bat_content = """\
@echo off
:: IQView — Uninstall script
:: Removes iqview and all its dependencies from the current Python environment.
:: Use this to clean up before testing the offline installer.

echo Uninstalling IQView and its dependencies...
echo.

pip uninstall -y iqview numpy pyqtgraph PyOpenGL scipy PyQt6 PyQt6-Qt6 PyQt6-sip colorama

echo.
echo Done. You can now re-install from the offline kit to test it.
pause
"""
    bat_path.write_text(bat_content, encoding="utf-8")
    print(f"  ✓ Wrote {bat_path.name}")


def write_install_sh(folder: Path, wheel_name: str, python_version: str):
    """Write install_offline.sh into the target folder."""
    sh_path = folder / "install_offline.sh"
    sh_content = f"""#!/bin/bash
# IQView offline installer for Python {python_version} on Linux x64
# Run this file on the target machine inside this folder.

# Change to this script's own directory so relative paths work correctly
cd "$(dirname "$0")"

echo "Installing IQView (Python {python_version}) from local wheels..."
pip install --no-index --find-links=. {wheel_name}
if [ $? -ne 0 ]; then
    echo
    echo "[ERROR] Installation failed."
    echo "Make sure you are running Python {python_version} and this folder is intact."
    exit 1
fi
echo
echo "IQView installed successfully!"
echo "Run it with: iqview"
"""
    sh_path.write_text(sh_content, encoding="utf-8")
    sh_path.chmod(0o755)
    print(f"  ✓ Wrote {sh_path.name}")


def write_uninstall_sh(folder: Path):
    """Write uninstall_iqview.sh into the target folder."""
    sh_path = folder / "uninstall_iqview.sh"
    sh_content = """#!/bin/bash
# IQView — Uninstall script
# Removes iqview and all its dependencies from the current Python environment.
# Use this to clean up before testing the offline installer.

echo "Uninstalling IQView and its dependencies..."
echo

pip uninstall -y iqview numpy pyqtgraph PyOpenGL scipy PyQt6 PyQt6-Qt6 PyQt6-sip colorama

echo
echo "Done. You can now re-install from the offline kit to test it."
"""
    sh_path.write_text(sh_content, encoding="utf-8")
    sh_path.chmod(0o755)
    print(f"  ✓ Wrote {sh_path.name}")


def print_summary(results: list, output_root: Path, os_name: str):
    print(f"\n{'═'*60}")
    print("  Summary")
    print(f"{'═'*60}")
    for target, ok in results:
        status = "✓ OK" if ok else "✗ FAILED / skipped"
        print(f"  Python {target['python_version']:5s}  →  {status}")
    print(f"\nOffline kits are in: {output_root.resolve()}")
    
    script_name = "install_offline.bat" if os_name == "windows" else "install_offline.sh"
    print(
        "\nTo install on a target machine, copy the matching sub-folder\n"
        f"and double-click {script_name}.\n"
    )


def main():
    parser = argparse.ArgumentParser(description="IQView Offline Wheel Downloader")
    default_os = "linux" if sys.platform.startswith("linux") else "windows"
    parser.add_argument("--os", choices=["windows", "linux"], default=default_os,
                        help="Target OS to download wheels for (determines platform tags).")
    args = parser.parse_args()

    os_name = args.os
    if os_name == "windows":
        platforms = ["win_amd64"]
        output_root = Path("offline_dist") / "windows"
    else:
        platforms = ["manylinux_2_28_x86_64", "manylinux2014_x86_64", "manylinux_2_17_x86_64"]
        output_root = Path("offline_dist") / "linux"

    print("IQView — Offline Wheel Downloader")
    print(f"Target OS: {os_name}")
    print(f"Platform : {', '.join(platforms)}")
    print(f"Targets  : {', '.join(t['python_version'] for t in PYTHON_TARGETS)}")

    iqview_wheel = find_iqview_wheel()
    print(f"IQView wheel: {iqview_wheel.name}")

    results = []
    for target in PYTHON_TARGETS:
        ok = download_for_target(target, iqview_wheel, platforms, output_root, os_name)
        results.append((target, ok))

    print_summary(results, output_root, os_name)


if __name__ == "__main__":
    main()
