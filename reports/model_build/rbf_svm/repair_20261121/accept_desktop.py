"""Run the three delivered entry points and portable tests from their own root."""
from pathlib import Path
import argparse,json,os,subprocess,time,hashlib


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main(package):
    package=Path(package).resolve();output=package/'runtime_acceptance';output.mkdir(exist_ok=True)
    env=os.environ.copy()
    for name in ['PYTHONPATH','PYTHONHOME','MLEC_PYTHON','MLEC_ACTION']:env.pop(name,None)
    env.update(MLEC_NO_PAUSE='1',PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1')
    receipt=package/'reports/market_state/model_io/test_results.json';before=sha(receipt)
    manifest=json.loads((package/'package.manifest.json').read_text(encoding='utf8'))
    results=[]
    def run(label,args):
        start=time.monotonic();log=output/(label+'.log')
        with log.open('w',encoding='utf8') as handle:
            result=subprocess.run(args,cwd=package,env=env,stdout=handle,stderr=subprocess.STDOUT)
        record=dict(entry=label,arguments=args,exit_code=result.returncode,seconds=time.monotonic()-start,log_sha256=sha(log))
        results.append(record)
        (output/'entrypoints.json').write_text(json.dumps(dict(status='IN_PROGRESS',entries=results),indent=2),encoding='utf8')
        print(label,result.returncode,round(record['seconds'],2),flush=True)
        if result.returncode:raise RuntimeError('Entry failed: '+label+'; '+str(log))
    comspec=env.get('COMSPEC',r'C:\Windows\System32\cmd.exe')
    run('check_windows',[comspec,'/d','/c','CHECK_WINDOWS.cmd'])
    python=package/'.venv-rbf-svm/Scripts/python.exe'
    assert python.is_file()
    identity_code="import json; from scripts.market_state.common import ROOT; from scripts.market_state.experiments.runtime import experiment_code_hash,environment; print(json.dumps(dict(root=str(ROOT),code=experiment_code_hash(),environment=environment())))"
    identity=json.loads(subprocess.check_output([str(python),'-c',identity_code],cwd=package,env=env,text=True))
    assert Path(identity['root']).resolve()==package
    assert identity['code']==manifest['experiment_code_hash']
    run('portable_pytest',[str(python),'-m','pytest','-q'])
    run('technical_windows',[comspec,'/d','/c','TECHNICAL_WINDOWS.cmd','-CpuWorkers','2'])
    run('start_windows_plan_only',[comspec,'/d','/c','START_WINDOWS.cmd','-PlanOnly','-CpuWorkers','2'])
    run('integrity_after_entries',[str(python),'-m','scripts.market_state.experiments.portable','--verify','.'])
    preflight=json.loads((output/'preflight.json').read_text(encoding='utf8'))
    subset=json.loads((output/'portable_pytest.json').read_text(encoding='utf8'))
    technical=json.loads((output/'technical.json').read_text(encoding='utf8'))
    assert preflight['status']=='PREFLIGHT_PASSED' and preflight['supervised_fit_calls']==0
    assert subset['receipt_kind']=='PORTABLE_SUBSET' and subset['exit_code']==0 and subset['passed']==subset['collected']
    assert technical['status']=='PASSED' and not technical['formal_BC_started']
    assert not list((package/'results/rbf_svm').glob('*/manifest.json'))
    assert sha(receipt)==before==manifest['source_test_receipt_sha256']
    result=dict(status='PASSED',entries=results,identity=identity,source_receipt_unchanged=True,
        source_receipt_sha256=before,source_repository_PYTHONPATH_used=False,new_package_local_venv=True,
        formal_BC_started=False,START_scope='actual .cmd entry with -PlanOnly; formal fitting not executed')
    (output/'entrypoints.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('package');main(**vars(parser.parse_args()))
