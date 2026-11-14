"""Data-only foundation paths and evidence-preserving source snapshots."""
from pathlib import Path
import sys
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.experiment_framework.common import ROOT,digest,identity,read_json,write_json,save_frame,write_text

VERSION='data-foundation-v3.0.0'
AUDIT=ROOT/'audit/data_foundation_v3'
CONFIG=ROOT/'config/data'
RAW=ROOT/'data/raw/macro/official_sources/v3'
STANDARD=ROOT/'data/standardized/macro/v3'
FEATURES=ROOT/'data/features/v3'
DATASETS=ROOT/'data/datasets/foundation_v3'
METADATA=ROOT/'data/metadata/foundation_v3'
TZ='Asia/Shanghai'

def now():return pd.Timestamp.now(tz=TZ).isoformat()

def local(path):
    p=(ROOT/path).resolve()
    if not p.is_relative_to(ROOT):raise ValueError('Output escapes project')
    return p
