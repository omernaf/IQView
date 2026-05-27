import subprocess
import os
import sys
from pathlib import Path

def run_command(cmd, cwd=None):
    """Utility to run a command and print output."""
    print(f"\n> {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        print(f"Error: Command failed with exit code {result.returncode}")
        sys.exit(result.returncode)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build IQView Project")
    parser.add_argument("--offline-wheels", type=str, default=None,
                        help="Path to directory containing pre-downloaded offline wheels (e.g. offline_dist/linux/py312)")
    parser.add_argument("--build-wheel", action="store_true",
                        help="Also build the Python wheel/sdist (required before publishing to PyPI, "
                             "and required for offline .deb builds)")
    args = parser.parse_args()

    if args.build_wheel or args.offline_wheels:
        # Build the wheel/sdist — needed for PyPI uploads and offline .deb bundles
        print("Step 1: Building Python wheel and sdist...")
        run_command([sys.executable, "-m", "build"])
    else:
        print("Step 1: Skipping wheel build (use --build-wheel to build a wheel for PyPI/offline).")

    # Build the Debian package
    print("\nStep 2: Building Debian package (.deb)...")
    scripts_dir = Path(__file__).parent
    cmd = [sys.executable, str(scripts_dir / "make_deb.py")]
    if args.offline_wheels:
        cmd.extend(["--offline-wheels", args.offline_wheels])
    run_command(cmd)
    
    print("\nBuild complete! Check the 'dist/' directory for output.")

if __name__ == "__main__":
    main()
