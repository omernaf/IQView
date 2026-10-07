import os
import sys
import subprocess
import shutil
from typing import List


def _get_supported_extensions():
    """
    Returns a unified list of supported extensions by merging 
    built-in factory defaults with current settings.
    """
    # Baseline factory-supported extensions
    exts = {
        ".32f", ".64f", ".16tc", ".16sc", ".64fc", ".32fc", 
        ".bin", ".iq", ".sigmf", ".sigmf-data", ".mat", ".r3f"
    }
    
    try:
        from iqview.utils.settings_manager import SettingsManager
        sm = SettingsManager()
        mapping = sm.get("core/extension_mapping", {})
        if mapping:
            exts.update(mapping.keys())
    except Exception:
        pass
        
    return sorted(list(exts))


APP_NAME = "IQView"
APP_PROG_ID = "IQView.File"
APP_DESC = "IQ Data File"


def is_admin() -> bool:
    """Check if the current process is running with Administrator / root privileges."""
    if os.name == "nt":
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    else:
        return os.geteuid() == 0


def _get_candidate_script_dirs() -> List[str]:
    """Returns candidate directories where iqview executables or scripts might be located."""
    dirs = []
    python_dir = os.path.dirname(sys.executable)

    # 1. Standard sysconfig scripts (current python environment)
    try:
        import sysconfig
        s_dir = sysconfig.get_path("scripts")
        if s_dir:
            dirs.append(s_dir)
    except Exception:
        pass

    # 2. Python executable directory and Scripts/bin
    dirs.append(python_dir)
    if os.name == "nt":
        dirs.append(os.path.join(python_dir, "Scripts"))
    else:
        dirs.append(os.path.join(python_dir, "bin"))

    # 3. Virtual environment base prefix (if inside a venv)
    if hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix:
        dirs.append(sys.base_prefix)
        if os.name == "nt":
            dirs.append(os.path.join(sys.base_prefix, "Scripts"))
        else:
            dirs.append(os.path.join(sys.base_prefix, "bin"))

    # 4. Per-user scripts scheme (nt_user / posix_user)
    try:
        import sysconfig
        user_scheme = f"{os.name}_user"
        if user_scheme in sysconfig.get_scheme_names():
            u_dir = sysconfig.get_path("scripts", user_scheme)
            if u_dir:
                dirs.append(u_dir)
    except Exception:
        pass

    # 5. site.getuserbase() directory
    try:
        import site
        ub = site.getuserbase()
        if ub:
            if os.name == "nt":
                dirs.append(os.path.join(ub, "Scripts"))
                py_ver = f"Python{sys.version_info.major}{sys.version_info.minor}"
                dirs.append(os.path.join(ub, py_ver, "Scripts"))
            else:
                dirs.append(os.path.join(ub, "bin"))
    except Exception:
        pass

    # 6. Common POSIX user / system paths
    if os.name != "nt":
        dirs.append(os.path.expanduser("~/.local/bin"))
        dirs.append("/usr/local/bin")
        dirs.append("/usr/bin")

    # De-duplicate while preserving order
    seen = set()
    unique_dirs = []
    for d in dirs:
        if d:
            norm = os.path.normpath(d)
            if norm not in seen:
                seen.add(norm)
                unique_dirs.append(norm)
    return unique_dirs


def get_executable_path() -> str:
    """
    Returns the path to the application executable or script.
    Checks all candidate script locations (including per-user Scripts when Python is installed for all users).
    Falls back to pythonw/python if no standalone wrapper exists.
    """
    if os.name == "nt":
        script_names = ["iqview-gui.exe", "iqview.exe", "iqview-gui.cmd", "iqview.cmd", "iqview-gui.bat", "iqview.bat"]
    else:
        script_names = ["iqview-gui", "iqview"]

    # 1. Search candidate directories
    for d in _get_candidate_script_dirs():
        for name in script_names:
            candidate = os.path.join(d, name)
            if os.path.exists(candidate):
                return candidate

    # 2. Check PATH via shutil.which
    for name in script_names:
        which_path = shutil.which(name)
        if which_path and os.path.exists(which_path):
            return os.path.abspath(which_path)

    # 3. Fallback: on Windows look for pythonw.exe (no console pop-up)
    if os.name == "nt":
        python_dir = os.path.dirname(sys.executable)
        for d in [python_dir, getattr(sys, "base_prefix", python_dir)]:
            pw = os.path.join(d, "pythonw.exe")
            if os.path.exists(pw):
                return pw
        return sys.executable
    else:
        # On POSIX: fallback to python interpreter or default command
        user_bin = os.path.expanduser("~/.local/bin/iqview-gui")
        if os.path.exists(user_bin):
            return user_bin
        return sys.executable


