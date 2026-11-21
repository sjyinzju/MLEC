"""Diagnostic only: native error state immediately following real rename failures."""
from pathlib import Path
from contextlib import contextmanager
import time
import json
import sys,ctypes,os,tempfile,multiprocessing
from concurrent.futures import ProcessPoolExecutor
ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from scripts.market_state.experiments import artifacts

def probe(root,worker):
    spans=[];failures=[];lock=artifacts._atomic_writer
    @contextmanager
    def measured(path):
        with lock(path):
            start=time.perf_counter_ns()
            try:yield
            finally:spans.append((start,time.perf_counter_ns(),worker))
    artifacts._atomic_writer=measured
    original=artifacts.os.replace
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
    api.CreateFileW.restype=ctypes.c_void_p
    api.CloseHandle.argtypes=[ctypes.c_void_p]
    nt=ctypes.WinDLL('ntdll');nt.RtlGetLastNtStatus.restype=ctypes.c_uint32
    def traced(a,b):
        try:return original(a,b)
        except OSError as e:
            status=nt.RtlGetLastNtStatus();details=[]
            for path in [a,b]:
                h=api.CreateFileW(str(path),0x10000,7,None,3,0x02000000,None)
                error=ctypes.get_last_error() if h==ctypes.c_void_p(-1).value else 0
                if not error:api.CloseHandle(h)
                details.append((str(path),error))
            failures.append(dict(pid=os.getpid(),winerror=e.winerror,ntstatus=hex(status),probes=details))
            raise
    artifacts.os.replace=traced
    try:
        for i in range(120):artifacts.atomic_json(Path(root)/'same.json',dict(worker=worker,iteration=i))
        return dict(worker=worker,spans=spans,failures=failures,success=True)
    except OSError:return dict(worker=worker,spans=spans,failures=failures,success=False)

if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='mlec-atomic-diagnose-') as root:
        with ProcessPoolExecutor(4,mp_context=multiprocessing.get_context('spawn')) as pool:
            results=list(pool.map(probe,[root]*4,range(4)))
            spans=sorted(s for r in results for s in r['spans'])
            overlaps=[(a,b) for a,b in zip(spans,spans[1:]) if a[1]>b[0]]
            summary=dict(success=[r['success'] for r in results],critical_sections=len(spans),overlaps=overlaps,
                recovered_native_errors=[e for r in results for e in r['failures']])
            (ROOT/'reports/model_build/rbf_svm/repair_20261121/atomic_probe.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
            print({k:v for k,v in summary.items() if k!='recovered_native_errors'},flush=True)
            assert all(summary['success']) and not overlaps
