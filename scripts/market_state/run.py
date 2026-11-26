"""Single data/label command surface. No prediction experiments."""
import argparse
from pathlib import Path
import joblib
from .common import OUT, read

def main():
    p=argparse.ArgumentParser(description='market-state-research-v3.0 A-C')
    p.add_argument('command',choices=['collect','build','verify','report','preflight','accept','reproduce','seal','interface-preflight','build-60d'])
    p.add_argument('--reuse-dictionary',action='store_true')
    p.add_argument('--force-sources',action='store_true')
    p.add_argument('--data-root',type=Path)
    p.add_argument('--receipt-dir',type=Path)
    p.add_argument('--information-set',action='append')
    p.add_argument('--stock-cache',type=Path)
    p.add_argument('--output',type=Path)
    p.add_argument('--rebuild-inputs',action='store_true',help='rebuild all historical inputs for the 60d study')
    args=p.parse_args()
    if args.rebuild_inputs and args.command!='build-60d':p.error('--rebuild-inputs requires build-60d')
    if args.command=='interface-preflight':
        from .tasks import interface_preflight
        interface_preflight(data_root=args.data_root,receipt_dir=args.receipt_dir,
            information_sets=args.information_set);return
    if args.command=='build-60d':
        if args.stock_cache is None or args.output is None:p.error('build-60d needs --stock-cache and --output')
        from .framework import DataStore
        from .horizons import build_60d
        print(build_60d(DataStore(args.data_root),args.stock_cache,args.output,rebuild_inputs=args.rebuild_inputs));return
    if any(v is not None for v in [args.data_root,args.receipt_dir,args.information_set,args.stock_cache,args.output]):
        p.error('Scoped paths and information sets apply to build-60d and interface-preflight')
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
