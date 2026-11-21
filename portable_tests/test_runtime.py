import json
import numpy as np
from scripts.market_state.common import ROOT
from scripts.market_state.framework import DataStore,load_dataset
from scripts.market_state.model_contract import fit_inputs,transform_inputs,fit_context
from scripts.market_state.target_adapters import fit_targets
from scripts.market_state.experiments.portable import verify_package


def test_fixed_package_and_source_proof():
    m=verify_package(ROOT)
    assert m['acceptance_scopes']['source']=='SOURCE_FULL_PYTEST'


def test_sealed_input_target_prediction_contracts():
    store=DataStore()
    for task in ['classification','regression']:
        args=dict(market_id='000985.SH',information_set='M+Z',task=task,fold_id='2020-01',store=store)
        train=load_dataset(**args,role='train');pred=load_dataset(**args,role='prediction')
        pre=fit_inputs(train);target=fit_targets(train)
        assert pred.y is None
        assert np.isfinite(transform_inputs(pre,pred)).all().all()
        if task=='regression':np.testing.assert_allclose(target.inverse_transform(target.transform(train.y)),train.y,rtol=1e-12,atol=1e-24)


def test_real_macro_specification_modules_and_no_duplicates():
    from scripts.final_data_foundation.macro_contract import specifications
    from scripts.market_state.macro import feature_specifications
    from scripts.market_state.common import digest
    reference=json.loads((ROOT/'macro_contract_identity.json').read_text(encoding='utf8'))
    base,features=specifications(),feature_specifications()
    assert len({s['series_id'] for s in features})==len(features)
    assert digest(base)==reference['base_digest'] and digest(features)==reference['feature_digest']
    assert [s for s in features if s.get('required',True)]==json.loads((ROOT/'data/market_state/macro/specifications.json').read_text(encoding='utf8'))
