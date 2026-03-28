import os
import sys
import subprocess
def _get_supported_extensions():
    """
    Returns a unified list of supported extensions by merging 
    built-in factory defaults with current settings.
    """
    # Baseline factory-supported extensions
    exts = {
        ".32f", ".64f", ".16tc", ".16sc", ".64fc", ".32fc", 
        ".bin", ".iq", ".sigmf", ".sigmf-data", ".mat"
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

def get_executable_path():
    """
    Returns the path to the application executable/script.
    """
    python_dir = os.path.dirname(sys.executable)
    
    if os.name == "nt":
        # Windows-specific search: look for .exe in python dir or Scripts
        scripts_dir = os.path.join(python_dir, "Scripts")
        for name in ["iqview-gui.exe", "iqview.exe"]:
            for d in [python_dir, scripts_dir]:
                exe_path = os.path.join(d, name)
                if os.path.exists(exe_path):
                    return exe_path
        return os.path.join(scripts_dir, "iqview-gui.exe")
    else:
        # Linux/POSIX: look for scripts in the same directory as python interpreter
        for name in ["iqview-gui", "iqview"]:
            exe_path = os.path.join(python_dir, name)
            if os.path.exists(exe_path):
                return exe_path
        # Fallback to just the command name
        return "iqview-gui"

def get_icon_path():
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

def _create_shortcut(exe_path, icon_path):
    print("Creating Start Menu shortcut...")
    start_menu_dir = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs")
    shortcut_path = os.path.join(start_menu_dir, f"{APP_NAME}.lnk")
    
    # We use PowerShell's WScript.Shell COM object to create a shortcut without requiring pywin32 module
    ps_cmd = (
        f"$wshell = New-Object -ComObject WScript.Shell; "
        f"$shortcut = $wshell.CreateShortcut('{shortcut_path}'); "
        f"$shortcut.TargetPath = '{exe_path}'; "
        f"$shortcut.IconLocation = '{icon_path}'; "
        f"$shortcut.Description = 'High-performance Static RF Spectrogram Viewer'; "
        f"$shortcut.Save();"
    )
    
    result = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
    if result.returncode == 0:
        print(f"  \u2713 Shortcut created at {shortcut_path}")
    else:
        print(f"  \u2717 Failed to create shortcut: {result.stderr}")

def _register_file_associations(exe_path, icon_path, extensions=None):
    import winreg
    print("Registering file associations...")
    command = f'"{exe_path}" "%1"'
    
    if extensions is None:
        extensions = _get_supported_extensions()
    
    try:
        # 1. Register the ProgID
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, fr"Software\Classes\{APP_PROG_ID}") as key:
            winreg.SetValue(key, "", winreg.REG_SZ, APP_DESC)
            
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, fr"Software\Classes\{APP_PROG_ID}\DefaultIcon") as key:
            # Append ,0 to the icon path (standard for DefaultIcon)
            winreg.SetValue(key, "", winreg.REG_SZ, f"{icon_path},0")
            
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, fr"Software\Classes\{APP_PROG_ID}\shell\open\command") as key:
            winreg.SetValue(key, "", winreg.REG_SZ, command)
            
        # 2. Register specified file extensions to the ProgID
        for ext in extensions:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, fr"Software\Classes\{ext}") as key:
                winreg.SetValue(key, "", winreg.REG_SZ, APP_PROG_ID)
            
            # Also set the icon directly for the extension (can help with immediate refresh)
            try:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, fr"Software\Classes\{ext}\DefaultIcon") as key:
                    winreg.SetValue(key, "", winreg.REG_SZ, f"{icon_path},0")
            except Exception:
                pass
                
            print(f"  \u2713 Associated {ext}")
                
        # 3. Notify Windows shell to update icons/associations
        # Using PowerShell to call SHChangeNotify
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
        print("  \u2713 Registered file associations successfully")
    except Exception as e:
        print(f"  \u2717 Failed to register file associations: {e}")

