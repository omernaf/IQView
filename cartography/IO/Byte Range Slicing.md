---
type: io
tags:
  - code/io
  - invariant
file: iqview/main.py
title: "Byte Range Slicing"
---

# ✂️ Byte Range Slicing

Permits loading arbitrary byte offsets from large files via `--start-byte`, `--stop-byte`, or `--bytes START:STOP`.

---

## ⚡ Alignment Safety Mandate

Because start and stop byte offsets can be arbitrary numbers (e.g. 17-byte header offset on 8-byte `complex64` samples):
- **Always truncate trailing unaligned bytes** prior to passing the buffer to `numpy.frombuffer`.
- Passing unaligned slices throws `ValueError: buffer size must be a multiple of element size`.

```python
item_size = np.dtype(dtype).itemsize * (2 if is_complex else 1)
valid_bytes = (len(raw_bytes) // item_size) * item_size
aligned_samples = np.frombuffer(raw_bytes[:valid_bytes], dtype=dtype)
```

---

## 🔗 Related Notes
- [[MOC - IO and Formats]]
- [[Binary IQ Loaders]]
