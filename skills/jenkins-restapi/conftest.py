import sys
from pathlib import Path

_root = Path(__file__).resolve().parent

# scripts/ directory for jenkins_api + system_config modules
sys.path.insert(0, str(_root / "scripts"))
