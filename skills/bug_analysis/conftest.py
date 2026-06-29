import sys
from pathlib import Path

_root = Path(__file__).resolve().parent

# scripts/ directory for bug_analysis module
sys.path.insert(0, str(_root / "scripts"))
