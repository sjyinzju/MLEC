"""Single data/label command surface. No prediction experiments."""
import argparse
import joblib
from .common import OUT, read

def main():
    p=argparse.ArgumentParser(description='market-state-research-v3.0 A-C')
    p.add_argument('command',choices=['collect','build','verify','report'])
    p.add_argument('--reuse-dictionary',action='store_true')
    p.add_argument('--force-sources',action='store_true')
    args=p.parse_args()
    if args.command=='collect':
        from .collect import collect
        collect();return
    if args.command=='build':
        from .sources import build_sources
        from .measure import build_measures
        from .dictionary import fit_dictionary
        from .macro import build_macro
        from .framework import build_framework
        build_sources(args.force_sources);build_measures()
        a=joblib.load(OUT/'state_dictionary/dictionary.joblib') if args.reuse_dictionary else fit_dictionary(read('future_window_outcomes'))
        build_macro();build_framework(a)
    if args.command in ['build','verify']:
        from .validation import verify
        print(verify(),flush=True)
    if args.command in ['build','report']:
        from .report import report
        report()

if __name__=='__main__':main()
