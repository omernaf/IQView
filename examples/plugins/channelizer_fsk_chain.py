"""channelizer_fsk_chain.py — Example IQView PluginChain

Demonstrates chaining the built-in `Channelizer + Energy Detector` with the
`FSK Demodulator` in a declarative `.py` pipeline.

Step 1 channelizes the wideband signal, detects active bursts per channel,
and attaches the downconverted/decimated complex baseband IQ (`o.iq`, `o.fs`)
to each `Rect` overlay.
Step 2 automatically receives those `Rect` overlays in memory, demodulates
each burst using its cached `o.iq`, and updates the overlay labels, tooltips,
and metadata with the decoded bit/hex sequences!
"""

from __future__ import annotations

from iqview import PluginChain

PLUGIN_NAME        = "Channelize + FSK Demod (Chain)"
PLUGIN_DESCRIPTION = (
    "2-step chain: Channelizer + Energy Detector → FSK Demodulator "
    "(detects bursts per channel and decodes 2-FSK bits/hex)."
)
PLUGIN_CATEGORY    = "Chains"

CHAIN = PluginChain([
    ("Channelizer + Energy Detector", {
        "channel_spacing": 25000.0,
        "ref_channel_fc": 0.0,
        "overlap": 0.0,
        "threshold_db": 6.0,
        "debug": False,
    }),
    ("FSK Demodulator", {
        "baud_rate": 0.0,
        "invert_bits": False,
        "debug_plots": False,
    }),
])