def get_open_command(exe_path: str) -> str:
    """Returns the shell command string to open a file with IQView."""
    basename = os.path.basename(exe_path).lower()
    if basename in ("pythonw.exe", "python.exe", "python3", "python"):
        return f'"{exe_path}" -m iqview "%1"'
    return f'"{exe_path}" "%1"'


def get_icon_path() -> str:
    """Returns the path to the application icon, preferring PNG on Linux."""
    try:
        import iqview
        pkg_dir = os.path.dirname(iqview.__file__)
        
        # On Linux, PNG is preferred for .desktop files
        extensions = [".png", ".ico"] if os.name != "nt" else [".ico", ".png"]
        
        for ext in extensions:
            icon_path = os.path.join(pkg_dir, "resources", f"logo{ext}")
            if os.path.exists(icon_path):
                return icon_path
    except ImportError:
        pass
    
    # fallback to get_executable_path
    return get_executable_path()


def _ensure_windows_user_path(directory: str):
    """Checks if directory is on User PATH; if missing, adds it to HKCU\\Environment and broadcasts update."""
    import winreg
    norm_target = os.path.normpath(directory)
    
    # Check current process PATH
    current_paths = [os.path.normpath(p) for p in os.environ.get("PATH", "").split(";") if p.strip()]
    if norm_target in current_paths:
        return

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            try:
                user_path, path_type = winreg.QueryValueEx(key, "Path")
            except OSError:
                user_path = ""
                path_type = winreg.REG_EXPAND_SZ

            existing_dirs = [os.path.normpath(p) for p in user_path.split(";") if p.strip()]
            if norm_target not in existing_dirs:
                new_path = f"{user_path};{directory}" if user_path.strip() else directory
                winreg.SetValueEx(key, "Path", 0, path_type, new_path)
                print(f"  [OK] Added '{directory}' to User PATH")
                print("  [i] Notice: Open a new terminal window for the updated PATH to take effect")

                # Broadcast environment update
                try:
                    import ctypes
                    HWND_BROADCAST = 0xFFFF
                    WM_SETTINGCHANGE = 0x001A
                    SMTO_ABORTIFHUNG = 0x0002
                    result = ctypes.c_ulong()
                    ctypes.windll.user32.SendMessageTimeoutW(
                        HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", SMTO_ABORTIFHUNG, 5000, ctypes.byref(result)
                    )
                except Exception:
                    pass
    except Exception as e:
        print(f"  [!] Note: Could not add '{directory}' to User PATH: {e}")


def _sync_script_and_path(exe_path: str):
    """
    Ensures the iqview script is placed in the right place and accessible via PATH:
    1. If Python is installed for all users and the system Scripts directory is writable:
       Generates iqview and iqview-gui wrapper scripts in the system Scripts directory.
    2. If the directory containing exe_path is not in PATH, adds it to User PATH (on Windows).
    """
    if os.name == "nt":
        python_dir = os.path.dirname(sys.executable)
        sys_scripts_dir = os.path.join(python_dir, "Scripts")

        # 1. System Scripts directory handling
        if os.path.isdir(sys_scripts_dir) and os.access(sys_scripts_dir, os.W_OK):
            try:
                if os.path.dirname(os.path.abspath(exe_path)).lower() != os.path.abspath(sys_scripts_dir).lower():
                    pw = os.path.join(python_dir, "pythonw.exe")
                    pythonw_target = pw if os.path.exists(pw) else sys.executable
                    cmd_content = f'@echo off\r\n"{sys.executable}" -m iqview %*\r\n'
                    gui_cmd_content = f'@echo off\r\nstart "" "{pythonw_target}" -m iqview %*\r\n'
                    
                    target_cmd = os.path.join(sys_scripts_dir, "iqview.cmd")
                    target_gui_cmd = os.path.join(sys_scripts_dir, "iqview-gui.cmd")
                    
                    with open(target_cmd, "w", encoding="utf-8") as f:
                        f.write(cmd_content)
                    with open(target_gui_cmd, "w", encoding="utf-8") as f:
                        f.write(gui_cmd_content)
                    print(f"  [OK] Installed launcher scripts to {sys_scripts_dir} (available for all users)")
            except Exception as e:
                print(f"  [!] Note: Could not write launchers to {sys_scripts_dir}: {e}")

        # 2. Check if the directory containing exe_path is in PATH
        exe_dir = os.path.dirname(os.path.abspath(exe_path))
        if os.path.isdir(exe_dir):
            _ensure_windows_user_path(exe_dir)
            
    elif sys.platform.startswith("linux"):
        if is_admin():
            target_link = "/usr/local/bin/iqview"
            try:
                if not os.path.exists(target_link):
                    os.symlink(exe_path, target_link)
                    print(f"  [OK] Created symlink at {target_link}")
            except Exception as e:
                print(f"  [!] Note: Could not create symlink at {target_link}: {e}")
        else:
            exe_dir = os.path.dirname(os.path.abspath(exe_path))
            path_dirs = [os.path.normpath(p) for p in os.environ.get("PATH", "").split(":") if p]
            if os.path.normpath(exe_dir) not in path_dirs:
                print(f"  [i] Notice: '{exe_dir}' is not in your current PATH.")
                print(f"      Add 'export PATH=\"{exe_dir}:$PATH\"' to ~/.bashrc or ~/.profile to run 'iqview' from anywhere.")


