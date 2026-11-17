"""Artificial predictions only: exercise the existing scoring chain without a model."""
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from scripts.market_state.common import CORE, KEY, clock
from scripts.market_state.framework import Dataset, paired_losses
from scripts.market_state.model_contract import (CONTRACT_VERSION, IDENTITY, PredictionContext,
    target_schema, classification_output, regression_output, evaluation_pairs)
from scripts.market_state.evaluation import multiclass_losses, continuous_losses


def artificial_scores(task='classification',metric='log_loss'):
    schema=target_schema()
    versions=dict(data_version='ARTIFICIAL_DATA',feature_version='ARTIFICIAL_FEATURES',
        target_version='ARTIFICIAL_TARGETS',dictionary_version=schema['dictionary_version'],contract_version=CONTRACT_VERSION)
    keys=pd.DataFrame(dict(market_id=['000985.SH']*2,asof_date=pd.to_datetime(['2023-01-06','2023-01-13']),horizon=[20]*2))
    truth_values=pd.DataFrame([[.01,.2,.02,1e-10,.02,.4,.3],[-.02,.3,.06,2e-10,.03,.6,.5]],columns=CORE)
    scores=[]
    for info in ['M','M+Z']:
        X=pd.DataFrame({'market__return_20d':[.01,.02]})
        if info=='M+Z':X['macro__pmi_mfg__latest']=[50.,51.]
        meta=keys.assign(asof_time=[clock(d) for d in keys.asof_date],fit_cutoff=str(clock('2022-12-30')))
        for c,v in versions.items():meta[c]=v
        y=pd.DataFrame({'future_state_id':[0,2]}) if task=='classification' else truth_values.copy()
        context=dict(market_id='000985.SH',fold_id='2023-01',role='test',information_set=info,
            quality='historical_reconstructed',view=None,versions=versions)
        truth=Dataset(X,y,meta,list(X),keys.copy(),X[[c for c in X if not c.startswith('macro__')]],
            X[[c for c in X if c.startswith('macro__')]],dict(columns=list(X),dtypes=X.dtypes.astype(str).to_dict()),schema,versions,context)
        ctx=PredictionContext(keys.copy(),'2023-01',str(clock('2022-12-30')),'ARTIFICIAL_TEST_ONLY',info,
            versions,'input-preprocessor-'+info,'same-target-adapter','model-weights-'+info,'historical_reconstructed')
        if task=='classification':
            p=np.array([[.6,.3,.1],[.1,.2,.7]]) if info=='M' else np.array([[.8,.1,.1],[.2,.2,.6]])
            predictions=classification_output(ctx,np.asarray(schema['class_ids'])[p.argmax(axis=1)],p,schema)
            scored=evaluation_pairs(predictions,truth,ctx,task=task,schema=schema)
            # Select metric only after attaching truth through the checked contract boundary.
            probabilities=scored[['predicted_state_prob_'+str(c) for c in schema['class_ids']]]
            scored['loss']=multiclass_losses(scored.future_state_id,probabilities,schema['class_ids'])[metric]
        else:
            values=truth_values.copy();values['return'] += [.03,-.04] if info=='M' else [.01,-.02]
            predictions=regression_output(ctx,values,schema)
            scored=evaluation_pairs(predictions,truth,ctx,task=task,schema=schema)
            original_predictions=scored[['predicted_'+c for c in CORE]]
            # Test one original-unit per-target loss, without an across-unit aggregation.
            scored['loss']=continuous_losses(scored[CORE],original_predictions)['absolute_error'][:,CORE.index('return')]
        scores.append(scored)
    return scores


@pytest.mark.parametrize('metric',['log_loss','brier'])
def test_artificial_classification_end_to_end_pairing(metric):
    left,right=artificial_scores(metric=metric)
    result=paired_losses(left,right.iloc[::-1],task='classification')
    assert 'label_version' not in left and not left.model_version.equals(right.model_version)
    assert not left.preprocessing_version.equals(right.preprocessing_version)
    pd.testing.assert_frame_equal(result[KEY],left[KEY])
    expected=np.log(np.array([.8/.6,.6/.7])) if metric=='log_loss' else [.20,-.10]
    np.testing.assert_allclose(result.loss_difference,expected,rtol=1e-12,atol=1e-15)


def test_artificial_seven_target_end_to_end_pairing():
    left,right=artificial_scores('regression')
    result=paired_losses(left,right,task='regression')
    np.testing.assert_allclose(result.loss_difference,[.02,.02],rtol=1e-12,atol=1e-15)


@pytest.mark.parametrize('column',KEY+IDENTITY+['fold_id','fit_cutoff','model_id','information_set','quality',
    'preprocessing_version','model_version','target_adapter_version','future_state_id','loss'])
def test_pairing_rejects_missing_contract_columns(column):
    left,right=artificial_scores()
    if column=='dictionary_version':right['label_version']=right[column]  # obsolete alias cannot rescue it
    with pytest.raises(ValueError,match='Missing'):paired_losses(left,right.drop(columns=column),task='classification')


@pytest.mark.parametrize('column',IDENTITY+['fold_id','fit_cutoff','model_id','quality','target_adapter_version','future_state_id'])
def test_pairing_rejects_identity_or_truth_mismatch(column):
    left,right=artificial_scores()
    right[column]=1 if column=='future_state_id' else str(clock('2022-12-29')) if column=='fit_cutoff' else 'wrong'
    with pytest.raises(ValueError,match='Unpaired'):paired_losses(left,right,task='classification')


@pytest.mark.parametrize('column',CORE)
def test_pairing_checks_all_seven_true_targets(column):
    left,right=artificial_scores('regression');right.loc[0,column]+=1
    with pytest.raises(ValueError,match='Unpaired'):paired_losses(left,right,task='regression')


def test_pairing_rejects_duplicate_keys_columns_and_different_samples():
    left,right=artificial_scores()
    cases=[pd.concat([right,right.iloc[:1]],ignore_index=True),right.iloc[:1],
        right.assign(asof_date=pd.to_datetime(['2023-01-06','2023-01-20'])),
        pd.concat([right,right[['loss']]],axis=1)]
    for bad in cases:
        with pytest.raises(ValueError):paired_losses(left,bad,task='classification')


@pytest.mark.parametrize('column,value',[('loss',np.inf),('loss',np.nan),('dictionary_version',None),('future_state_id',None)])
def test_pairing_rejects_nonfinite_loss_or_missing_identity_truth(column,value):
    left,right=artificial_scores();right[column]=value
    with pytest.raises(ValueError):paired_losses(left,right,task='classification')
