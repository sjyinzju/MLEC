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
        from scripts.experiment_framework.audit import verify_market
        print('Frozen artifacts:',verify_market())
    elif a.command=='govern-macro':
        p.error('Legacy macro writer retired. Maintain v5 through scripts.final_data_foundation.')
    elif a.command=='validate-data':
        from scripts.final_data_foundation.practical_validate import build
        from scripts.experiment_framework.validate_interface import build as validate_interface
        build();validate_interface()
    elif a.command=='build-dataset':
        from scripts.experiment_framework.dataset import build_dataset
        d=build_dataset();print('v5 feature bindings:',len(d),'(no data copies written)')
    elif a.command=='benchmark':
        from scripts.experiment_framework.runner import benchmark
        result=benchmark(a.config);print('Completed',result['run_id'],'predictions',result['predictions'])
    else:
        from scripts.experiment_framework.runner import evaluate
        print('Evaluated',evaluate()['run_id'])

if __name__=='__main__':main()
