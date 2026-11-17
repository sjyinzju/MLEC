"""Allow the verified local DuckDB runtime in this Windows checkout.

A standard installation of requirements-research.txt needs no local copy.
"""
from pathlib import Path
import sys
local=Path(__file__).resolve().parents[1]/'.local_deps'
if local.is_dir():sys.path.insert(0,str(local))

def pytest_sessionfinish(session,exitstatus):
    """Refresh formal interface test identity only for an unfiltered full suite."""
    import json
    from scripts.market_state.release import code_hash,file_hash
    from scripts.market_state.common import ROOT,REPORT
    required={'test_market_state.py','test_model_io.py','test_paired_losses.py'}
    files={Path(str(item.fspath)).name for item in session.items}
    options=session.config.option
    if not required<=files or options.keyword or options.markexpr or getattr(options,'lf',False):return
    reporter=session.config.pluginmanager.get_plugin('terminalreporter')
    passed=len(reporter.stats.get('passed',[])) if reporter else 0
    record=dict(exit_code=int(exitstatus),summary=[str(passed)+' passed'],interface_code_hash=code_hash(),
        test_files={p.relative_to(ROOT).as_posix():file_hash(p) for p in sorted((ROOT/'tests').glob('*.py'))})
    path=REPORT/'model_io/test_results.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(record,indent=2),encoding='utf8')
