import os
import sys
import subprocess
import winreg

# The file extensions we want to associate with IQView
SUPPORTED_EXTENSIONS = [
    ".32f", ".64f", ".16tc", ".16sc", ".64fc", ".32fc", 
    ".bin", ".iq", ".sigmf", ".sigmf-data"
]

APP_NAME = "IQView"
APP_PROG_ID = "IQView.File"
APP_DESC = "IQ Data File"

def get_executable_path():
    """
    Returns the path to the iqview.exe.
    When installed via pip, an iqview.exe is placed in the Python/Scripts folder.
    """
    python_dir = os.path.dirname(sys.executable)
    # Check if we are running the wrapper iqview.exe in Scripts
    # typically sys.executable is python.exe, but in venv it might be Scripts/python.exe
    exe_path = os.path.join(python_dir, "iqview.exe")
    
    # If not there, check Scripts folder explicitly (especially outside venv)
    if not os.path.exists(exe_path):
        scripts_dir = os.path.join(python_dir, "Scripts")
        alt_exe_path = os.path.join(scripts_dir, "iqview.exe")
        if os.path.exists(alt_exe_path):
            exe_path = alt_exe_path
            
    return exe_path

def get_icon_path():
    """Returns the path to the application icon."""
    try:
        import iqview
        pkg_dir = os.path.dirname(iqview.__file__)
        icon_path = os.path.join(pkg_dir, "resources", "logo.ico")
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

def _register_file_associations(exe_path, icon_path):
    print("Registering file associations...")
    command = f'"{exe_path}" "%1"'
    
    try:
        # 1. Register the ProgID
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, fr"Software\Classes\{APP_PROG_ID}") as key:
            winreg.SetValue(key, "", winreg.REG_SZ, APP_DESC)
            
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, fr"Software\Classes\{APP_PROG_ID}\DefaultIcon") as key:
            winreg.SetValue(key, "", winreg.REG_SZ, icon_path)
            
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, fr"Software\Classes\{APP_PROG_ID}\shell\open\command") as key:
            winreg.SetValue(key, "", winreg.REG_SZ, command)
            
        # 2. Register all file extensions to the ProgID
        for ext in SUPPORTED_EXTENSIONS:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, fr"Software\Classes\{ext}") as key:
                winreg.SetValue(key, "", winreg.REG_SZ, APP_PROG_ID)
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

def _unregister_file_associations():
    print("Unregistering file associations...")
    try:
        # 1. Unregister all file extensions (if they pointed to our ProgID)
        for ext in SUPPORTED_EXTENSIONS:
            try:
                # We do not want to delete the .ext key entirely, just the default association if it matches us
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, fr"Software\Classes\{ext}", 0, winreg.KEY_ALL_ACCESS) as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    if val == APP_PROG_ID:
                        winreg.DeleteValue(key, "")
                        print(f"  \u2713 Unassociated {ext}")
            except OSError:
                pass # Doesn't exist or not set as default
                
        # 2. Delete the ProgID
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

def install_desktop_integration():
    """Entry point to install the desktop integration."""
    if os.name != "nt":
        print("Error: Desktop integration is only supported on Windows.")
        return
        
    print(f"Installing {APP_NAME} desktop integration...")
    exe_path = get_executable_path()
    icon_path = get_icon_path()
    
    if not os.path.exists(exe_path):
        print(f"Warning: Executable not found at {exe_path}. Shortcut may not work unless the path is correct.")
        
    _create_shortcut(exe_path, icon_path)
    _register_file_associations(exe_path, icon_path)
    print("Desktop integration installation complete.")

def uninstall_desktop_integration():
    """Entry point to uninstall the desktop integration."""
    if os.name != "nt":
        print("Error: Desktop integration is only supported on Windows.")
        return
        
    print(f"Uninstalling {APP_NAME} desktop integration...")
    _remove_shortcut()
    _unregister_file_associations()
    print("Desktop integration uninstallation complete.")
