"""Data-interface report only; never regenerate historical experiment reports."""
from .common import ROOT, read_json


def build():
    report = read_json(ROOT/'data/metadata/experiment_interface_validation.json')
    print('Data interface:', report['status'])
    print('Data completeness:', read_json(ROOT/'data/metadata/remaining_gaps.json')['status'])
    return report


if __name__ == '__main__':
    build()
