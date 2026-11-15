"""Shared paths, atomic artifacts and content identities; no source writes."""
from pathlib import Path
import hashlib
import json
import os
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TZ = 'Asia/Shanghai'

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()

def identity(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write_json(path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.partial')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding='utf-8')
    os.replace(tmp, path)

def save_frame(path, frame):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.parquet.partial')
    frame.to_parquet(tmp, index=False, compression='zstd'); os.replace(tmp, path)

def write_text(path, text):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
