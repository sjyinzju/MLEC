"""Single data/label command surface. No prediction experiments."""
import argparse
import joblib
from .common import OUT, read

def main():
    p=argparse.ArgumentParser(description='market-state-research-v3.0 A-C')
    p.add_argument('command',choices=['collect','build','verify','report','preflight','accept','reproduce','seal'])
    p.add_argument('--reuse-dictionary',action='store_true')
    p.add_argument('--force-sources',action='store_true')
    args=p.parse_args()
    from .release import begin
    begin()
    if args.command=='collect':
        from .collect import collect
        collect();return
    if args.command=='build':
        from .sources import build_sources
        from .measure import build_measures
        from .dictionary import ensure_dictionary
        from .macro import build_macro
        from .framework import build_framework
        from .formal import build_policy
        build_sources(args.force_sources);build_policy();build_measures()
        a=ensure_dictionary(read('future_window_outcomes'))
        build_macro();build_framework(a)
        from .tasks import expand
        expand()
    if args.command in ['build','verify']:
        from .validation import verify
        print(verify(),flush=True)
    if args.command in ['build','report']:
        from .report import report
        report()
    if args.command=='preflight':
        from .tasks import preflight
        preflight()
    if args.command=='accept':
        from .acceptance import verify_acceptance
        print(verify_acceptance(),flush=True)
    if args.command=='seal':
        from .release import seal
        seal()
    if args.command=='reproduce':
        from .release import verify_rebuild
        print('Reproducible products',verify_rebuild(),flush=True)

if __name__=='__main__':main()
