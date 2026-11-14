"""Allow the verified local DuckDB runtime in this Windows checkout.

A standard installation of requirements-research.txt needs no local copy.
"""
from pathlib import Path
import sys
local=Path(__file__).resolve().parents[1]/'.local_deps'
if local.is_dir():sys.path.insert(0,str(local))
