"""Portable subset proof, strictly separate from full source-workspace proof."""
from pathlib import Path
import pytest


@pytest.fixture(autouse=True)
def prohibit_training(monkeypatch):
    from sklearn.svm import SVC,SVR
    from scripts.market_state.models.calibration import TimeSigmoid
    def forbidden(*a,**k):
        raise AssertionError('Portable pytest never fits; use explicit TECHNICAL')
    for cls in [SVC,SVR]:monkeypatch.setattr(cls,'fit',forbidden)
    for name in ['optimize','polish']:monkeypatch.setattr(TimeSigmoid,name,forbidden)


def pytest_sessionfinish(session,exitstatus):
    from scripts.market_state.common import ROOT
    from scripts.market_state.experiments.artifacts import atomic_json
    from scripts.market_state.experiments.runtime import experiment_code_hash,environment
    from scripts.market_state.release import file_hash
    reporter=session.config.pluginmanager.get_plugin('terminalreporter')
    atomic_json(ROOT/'runtime_acceptance/portable_pytest.json',dict(
        receipt_kind='PORTABLE_SUBSET',exit_code=int(exitstatus),collected=len(session.items),
        passed=len(reporter.stats.get('passed',[])),node_ids=[i.nodeid for i in session.items],
        experiment_code_hash=experiment_code_hash(),environment=environment(),
        source_receipt_sha256=file_hash(ROOT/'reports/market_state/model_io/test_results.json'),
        scope='Runtime/seal/contracts/imports only; excludes raw collection/build tests; no training'))
