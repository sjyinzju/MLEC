from pathlib import Path
import sys
import json
import hashlib
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.local_deps'))
import duckdb

VERSION = 'market-state-research-v3.0'
OUT = ROOT / 'data/market_state'
REPORT = ROOT / 'reports/market_state'
BASE = ROOT / 'data/standardized/market/v4'
KEY = ['market_id', 'asof_date', 'horizon']
MARKETS = {'000985.SH': 'All A shares', '000300.SH': 'Large',
           '000905.SH': 'Medium', '000852.SH': 'Smaller'}
CORE = ['return', 'volatility', 'drawdown', 'amihud', 'turnover', 'breadth', 'correlation']

def write(path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf8')

def frame(name, df):
    path = OUT / (name + '.parquet'); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.partial'); df.to_parquet(tmp, index=False, compression='zstd'); tmp.replace(path)

def read(name):
    return pd.read_parquet(OUT / (name + '.parquet'))

def clock(d):
    return pd.Timestamp(d).tz_localize('Asia/Shanghai') + pd.Timedelta(hours=18)

def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()

def db():
    c = duckdb.connect(); c.execute('SET threads=2'); c.execute("SET memory_limit='3GB'");c.execute('SET enable_progress_bar=false')
    tmp = OUT / 'cache/temp'; tmp.mkdir(parents=True, exist_ok=True)
    c.execute('SET temp_directory=?', [str(tmp)])
    return c
