"""Read-only verification of existing frozen research artifacts."""
from .common import ROOT, digest, read_json


def verify_market():
    records = read_json(ROOT/'data/metadata/frozen_integrity_hashes.json')
    for path, record in records.items():
        if digest(ROOT/path) != record['sha256']:
            raise ValueError('Frozen artifact changed: '+path)
    return len(records)


if __name__ == '__main__':
    print('Frozen artifacts verified:', verify_market())
