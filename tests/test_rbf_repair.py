"""Analytic calibration controls and real Windows spawn/file-sharing regressions."""
import os
import time
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import pandas as pd
import pytest
from scripts.market_state.models.calibration import local_optimality,sigmoid_objective
from scripts.market_state.experiments.artifacts import atomic_json,atomic_parquet,read_json


def _writer(root, worker):
    from pathlib import Path
    for i in range(16):
        atomic_json(Path(root)/'same.json',dict(worker=worker,values=[worker]*20,iteration=i))
        atomic_parquet(Path(root)/'same.parquet',pd.DataFrame({'worker':[worker]*20,'iteration':[i]*20}))
    return worker


def _hold_windows(path,ready,observed):
    import ctypes
    from ctypes import wintypes
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    api.CreateFileW.restype=wintypes.HANDLE
    h=api.CreateFileW(str(path),0x80000000,1,None,3,0x02000000,None)
    assert h!=ctypes.c_void_p(-1).value
    ready.set();assert observed.wait(10)
    time.sleep(.1)
    api.CloseHandle.argtypes=[wintypes.HANDLE];api.CloseHandle(h)


def test_curvature_scale_is_not_sufficient_for_acceptance():
    # Nearly unidentified slope: small absolute gradient, large descent in the
    # low-curvature direction. A lambda_max-only threshold could accept this.
    x=np.linspace(-1e-8,1e-8,100);t=np.where(x>0,.8,.2)
    q=local_optimality(np.zeros(2),x,t,1e-8)
    assert not q['accepted']
    assert not q['rigorous_global_certificate']
    assert q['null_gradient']>q['null_gradient_roundoff'] or q['newton_decrement']>8*q['objective_resolution']


def test_true_stationary_point_and_obvious_descent_control():
    x=np.linspace(-1,1,80);target=np.full(80,.2)
    good=np.array([0.,np.log(.2/.8)])
    q=local_optimality(good,x,target,1e-8)
    assert q['accepted'] and q['newton_decrement']<1e-20
    assert not local_optimality(np.array([2.,2.]),x,target,1e-8)['accepted']


def test_atomic_real_spawn_same_destination(tmp_path):
    with ProcessPoolExecutor(4,mp_context=mp.get_context('spawn')) as pool:
        assert sorted(pool.map(_writer,[str(tmp_path)]*4,range(4)))==list(range(4))
    r=read_json(tmp_path/'same.json');assert r['values']==[r['worker']]*20
    frame=pd.read_parquet(tmp_path/'same.parquet')
    assert frame.worker.nunique()==1 and frame.iteration.nunique()==1
    assert not list(tmp_path.glob('*.partial'))


@pytest.mark.skipif(os.name!='nt',reason='Real Windows sharing semantics')
def test_real_windows_sharing_violation_retry(tmp_path,monkeypatch):
    from scripts.market_state.experiments import artifacts
    target=tmp_path/'occupied.json';atomic_json(target,{'old':True})
    context=mp.get_context('spawn');ready,observed=context.Event(),context.Event()
    child=context.Process(target=_hold_windows,args=(str(target),ready,observed));child.start()
    assert ready.wait(10)
    original=artifacts.os.replace;errors=[]
    def traced(a,b):
        try:return original(a,b)
        except OSError as e:
            errors.append(getattr(e,'winerror',None));observed.set();raise
    monkeypatch.setattr(artifacts.os,'replace',traced)
    try:atomic_json(target,{'new':True})
    finally:observed.set();child.join(10)
    assert child.exitcode==0 and errors and set(errors)<= {5,32,33}
    assert read_json(target)=={'new':True}


def test_permanent_errors_are_not_retried(tmp_path,monkeypatch):
    from scripts.market_state.experiments import artifacts
    calls=[]
    def permanent(*args):
        calls.append(1);raise OSError(28,'No space')
    monkeypatch.setattr(artifacts.os,'replace',permanent)
    with pytest.raises(OSError):atomic_json(tmp_path/'target.json',{'a':1})
    assert len(calls)==1 and not list(tmp_path.glob('*.partial'))


@pytest.mark.skipif(os.name!='nt',reason='Real Windows readonly access denial')
def test_real_permanent_readonly_denial_is_immediate(tmp_path,monkeypatch):
    import ctypes
    from scripts.market_state.experiments import artifacts
    target=tmp_path/'readonly.json';atomic_json(target,{'old':1})
    assert ctypes.windll.kernel32.SetFileAttributesW(str(target),1)
    original=artifacts.os.replace;attempts=[]
    def traced(a,b):attempts.append(1);return original(a,b)
    monkeypatch.setattr(artifacts.os,'replace',traced)
    try:
        with pytest.raises(PermissionError):atomic_json(target,{'new':1})
        assert len(attempts)==1
    finally:ctypes.windll.kernel32.SetFileAttributesW(str(target),128)
