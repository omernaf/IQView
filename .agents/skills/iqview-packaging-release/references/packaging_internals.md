# IQView Packaging & Distribution Internals Reference

This document provides low-level technical specifications for packaging, Debian `.deb` archive generation, and desktop integration in IQView.

---

## 1. Debian Packaging Architecture ([`scripts/make_deb.py`](file:///d:/Projects/IQView/scripts/make_deb.py))

A Debian `.deb` file is an `ar` archive containing three files:
1. `debian-binary`: Plain text containing `2.0\n`.
2. `control.tar.gz`: Tarball containing package control metadata (`control`, `postinst`, `prerm`).
3. `data.tar.gz`: Tarball containing installed filesystem payloads (`/opt/iqview/`, `/usr/share/applications/iqview.desktop`, `/usr/share/icons/hicolor/256x256/apps/iqview.png`).

---

## 2. Critical Gotchas in `.deb` Creation

### 2.1 TarInfo Byte Length vs. Character Count
```python
# CORRECT:
postinst_bytes = postinst_content.encode('utf-8')
p_info = tarfile.TarInfo("postinst")
p_info.size = len(postinst_bytes)  # Byte count in UTF-8
tar.addfile(p_info, io.BytesIO(postinst_bytes))

# BUGGY:
# p_info.size = len(postinst_content)  # Character count truncates file on multi-byte UTF-8!
```

### 2.2 Private Network pip Resolution
When `sudo dpkg -i` runs, `HOME` is often reset or unreliable:
```bash
# Resolve invoking user's config via SUDO_USER
if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    INVOKER_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
    CANDIDATES="$INVOKER_HOME/.config/pip/pip.conf $INVOKER_HOME/.pip/pip.conf"
fi
```

### 2.3 Host Qt Library Collision Prevention
To avoid symbol mismatches (`Version Qt_6_PRIVATE_API symbol mismatch`) between host desktop themes and bundled PyQt6:
```bash
#!/bin/bash
export QT_QPA_PLATFORMTHEME=""
export QT_STYLE_OVERRIDE=""
exec "/opt/iqview/venv/bin/iqview" "$@"
```

---

## 3. Desktop Integration ([`iqview/utils/desktop.py`](file:///d:/Projects/IQView/iqview/utils/desktop.py))

- Windows: Creates `.lnk` shortcuts with canonical `APP_USER_MODEL_ID = "OmerNaf.IQView.<version>"`.
- Registry File Associations: Registers `.iq`, `.bin`, `.mat` extensions under `HKCU\Software\Classes` (or `HKLM` when run elevated).
- Linux: Installs `/usr/share/applications/iqview.desktop` and updates MIME database (`update-mime-database`).
