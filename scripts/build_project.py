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
    # 1. Build the wheel/sdist
    print("Step 1: Building Python wheel and sdist...")
    run_command([sys.executable, "-m", "build"])
    
    # 2. Build the Debian package
    print("\nStep 2: Building Debian package (.deb)...")
    scripts_dir = Path(__file__).parent
    run_command([sys.executable, str(scripts_dir / "make_deb.py")])
    
    print("\nBuild complete! Check the 'dist/' directory for output.")

if __name__ == "__main__":
    main()
