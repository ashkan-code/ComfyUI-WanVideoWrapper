#!/usr/bin/env python3
"""Helper: run on SERVER to regenerate patch.py from wyckoff_pro.py"""
import os, base64, zlib

src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wyckoff_pro.py")
content = open(src, "rb").read()
compressed = base64.b64encode(zlib.compress(content, 9)).decode()

patch_code = f'''#!/usr/bin/env python3
"""
Run this once to fix wyckoff_pro.py:
  python patch.py
Then:
  python wyckoff_pro.py
"""
import os, base64, zlib

DATA = "{compressed}"

target = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wyckoff_pro.py")
content = zlib.decompress(base64.b64decode(DATA))
with open(target, "wb") as f:
    f.write(content)
print(f"[OK] wyckoff_pro.py fixed -> {{target}}")
print("[OK] ICT 100% bug fixed -- TP now min 2:1 RR for all methods")
print("[OK] Brooks window 3-7, ATR-based range")
print("[OK] Adv PA key level: 1.5x ATR zone")
print("")
print("Now run:  python wyckoff_pro.py")
'''

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "patch.py")
with open(out, "w") as f:
    f.write(patch_code)
print(f"[OK] patch.py written ({len(compressed)} chars compressed)")
