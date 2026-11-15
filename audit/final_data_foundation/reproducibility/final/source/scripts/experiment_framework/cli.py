"""Explicit development-only command entry point."""
import os
for name in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']:os.environ[name]='1'
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import argparse
from scripts.experiment_framework.common import ROOT,write_json

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['audit','govern-macro','validate-data','build-dataset','benchmark','evaluate']);p.add_argument('--stage',choices=['development'],default='development');p.add_argument('--config',type=Path,default=ROOT/'config/experiments/development.json');a=p.parse_args()
    if a.command=='audit':
        from scripts.experiment_framework.audit import snapshot,verify_market
        snapshot();print('Frozen artifacts:',verify_market())
    elif a.command=='govern-macro':
        from scripts.macro_pipeline.govern import build
        print('Macro fact rows:',len(build()))
    elif a.command=='validate-data':
        import pandas as pd
        from scripts.macro_pipeline.govern import validate_facts
        from scripts.experiment_framework.audit import verify_market
        validate_facts(pd.read_parquet(ROOT/'data/standardized/macro/macro_facts.parquet'));verify_market()
        from scripts.experiment_framework.common import read_json
        print('Structure/integrity valid; macro gate:',read_json(ROOT/'audit/framework/macro_gate.json')['core_eligible'])
    elif a.command=='build-dataset':
        from scripts.experiment_framework.dataset import build_dataset
        d=build_dataset();print('Market eligible:',int(d.included_market.sum()),'Core eligible:',int(d.included_core.sum()))
    elif a.command=='benchmark':
        from scripts.experiment_framework.runner import benchmark
        result=benchmark(a.config);print('Completed',result['run_id'],'predictions',result['predictions'])
    else:
        from scripts.experiment_framework.runner import evaluate
        print('Evaluated',evaluate()['run_id'])

if __name__=='__main__':main()
