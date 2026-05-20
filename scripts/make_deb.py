import os
import sys
import tarfile
import io
import time
import shutil
import subprocess
from pathlib import Path

# Metadata
PACKAGE_NAME = "iqview"
MAINTAINER = "Omer Naf <omernaf@gmail.com>"
DESCRIPTION = "High-performance Static RF Spectrogram Viewer"
SECTION = "science"
PRIORITY = "optional"
ARCHITECTURE = "amd64"

def create_ar_archive(output_path, files):
    """
    Creates a basic 'ar' archive (the format of a .deb file).
    files: list of (filename, bytes)
    """
    with open(output_path, 'wb') as f:
        # Global header
        f.write(b"!<arch>\n")
        
        for name, data in files:
            # File header
            # name (16), timestamp (12), owner (6), group (6), mode (8), size (10), marker (2)
            timestamp = str(int(time.time())).ljust(12)
            owner = "0".ljust(6)
            group = "0".ljust(6)
            mode = "100644".ljust(8)
            size = str(len(data)).ljust(10)
            
            header = f"{name.ljust(16)}{timestamp}{owner}{group}{mode}{size}\x60\n"
            f.write(header.encode('ascii'))
            f.write(data)
            
            # Pad to even byte boundary
            if len(data) % 2 != 0:
                f.write(b"\n")

def get_project_version():
    """Extract version from pyproject.toml."""
    try:
        with open("pyproject.toml", "r") as f:
            for line in f:
                if line.strip().startswith("version ="):
                    return line.split("=")[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return "0.1.4"

def find_wheel():
    """Find the .whl in dist/."""
    dist_dir = Path("dist")
    if not dist_dir.exists():
        return None
    wheels = list(dist_dir.glob("iqview-*.whl"))
    if not wheels:
        return None
    # Return the latest one
    return sorted(wheels)[-1]

def make_deb(offline_wheels=None):
    version = get_project_version()
    wheel_path = find_wheel()
    
    if not wheel_path:
        print("Error: No .whl found in dist/. Run 'python -m build' first.")
        sys.exit(1)
        
    suffix = "_offline" if offline_wheels else ""
    print(f"Building .deb for IQView v{version}{suffix} using {wheel_path.name}...")
    
    # 1. Create Control Tarball
    control_buf = io.BytesIO()
    # Force GNU_FORMAT to avoid 'PAX tar header' errors on some Linux distros
    with tarfile.open(fileobj=control_buf, mode='w:gz', format=tarfile.GNU_FORMAT) as tar:
        # control file
        control_content = f"""Package: {PACKAGE_NAME}
Version: {version}
Section: {SECTION}
Priority: {PRIORITY}
Architecture: {ARCHITECTURE}
Maintainer: {MAINTAINER}
Description: {DESCRIPTION}
Depends: python3, python3-pip, python3-venv, libgl1, libxcb-cursor0
"""
        c_info = tarfile.TarInfo("control")
        c_info.size = len(control_content)
        c_info.mtime = time.time()
        tar.addfile(c_info, io.BytesIO(control_content.encode('utf-8')))
        
        # postinst script
        postinst_content = f"""#!/bin/bash
set -e

APP_DIR="/opt/iqview"
VENV_DIR="$APP_DIR/venv"
WHEEL_PATH="$APP_DIR/{wheel_path.name}"

echo "Setting up IQView virtual environment in $VENV_DIR..."
mkdir -p "$APP_DIR"
python3 -m venv "$VENV_DIR"

if [ -d "$APP_DIR/wheels" ]; then
    echo "Installing IQView and dependencies from local wheels..."
    "$VENV_DIR/bin/pip" install --no-index --find-links="$APP_DIR/wheels" "$WHEEL_PATH"
else
    echo "Installing IQView from wheel..."
    "$VENV_DIR/bin/pip" install "$WHEEL_PATH"
fi

echo "Creating symbolic link..."
ln -sf "$VENV_DIR/bin/iqview" /usr/bin/iqview

# Trigger desktop integration to set up associations
echo "Configuring desktop integration and file associations..."
/usr/bin/iqview --install-desktop
/usr/bin/iqview --install-mat

echo "IQView installation complete."
exit 0
"""
        p_info = tarfile.TarInfo("postinst")
        p_info.size = len(postinst_content)
        p_info.mtime = time.time()
        p_info.mode = 0o755
        tar.addfile(p_info, io.BytesIO(postinst_content.encode('utf-8')))
        
        # prerm script
        prerm_content = f"""#!/bin/bash
set -e

# Run uninstall-desktop before removing the files
if [ -f /usr/bin/iqview ]; then
    /usr/bin/iqview --uninstall-desktop || true
    rm -f /usr/bin/iqview
fi

echo "Removing IQView files..."
rm -rf /opt/iqview

exit 0
"""
        pr_info = tarfile.TarInfo("prerm")
        pr_info.size = len(prerm_content)
        pr_info.mtime = time.time()
        pr_info.mode = 0o755
        tar.addfile(pr_info, io.BytesIO(prerm_content.encode('utf-8')))

    # 2. Create Data Tarball
    data_buf = io.BytesIO()
    with tarfile.open(fileobj=data_buf, mode='w:gz', format=tarfile.GNU_FORMAT) as tar:
        # Explicitly add directories. dpkg needs these entries to create parent folders.
        dirs_to_add = ["opt/", "opt/iqview/"]
        if offline_wheels:
            dirs_to_add.append("opt/iqview/wheels/")
            
        for d in dirs_to_add:
            d_info = tarfile.TarInfo(d)
            d_info.type = tarfile.DIRTYPE
            d_info.mtime = int(time.time())
            d_info.mode = 0o755
            tar.addfile(d_info)
            
        # Add the wheel
        tar.add(wheel_path, arcname=f"opt/iqview/{wheel_path.name}")
        
        # Add offline wheels if specified
        if offline_wheels:
            offline_path = Path(offline_wheels)
            if not offline_path.exists() or not offline_path.is_dir():
                print(f"Error: Offline wheels directory '{offline_wheels}' does not exist.")
                sys.exit(1)
                
            print(f"Packaging offline wheels from '{offline_wheels}'...")
            for w in offline_path.glob("*.whl"):
                if w.name.startswith("iqview-"):
                    # Avoid duplicate packaging of iqview wheel
                    continue
                tar.add(w, arcname=f"opt/iqview/wheels/{w.name}")
        
    # 3. Create the .deb
    output_filename = f"dist/{PACKAGE_NAME}_{version}{suffix}_{ARCHITECTURE}.deb"
    create_ar_archive(output_filename, [
        ("debian-binary", b"2.0\n"),
        ("control.tar.gz", control_buf.getvalue()),
        ("data.tar.gz", data_buf.getvalue())
    ])
    
    print(f"Successfully created {output_filename}")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build IQView Debian Package")
    parser.add_argument("--offline-wheels", type=str, default=None,
                        help="Path to directory containing pre-downloaded offline wheels (e.g. offline_dist/linux/py312)")
    args = parser.parse_args()
    make_deb(offline_wheels=args.offline_wheels)

if __name__ == "__main__":
    main()