def _create_shortcut(exe_path, icon_path):
    print("Creating Start Menu shortcut...")
    if is_admin():
        start_menu_dir = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "Microsoft", "Windows", "Start Menu", "Programs")
    else:
        start_menu_dir = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")
        
    os.makedirs(start_menu_dir, exist_ok=True)
    shortcut_path = os.path.join(start_menu_dir, f"{APP_NAME}.lnk")

    basename = os.path.basename(exe_path).lower()
    if basename in ("pythonw.exe", "python.exe"):
        args = "-m iqview"
    else:
        args = ""
    
    # We use PowerShell's WScript.Shell COM object to create a shortcut without requiring pywin32 module
    ps_cmd = (
        f"$wshell = New-Object -ComObject WScript.Shell; "
        f"$shortcut = $wshell.CreateShortcut('{shortcut_path}'); "
        f"$shortcut.TargetPath = '{exe_path}'; "
        + (f"$shortcut.Arguments = '{args}'; " if args else "")
        + f"$shortcut.IconLocation = '{icon_path}'; "
        f"$shortcut.Description = 'High-performance Static RF Spectrogram Viewer'; "
        f"$shortcut.Save();"
    )
    
    result = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
    if result.returncode == 0:
        scope = "All Users" if is_admin() else "Current User"
        print(f"  [OK] Shortcut created at {shortcut_path} ({scope})")
    else:
        print(f"  [X] Failed to create shortcut: {result.stderr}")


def _register_file_associations(exe_path, icon_path, extensions=None):
    import winreg
    print("Registering file associations...")
    command = get_open_command(exe_path)
    
    if extensions is None:
        extensions = _get_supported_extensions()

    roots = [(winreg.HKEY_CURRENT_USER, "HKCU")]
    if is_admin():
        roots.append((winreg.HKEY_LOCAL_MACHINE, "HKLM"))

    for root_key, root_name in roots:
        try:
            # 1. Register the ProgID
            with winreg.CreateKey(root_key, fr"Software\Classes\{APP_PROG_ID}") as key:
                winreg.SetValue(key, "", winreg.REG_SZ, APP_DESC)
                
            with winreg.CreateKey(root_key, fr"Software\Classes\{APP_PROG_ID}\DefaultIcon") as key:
                # Append ,0 to the icon path (standard for DefaultIcon)
                winreg.SetValue(key, "", winreg.REG_SZ, f"{icon_path},0")
                
            with winreg.CreateKey(root_key, fr"Software\Classes\{APP_PROG_ID}\shell\open\command") as key:
                winreg.SetValue(key, "", winreg.REG_SZ, command)
                
            # 2. Register specified file extensions to the ProgID
            for ext in extensions:
                with winreg.CreateKey(root_key, fr"Software\Classes\{ext}") as key:
                    winreg.SetValue(key, "", winreg.REG_SZ, APP_PROG_ID)
                
                # Also set the icon directly for the extension (can help with immediate refresh)
                try:
                    with winreg.CreateKey(root_key, fr"Software\Classes\{ext}\DefaultIcon") as key:
                        winreg.SetValue(key, "", winreg.REG_SZ, f"{icon_path},0")
                except Exception:
                    pass
                    
                print(f"  [OK] Associated {ext} ({root_name})")
                    
            # 3. Notify Windows shell to update icons/associations
            ps_notify = (
                "Add-Type -TypeDefinition '"
                "using System;"
                "using System.Runtime.InteropServices;"
                "public class Shell {"
                "  [DllImport(\"shell32.dll\")] "
                "  public static extern void SHChangeNotify(uint wEventId, uint uFlags, IntPtr dwItem1, IntPtr dwItem2);"
                "}'; "
                "[Shell]::SHChangeNotify(0x08000000, 0x0000, [IntPtr]::Zero, [IntPtr]::Zero);"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_notify], capture_output=True)
            print(f"  [OK] Registered file associations successfully ({root_name})")
        except Exception as e:
            print(f"  [X] Failed to register file associations in {root_name}: {e}")


