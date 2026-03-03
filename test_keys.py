from PyQt6.QtGui import QKeySequence
from PyQt6.QtCore import Qt

def test():
    # Test standalone modifiers
    keys = [Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift]
    mods = [Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.AltModifier, Qt.KeyboardModifier.ShiftModifier]
    names = ["Control", "Alt", "Shift"]
    
    names = ["Ctrl", "Alt", "Shift", "Control"]
    for n in names:
        seq = QKeySequence(n)
        print(f"String '{n}' -> Sequence: '{seq.toString()}'")

if __name__ == "__main__":
    test()
