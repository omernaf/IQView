import iqview
import numpy as np

filename = "samples/mavic_air_2.16tc"
iq_data = np.fromfile(filename, dtype=np.int16).reshape(-1, 2)
iq_data = iq_data[:, 0] + 1j * iq_data[:, 1]
iq_data = iq_data.astype(np.complex64) / 32768.0  # Normalize to [-1, 1]
iqview.view(iq_data, fs=50e6)

