"""Allow the verified local DuckDB runtime in this Windows checkout.

A standard installation of requirements-research.txt needs no local copy.
"""
from pathlib import Path
import sys
local=Path(__file__).resolve().parents[1]/'.local_deps'
if local.is_dir():sys.path.insert(0,str(local))

import pytest

@pytest.fixture(autouse=True)
def prohibit_real_supervised_fit(monkeypatch):
    """Ordinary pytest is a non-training boundary, including future model tests."""
    from sklearn.linear_model import LogisticRegression, ElasticNet, LassoLars, SGDClassifier, SGDRegressor
    from sklearn.svm import SVC, SVR
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from scripts.market_state.models.calibration import TimeSigmoid
    from scripts.market_state.models.elastic_net import AugmentedLarsElasticNet
    def forbidden(*args, **kwargs):
        raise AssertionError('Real supervised fit/partial_fit is forbidden in ordinary pytest; use a non-learning stub')
    for estimator in [LogisticRegression, ElasticNet, LassoLars, SGDClassifier, SGDRegressor, SVC, SVR,
                      RandomForestClassifier, RandomForestRegressor]:
        for name in ['fit', 'partial_fit']:
            if hasattr(estimator, name):monkeypatch.setattr(estimator,name,forbidden)
    monkeypatch.setattr(TimeSigmoid, 'optimize', forbidden)
    monkeypatch.setattr(TimeSigmoid, 'polish', forbidden)
    monkeypatch.setattr(AugmentedLarsElasticNet, 'polish', forbidden)

def pytest_sessionfinish(session,exitstatus):
    """Refresh formal interface test identity only for an unfiltered full suite."""
    import json
    from scripts.market_state.release import code_hash,file_hash
    from scripts.market_state.common import ROOT,REPORT
    from scripts.market_state.experiments.runtime import experiment_code_hash
    if (ROOT/'package.manifest.json').exists():
        return  # Portable subsets NEVER replace source-workspace proof.
    required={p.name for p in (ROOT/'tests').glob('test_*.py')}
    files={Path(str(item.fspath)).name for item in session.items}
    options=session.config.option
    if not required<=files or options.keyword or options.markexpr or getattr(options,'lf',False) or getattr(options,'deselect',[]) or options.collectonly or any('::' in a for a in session.config.args):return
    reporter=session.config.pluginmanager.get_plugin('terminalreporter')
    passed=len(reporter.stats.get('passed',[])) if reporter else 0
    from scripts.market_state.experiments.runtime import environment
    record=dict(receipt_kind='SOURCE_FULL_PYTEST',collected=len(session.items),node_ids=[i.nodeid for i in session.items],
        environment=environment(),exit_code=int(exitstatus),passed=passed,summary=[str(passed)+' passed'],interface_code_hash=code_hash(),
        experiment_code_hash=experiment_code_hash(), real_supervised_fit_calls=0, real_calibration_fit_calls=0, smoke_runs=0,
        verification='ordinary pytest blocks real supervised estimators; integration uses non-learning stubs',
        test_files={p.relative_to(ROOT).as_posix():file_hash(p) for p in sorted((ROOT/'tests').glob('*.py'))})
    path=REPORT/'model_io/test_results.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(record,indent=2),encoding='utf8')