def _remove_shortcut():
    print("Removing Start Menu shortcut...")
    start_menu_dir = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs")
    shortcut_path = os.path.join(start_menu_dir, f"{APP_NAME}.lnk")
    
    try:
        if os.path.exists(shortcut_path):
            os.remove(shortcut_path)
            print("  \u2713 Shortcut removed")
        else:
            print("  - Shortcut not found")
    except Exception as e:
        print(f"  \u2717 Failed to remove shortcut: {e}")

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
        
    try:
        # 1. Unregister specified file extensions (if they pointed to our ProgID)
        for ext in extensions:
            try:
                # We do not want to delete the .ext key entirely, just the default association if it matches us
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, fr"Software\Classes\{ext}", 0, winreg.KEY_ALL_ACCESS) as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    if val == APP_PROG_ID:
                        winreg.DeleteValue(key, "")
                        print(f"  \u2713 Unassociated {ext}")
            except OSError:
                pass # Doesn't exist or not set as default
                
        # 2. Delete the ProgID if it's a full unregister (no extensions specified)
        if extensions == _get_supported_extensions():
            _delete_reg_key(winreg.HKEY_CURRENT_USER, fr"Software\Classes\{APP_PROG_ID}")
            print("  \u2713 Unregistered ProgID")
        
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
        print(f"  \u2717 Failed to unregister file associations: {e}")

def _install_linux_desktop(exe_path, icon_path):
    print("Creating Linux .desktop file...")
    desktop_dir = os.path.expanduser("~/.local/share/applications")
    os.makedirs(desktop_dir, exist_ok=True)
    desktop_file = os.path.join(desktop_dir, f"{APP_NAME.lower()}.desktop")
    
    # Simple setup for handling command line args and icon
    content = f"""[Desktop Entry]
Name={APP_NAME}
Comment={APP_DESC}
Exec="{exe_path}" %f
Icon={icon_path}
Terminal=false
Type=Application
Categories=Science;Utility;Engineering;DataVisualization;
MimeType={''.join(f'application/x-extension-{ext[1:]};' for ext in _get_supported_extensions())}
StartupWMClass=iqview
"""
    try:
        with open(desktop_file, "w") as f:
            f.write(content)
        # Make the desktop file executable
        os.chmod(desktop_file, 0o755)
        
        # Update desktop database
        subprocess.run(["update-desktop-database", desktop_dir], capture_output=True)
        
        # Set as default for all supported extensions
        desktop_filename = os.path.basename(desktop_file)
        for ext in _get_supported_extensions():
            mime_type = f"application/x-extension-{ext[1:]}"
            subprocess.run(["xdg-mime", "default", desktop_filename, mime_type], capture_output=True)
            
        print(f"  \u2713 Desktop file created at {desktop_file}")
    except Exception as e:
        print(f"  \u2717 Failed to create .desktop file: {e}")

def _uninstall_linux_desktop():
    print("Removing Linux .desktop file...")
    desktop_file = os.path.expanduser(f"~/.local/share/applications/{APP_NAME.lower()}.desktop")
    if os.path.exists(desktop_file):
        try:
            os.remove(desktop_file)
            desktop_dir = os.path.dirname(desktop_file)
            subprocess.run(["update-desktop-database", desktop_dir], capture_output=True)
            print("  \u2713 .desktop file removed")
        except Exception as e:
            print(f"  \u2717 Failed to remove .desktop file: {e}")
    else:
        print("  - .desktop file not found")

def install_desktop_integration():
    """Entry point to install the desktop integration."""
    print(f"Installing {APP_NAME} desktop integration...")
    exe_path = get_executable_path()
    icon_path = get_icon_path()
    
    if not os.path.exists(exe_path):
        print(f"Warning: Executable not found at {exe_path}. Shortcut may not work unless the path is correct.")
        
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
        # Since _get_supported_extensions() now includes .mat, 
        # we can just run/rerun the main desktop integration to ensure it's registered.
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
        # On Linux, .mat is part of the standard .desktop file.
        # Rerunning install_desktop_integration would keep it there.
        # For now, we inform the user it's bundled.
        print("On Linux, .mat association is bundled with the main desktop integration.")
    else:
        print(f".mat association is currently only independently supported on Windows.")
        
    print(".mat association unregistration complete.")