def _remove_shortcut():
    print("Removing Start Menu shortcut...")
    targets = [
        os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "Microsoft", "Windows", "Start Menu", "Programs", f"{APP_NAME}.lnk"),
        os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", f"{APP_NAME}.lnk")
    ]
    removed = False
    for path in targets:
        try:
            if os.path.exists(path):
                os.remove(path)
                print(f"  [OK] Shortcut removed at {path}")
                removed = True
        except Exception as e:
            print(f"  [X] Failed to remove shortcut at {path}: {e}")
    if not removed:
        print("  - Shortcut not found")


def _delete_reg_key(key_root, sub_key):
    """Recursively delete a registry key."""
    import winreg
    try:
        with winreg.OpenKey(key_root, sub_key, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    name = winreg.EnumKey(key, 0)
                    _delete_reg_key(key, name)
                except OSError:
                    break
        winreg.DeleteKey(key_root, sub_key)
    except OSError:
        pass # Key doesn't exist


def _unregister_file_associations(extensions=None):
    import winreg
    print("Unregistering file associations...")
    
    if extensions is None:
        extensions = _get_supported_extensions()

    roots = [(winreg.HKEY_CURRENT_USER, "HKCU")]
    if is_admin():
        roots.append((winreg.HKEY_LOCAL_MACHINE, "HKLM"))

    for root_key, root_name in roots:
        try:
            # 1. Unregister specified file extensions (if they pointed to our ProgID)
            for ext in extensions:
                try:
                    with winreg.OpenKey(root_key, fr"Software\Classes\{ext}", 0, winreg.KEY_ALL_ACCESS) as key:
                        val, _ = winreg.QueryValueEx(key, "")
                        if val == APP_PROG_ID:
                            winreg.DeleteValue(key, "")
                            print(f"  [OK] Unassociated {ext} ({root_name})")
                except OSError:
                    pass
                    
            # 2. Delete the ProgID if it's a full unregister (no extensions specified)
            if extensions == _get_supported_extensions():
                _delete_reg_key(root_key, fr"Software\Classes\{APP_PROG_ID}")
                print(f"  [OK] Unregistered ProgID ({root_name})")
            
            # 3. Notify Windows shell to update icons/associations
            ps_notify = (
                "Add-Type -TypeDefinition '"
                "using System;"
                "using System.Runtime.InteropServices;"
                "public class Shell {"
                "  [DllImport(\"shell32.dll\")] "
                "  public static extern void SHChangeNotify(uint wEventId, uint uFlags, IntPtr dwItem1, IntPtr dwItem2);"
                "}'; "
                "[Shell]::SHChangeNotify(0x08000000, 0x0000, [IntPtr]::Zero, [IntPtr]::Zero);"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_notify], capture_output=True)
        except Exception as e:
            print(f"  [X] Failed to unregister file associations in {root_name}: {e}")


