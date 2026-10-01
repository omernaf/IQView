"""testing/test_hover_formatting.py

Tests for overlay hover text formatting, backward compatibility, and
the Overlay Inspector dialog (Markdown, HTML, and plain-text modes).
"""

from __future__ import annotations

import unittest
from PyQt6.QtWidgets import QApplication, QPushButton, QTextBrowser

from iqview.overlays import Overlay, OverlayShape, Rect
from iqview.ui.overlay_inspector import OverlayInspectorDialog


app = QApplication.instance() or QApplication([])


class TestHoverFormatting(unittest.TestCase):
    """Test get_truncated_hover behavior across text formats."""

    def test_plain_text_backward_compatibility(self):
        """Plain text hover strings must remain pure plain text without HTML wrappers."""
        plain = "Channel 01\nCenter: 1575.420 MHz\nBandwidth: 100.0 kHz\nPower: -12.4 dB"
        ov = Rect(t_start=0.0, f_start=1e6, t_end=1.0, f_end=2e6, hover_str=plain)
        tip = ov.get_truncated_hover()

        self.assertNotIn("<html", tip.lower())
        self.assertNotIn("<!doctype", tip.lower())
        self.assertIn("Channel 01", tip)
        self.assertIn("Bandwidth: 100.0 kHz", tip)

    def test_markdown_tooltip_rendering(self):
        """Markdown hover strings must convert to rich HTML with table and CSS styling."""
        md = (
            "### GPS L1 C/A - Satellite Constellation Fix\n\n"
            "- **RF Carrier:** 1575.42 MHz | **SVs Acquired:** 2\n\n"
            "| PRN | Quality | C/N0 | Doppler (Obs) |\n"
            "| :--- | :--- | :--- | :--- |\n"
            "| PRN 01 | STRONG | 46.5 dB-Hz | +7800 Hz |\n"
            "| PRN 11 | NOMINAL | 41.2 dB-Hz | +8100 Hz |\n"
        )
        ov = Rect(t_start=0.0, f_start=1e6, t_end=1.0, f_end=2e6, hover_str=md)
        tip = ov.get_truncated_hover()

        self.assertIn("<table", tip.lower())
        self.assertIn("<style", tip.lower())
        self.assertIn("PRN 01", tip)

    def test_metadata_fallback_when_hover_empty(self):
        """When hover_str is empty but metadata exists, creates a compact key-value preview."""
        ov = Rect(
            t_start=0.0,
            f_start=1e6,
            t_end=1.0,
            f_end=2e6,
            metadata={"protocol": "FSK", "baud_rate": 9600, "snr_db": 18.5},
        )
        tip = ov.get_truncated_hover()

        self.assertIn("protocol: FSK", tip)
        self.assertIn("baud_rate: 9600", tip)
        self.assertIn("Inspect Overlay", tip)


class TestOverlayInspectorDialog(unittest.TestCase):
    """Test OverlayInspectorDialog rich rendering and raw toggle."""

    def test_inspector_plain_text(self):
        """Plain text overlays display as plain text with monospace font, without toggle button."""
        plain = "FSK: 100 kBd\nBits: 10101010\nHex: AA"
        ov = Rect(t_start=0.0, f_start=1e6, t_end=1.0, f_end=2e6, hover_str=plain)
        dlg = OverlayInspectorDialog(ov)

        tb = dlg.findChild(QTextBrowser, "hover_browser")
        self.assertIsNotNone(tb)
        self.assertEqual(tb.toPlainText().strip(), plain.strip())

        # No 'Show Raw' button should be added for plain text
        raw_buttons = [b for b in dlg.findChildren(QPushButton) if b.text() in ("Show Raw", "Show Formatted")]
        self.assertEqual(len(raw_buttons), 0)

    def test_inspector_markdown_toggle(self):
        """Markdown overlays render formatted by default and can toggle between formatted and raw view."""
        md = (
            "### GPS L1 C/A - Fix\n\n"
            "- **Carrier:** 1575.42 MHz\n\n"
            "| PRN | C/N0 |\n"
            "| :--- | :--- |\n"
            "| PRN 01 | 46.5 dB-Hz |\n"
        )
        ov = Rect(t_start=0.0, f_start=1e6, t_end=1.0, f_end=2e6, hover_str=md)
        dlg = OverlayInspectorDialog(ov)

        tb = dlg.findChild(QTextBrowser, "hover_browser")
        self.assertIsNotNone(tb)

        # Initially formatted (no raw '###' header prefix in plain view)
        self.assertNotIn("###", tb.toPlainText())
        self.assertIn("GPS L1 C/A - Fix", tb.toPlainText())

        # Locate toggle button
        toggle_buttons = [b for b in dlg.findChildren(QPushButton) if b.text() == "Show Raw"]
        self.assertEqual(len(toggle_buttons), 1)
        btn_toggle = toggle_buttons[0]

        # Click to toggle to Raw
        btn_toggle.click()
        self.assertEqual(btn_toggle.text(), "Show Formatted")
        self.assertIn("### GPS L1 C/A - Fix", tb.toPlainText())
        self.assertIn("| PRN | C/N0 |", tb.toPlainText())

        # Click to toggle back to Formatted
        btn_toggle.click()
        self.assertEqual(btn_toggle.text(), "Show Raw")
        self.assertNotIn("###", tb.toPlainText())


if __name__ == "__main__":
    unittest.main()
