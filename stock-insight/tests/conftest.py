import os
import sys

# 让 tests/ 里可以直接 import core.xxx（core 是 namespace package，无需 __init__.py）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