def _install_linux_desktop(exe_path, icon_path):
    print("Creating Linux .desktop file...")
    if is_admin():
        desktop_dir = "/usr/share/applications"
    else:
        desktop_dir = os.path.expanduser("~/.local/share/applications")
        
    os.makedirs(desktop_dir, exist_ok=True)
    desktop_file = os.path.join(desktop_dir, f"{APP_NAME.lower()}.desktop")

    basename = os.path.basename(exe_path).lower()
    if basename in ("python3", "python"):
        exec_cmd = f'"{exe_path}" -m iqview %f'
    else:
        exec_cmd = f'"{exe_path}" %f'
    
    content = f"""[Desktop Entry]
Name={APP_NAME}
Comment={APP_DESC}
Exec={exec_cmd}
Icon={icon_path}
Terminal=false
Type=Application
Categories=Science;Utility;Engineering;DataVisualization;
MimeType={''.join(f'application/x-extension-{ext[1:]};' for ext in _get_supported_extensions())}
StartupWMClass=iqview
"""
    try:
        with open(desktop_file, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(desktop_file, 0o755)
        
        # Update desktop database
        subprocess.run(["update-desktop-database", desktop_dir], capture_output=True)
        
        # Set as default for all supported extensions
        desktop_filename = os.path.basename(desktop_file)
        for ext in _get_supported_extensions():
            mime_type = f"application/x-extension-{ext[1:]}"
            subprocess.run(["xdg-mime", "default", desktop_filename, mime_type], capture_output=True)
            
        scope = "All Users" if is_admin() else "Current User"
        print(f"  [OK] Desktop file created at {desktop_file} ({scope})")
    except Exception as e:
        print(f"  [X] Failed to create .desktop file: {e}")


def _uninstall_linux_desktop():
    print("Removing Linux .desktop file...")
    targets = [
        "/usr/share/applications/iqview.desktop",
        os.path.expanduser("~/.local/share/applications/iqview.desktop")
    ]
    removed = False
    for desktop_file in targets:
        if os.path.exists(desktop_file):
            try:
                os.remove(desktop_file)
                desktop_dir = os.path.dirname(desktop_file)
                subprocess.run(["update-desktop-database", desktop_dir], capture_output=True)
                print(f"  [OK] .desktop file removed from {desktop_file}")
                removed = True
            except Exception as e:
                print(f"  [X] Failed to remove .desktop file at {desktop_file}: {e}")

    # Remove symlink if present
    if os.path.islink("/usr/local/bin/iqview"):
        try:
            os.remove("/usr/local/bin/iqview")
            print("  [OK] Removed /usr/local/bin/iqview symlink")
        except Exception:
            pass

    if not removed:
        print("  - .desktop file not found")


def install_desktop_integration():
    """Entry point to install the desktop integration."""
    print(f"Installing {APP_NAME} desktop integration...")
    exe_path = get_executable_path()
    icon_path = get_icon_path()
    
    if not os.path.exists(exe_path):
        print(f"Warning: Executable not found at {exe_path}. Shortcut may not work unless the path is correct.")

    _sync_script_and_path(exe_path)
        
    if os.name == "nt":
        _create_shortcut(exe_path, icon_path)
        _register_file_associations(exe_path, icon_path)
    elif sys.platform.startswith("linux"):
        _install_linux_desktop(exe_path, icon_path)
    else:
        print(f"Desktop integration is not yet supported for your platform ({sys.platform}).")
        
    print("Desktop integration installation complete.")


def uninstall_desktop_integration():
    """Entry point to uninstall the desktop integration."""
    print(f"Uninstalling {APP_NAME} desktop integration...")
    if os.name == "nt":
        _remove_shortcut()
        _unregister_file_associations()
    elif sys.platform.startswith("linux"):
        _uninstall_linux_desktop()
    else:
        print(f"Desktop integration is not yet supported for your platform ({sys.platform}).")
        
    print("Desktop integration uninstallation complete.")


def install_mat_integration():
    """Register ONLY the .mat file association."""
    print(f"Registering .mat file association for {APP_NAME}...")
    exe_path = get_executable_path()
    icon_path = get_icon_path()
    
    if os.name == "nt":
        _register_file_associations(exe_path, icon_path, extensions=[".mat"])
    elif sys.platform.startswith("linux"):
        install_desktop_integration()
    else:
        print(f".mat association is currently only independently supported on Windows.")
        
    print(".mat association registration complete.")


def uninstall_mat_integration():
    """Unregister ONLY the .mat file association."""
    print(f"Unregistering .mat file association for {APP_NAME}...")
    if os.name == "nt":
        _unregister_file_associations(extensions=[".mat"])
    elif sys.platform.startswith("linux"):
        print("On Linux, .mat association is bundled with the main desktop integration.")
    else:
        print(f".mat association is currently only independently supported on Windows.")
        
    print(".mat association unregistration complete.")
