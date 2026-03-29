"""Scaffold registry for A/B tests.

Each scaffold module exposes:
  SCAFFOLD_FILES: dict[str, str]
  SHARED_PROMPT: str
  REPO_NAME: str
  REPO_ID: str
  MAX_TURNS: int
  create_scaffold(base_dir: Path) -> Path
"""
from . import simple, multistage, nightmare
from . import complex as complex_

SCAFFOLDS: dict = {
    "simple": simple,
    "multistage": multistage,
    "complex": complex_,
    "nightmare": nightmare,
}
