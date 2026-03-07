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
