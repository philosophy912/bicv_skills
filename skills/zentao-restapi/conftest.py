import sys
from pathlib import Path

_root = Path(__file__).resolve().parent

# scripts/ directory for zentao_api module
sys.path.insert(0, str(_root / "scripts"))
