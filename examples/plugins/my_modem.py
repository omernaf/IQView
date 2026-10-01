"""my_modem — IQView Plugin Chain

Pipeline: Channelizer + Energy Detector → FSK Demodulator → Sync Word Slicer → Block FEC Decoder → XOR Mask → CRC Checker
"""

from __future__ import annotations

from iqview import PluginChain

PLUGIN_NAME        = 'my_modem'
PLUGIN_DESCRIPTION = 'Channelizer + Energy Detector → FSK Demodulator → Sync Word Slicer → Block FEC Decoder → XOR Mask → CRC Checker'
PLUGIN_CATEGORY    = 'Chains'

CHAIN = PluginChain([
    ('Channelizer + Energy Detector', {
        'channel_spacing': 500000.0,
        'ref_channel_fc': 0.0,
        'overlap': 0.0,
        'threshold_db': 6.0,
        'L': 8,
        'alpha_low': 0.001,
        'alpha_high': 0.005,
        'm': 70,
        'n': 115,
        'chunk_size': 10000,
        'init_chunks': 3,
        'margin': 0,
        'debug': False,
    }),
    ('FSK Demodulator', {
        'baud_rate': 0.0,
        'invert_bits': False,
        'trim_edges': True,
        'max_hover_bits': 64,
        'debug_plots': False,
    }),
    ('Sync Word Slicer', {
        'uw_hex': '0xB57E',
        'min_match_pct': 90.0,
        'max_search_bits': 512,
        'allow_inverted': True,
    }),
    ('Block FEC Decoder', {
        'code': 'Custom G Matrix',
        'custom_g_matrix': '1101000, 0110100, 1110010, 1010001',
    }),
    ('XOR Mask', {
        'preset': 'Alternating (0xAA)',
        'mask_hex': '0xAA',
        'bit_order': 'msb_first',
    }),
    ('CRC Checker', {
        'preset': 'Custom',
        'poly_hex': '0x1021',
        'crc_bits': 16,
        'init_hex': '0x0000',
        'xorout_hex': '0x0000',
        'refin': False,
        'refout': False,
        'rev8': False,
        'crc_position': 'end',
        'crc_endianness': 'auto',
    }),
])
