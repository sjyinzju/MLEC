"""Contract tests use only transformations and explicitly artificial output arrays."""
from dataclasses import replace,asdict
import json
import numpy as np
import pandas as pd
import pytest
from scripts.market_state.common import OUT,CORE,KEY,clock
from scripts.market_state.framework import DataStore,load_dataset,information_view,target_view
from scripts.market_state.model_contract import *
from scripts.market_state.target_adapters import *
from scripts.market_state.preprocessing import FoldPreprocessor

@pytest.fixture(scope='module')
def store():return DataStore()


def ds(store,task='regression',role='train',fold='2023-01',info='M+Z'):
    return load_dataset(market_id='000985.SH',fold_id=fold,role=role,task=task,information_set=info,store=store)


def test_components_and_pairing(store):
    a=ds(store);b=information_view(a,'M',store=store);validate_pair(a,b)
    pd.testing.assert_frame_equal(pd.concat([a.X_market,a.X_macro],axis=1),a.X)
    pd.testing.assert_frame_equal(b.X,ds(store,info='M').X)
    assert list(a.y)==CORE and len(a.target_schema['dimensions'])==5
    for info in store.spec['sets']:
        v=information_view(a,info,store=store);validate_pair(a,v)
        assert list(v.X)==store.spec['by_market']['000985.SH'][info]


def test_prediction_does_not_open_truth_or_manifest(store,monkeypatch):
    original=store.get
    def get(name):
        if name in ['supervised_targets','sample_manifest']:raise AssertionError('Future table read')
        return original(name)
    monkeypatch.setattr(store,'get',get)
    p=ds(store,role='prediction',fold='2026-11')
    assert p.y is None and len(p.X)==2 and p.metadata.prediction_eligible.all()
    assert not any(c in p.metadata for c in ['label_end','eligible','label_available_at'])


def test_prediction_unchanged_when_truth_is_mutated(store):
    before=ds(store,role='prediction',fold='2026-11');saved=store.get('supervised_targets')
    try:
        store.tables['supervised_targets']=saved.assign(future_state_id=999,**{c:999. for c in CORE})
        after=ds(store,role='prediction',fold='2026-11')
        pd.testing.assert_frame_equal(before.X,after.X);pd.testing.assert_frame_equal(before.metadata,after.metadata)
    finally:store.tables['supervised_targets']=saved


def test_fold_preprocessor_and_target_serialization(store,tmp_path):
    train=ds(store);test=ds(store,role='test');pre=fit_inputs(train);target=fit_targets(train)
    a=transform_inputs(pre,test);pre.save(tmp_path/'input');target.save(tmp_path/'target.json')
    pre2=FoldPreprocessor.load(tmp_path/'input');target2=TargetAdapter.load(tmp_path/'target.json',context=pre.fit_context_)
    pd.testing.assert_frame_equal(a,transform_inputs(pre2,test))
    np.testing.assert_array_equal(target.transform(test.y),target2.transform(test.y))
    np.testing.assert_allclose(target.inverse_transform(target.transform(test.y)),test.y,rtol=ROUNDTRIP_RTOL,atol=ROUNDTRIP_ATOL)


def test_no_heldout_statistics_and_shared_columns(store):
    train=ds(store);test=ds(store,role='test');before=fit_inputs(train);target=fit_targets(train)
    schema=json.dumps(before.schema_,sort_keys=True);parameters=json.dumps(target.parameters_,sort_keys=True)
    modified=replace(test,X=(test.X*1e6).astype(test.X.dtypes.to_dict()),y=test.y*1e6)
    # Standalone transform is still train-fitted, even with adversarial held-out numbers.
    before.transform(modified.X);target.transform(modified.y)
    assert schema==json.dumps(before.schema_,sort_keys=True) and parameters==json.dumps(target.parameters_,sort_keys=True)
    m=information_view(train,'M',store=store);p=fit_inputs(m)
    restricted=before.subset(m.feature_names)
    np.testing.assert_array_equal(p.transform(m.X),restricted.transform(m.X))
    assert target.adapter_version_==fit_targets(m).adapter_version_


def test_tiny_and_constant_regression_scales(store):
    train=ds(store);y=pd.DataFrame({c:[1e-30,2e-30,3e-30,4e-30,5e-30] for c in CORE})
    y['drawdown']=.1;y['volatility']=[1.,1.,1.,1.,2.]
    ctx=replace(fit_context(train),training_target_hash=truth_hash(y))
    t=RegressionTargetAdapter(train.target_schema).fit(y,ctx)
    assert t.parameters_['scale'][3]<1e-29 and not t.parameters_['constant'][3]
    assert t.parameters_['constant'][2]
    assert t.parameters_['scale_method'][1]=='STD'
    np.testing.assert_allclose(t.inverse_transform(t.transform(y)),y,rtol=ROUNDTRIP_RTOL,atol=1e-45)
    assert t.parameters_['weight'][3]==pytest.approx(1/np.sqrt(2))


def test_nominal_missing_empty_and_unseen():
    a=pd.DataFrame({'current_state_id':[1.,2.,np.nan],'value':[1.,2.,3.],'empty':[np.nan]*3,'constant':[2.]*3})
    b=pd.DataFrame({'current_state_id':[9.,np.nan],'value':[4.,np.nan],'empty':[5.,8.],'constant':[3.,4.]})
    p=FoldPreprocessor().fit(a);v=p.transform(b);names=p.get_feature_names_out().tolist()
    assert 'empty' not in names and 'constant' not in names
    assert v[0,names.index('current_state_id==UNSEEN')]==1 and v[1,names.index('current_state_id==MISSING')]==1
    assert v[0,names.index('missing__empty')]==0


def test_class_mapping_missing_and_probability_alignment(store,tmp_path):
    train=ds(store,task='classification');y=train.y[train.y.future_state_id.ne(0)].reset_index(drop=True)
    ctx=replace(fit_context(train),training_target_hash=truth_hash(y))
    a=ClassificationTargetAdapter(train.target_schema).fit(y,ctx)
    assert a.parameters_['missing_classes']==[0]
    np.testing.assert_array_equal(a.inverse_transform(a.transform(y)),y.future_state_id)
    p=a.align_probabilities([[.7,.3]],[2,1],missing_policy='zero_for_absent')
    np.testing.assert_array_equal(p,[[0.,.3,.7]])
    with pytest.raises(ValueError):a.align_probabilities([[.7,.3]],[2,1],missing_policy='error')
    a.save(tmp_path/'target.json');b=TargetAdapter.load(tmp_path/'target.json');assert b.parameters_==a.parameters_
    with pytest.raises(ValueError):fit_targets(ds(store,task='probability'))


@pytest.mark.parametrize('bad',[[[.5,.4,.0]],[[1.1,-.1,0]],[[np.nan,0,1]],[[1,0]],[[.5,.5,.00000002]]])
def test_probability_errors(bad):
    with pytest.raises(ValueError):validate_probabilities(bad,[0,1,2])


def test_outputs_and_evaluation_association(store):
    train=ds(store,task='classification');test=ds(store,task='classification',role='test')
    pre=fit_inputs(train);adapter=fit_targets(train)
    ctx=prediction_context(test,pre,adapter,model_id='ARTIFICIAL_TEST_ONLY',model_version='test-stub')
    p=np.tile([.2,.6,.2],(len(test.X),1));o=classification_output(ctx,np.ones(len(p),dtype=int),p,train.target_schema)
    validate_output(o,ctx,task='classification',schema=train.target_schema)
    assert len(evaluation_pairs(o,test,ctx,task='classification',schema=train.target_schema))==len(test.X)
    for column,value in [('fold_id','wrong'),('information_set','M'),('data_version','wrong'),('market_id','wrong')]:
        bad=o.copy();bad[column]=value
        with pytest.raises(ValueError):validate_output(bad,ctx,task='classification',schema=train.target_schema)
    with pytest.raises(ValueError):classification_output(ctx,np.zeros(len(p),dtype=int),p,train.target_schema)
    with pytest.raises(ValueError):validate_output(o.iloc[::-1],ctx,task='classification',schema=train.target_schema)
    with pytest.raises(ValueError):validate_output(pd.concat([o,o.iloc[:1]]),ctx,task='classification',schema=train.target_schema)
    reg=ds(store);rt=ds(store,role='test');rp=fit_inputs(reg);ra=fit_targets(reg)
    rc=prediction_context(rt,rp,ra,model_id='ARTIFICIAL_TEST_ONLY',model_version='test-stub')
    values=pd.DataFrame(np.zeros((len(rt.X),7)),columns=CORE);values['drawdown']=-.2
    ro=regression_output(rc,values,rt.target_schema)
    assert ro.predicted_drawdown.eq(-.2).all() and ro.economic_bound_violations.eq('["drawdown"]').all()
    validate_output(ro,rc,task='regression',schema=rt.target_schema)
    with pytest.raises(ValueError):regression_output(rc,values[CORE[::-1]],rt.target_schema)
    with pytest.raises(ValueError):regression_output(rc,values.assign(amihud=np.inf),rt.target_schema)


def test_input_context_and_maturity_errors(store):
    train=ds(store);test=ds(store,role='test');p=fit_inputs(train)
    with pytest.raises(ValueError):transform_inputs(p,information_view(test,'M',store=store))
    with pytest.raises(ValueError):p.transform(test.X[test.X.columns[::-1]])
    with pytest.raises(ValueError):p.transform(test.X.astype('float32'))
    with pytest.raises(ValueError):FoldPreprocessor().transform(test.X)
    with pytest.raises(ValueError):RegressionTargetAdapter().transform(test.y)
    m=train.metadata.copy();m['label_available_at']=clock('2099-01-01')
    with pytest.raises(ValueError):fit_context(replace(train,metadata=m))
    with pytest.raises(ValueError):fit_inputs(test)
    bad=replace(test,versions=dict(test.versions,data_version='wrong'))
    with pytest.raises(ValueError):transform_inputs(p,bad)
    with pytest.raises(ValueError):validate_dataset(replace(test,X=test.X.assign(future_state_id=1)))
    with pytest.raises(ValueError):validate_dataset(replace(test,keys=test.keys.iloc[::-1].reset_index(drop=True)))


def test_explicit_analysis_and_fail_closed_seal(store,monkeypatch,tmp_path):
    from scripts.market_state import release
    monkeypatch.setattr(release,'RELEASE',tmp_path)
    with pytest.raises(RuntimeError,match='seal'):DataStore()
    assert len(load_dataset(market_id='000985.SH',view='analysis').X)>0
    with pytest.raises(ValueError):fit_inputs(load_dataset(market_id='000985.SH',view='analysis'))


def test_fixed_evaluation_scale_and_package_manifest(store):
    scale=evaluation_scale(market_id='000985.SH',store=store)
    assert scale['source_fold']=='initial' and scale['fit_cutoff'].startswith('2019-12-31')
    d=ds(store);p=fit_inputs(d);a=fit_targets(d)
    manifest=package_manifest(p,a,ModelCapabilities('RBF-SVM','regression','per_target'),model_version='future-template')
    assert manifest['estimator_created'] is False and 'estimator' in manifest['components']

@pytest.mark.parametrize('market', ['000985.SH','000300.SH','000905.SH','000852.SH'])
@pytest.mark.parametrize('task', ['classification','probability'])
def test_target_views_reuse_authoritative_keyed_chain(store,market,task):
    args=dict(market_id=market,information_set='M+Z',fold_id='2023-01',role='test',store=store)
    original=load_dataset(**args,task='regression')
    projected=target_view(original,task,store=store);direct=load_dataset(**args,task=task)
    pd.testing.assert_frame_equal(projected.X,direct.X);pd.testing.assert_frame_equal(projected.y,direct.y)
    pd.testing.assert_frame_equal(projected.metadata,direct.metadata)


def test_internal_time_validation_and_adapter_version_errors(store,tmp_path):
    outer=ds(store);cut=clock('2020-12-31')
    trkeys=outer.keys[outer.metadata.label_available_at.le(cut)].reset_index(drop=True)
    vakeys=outer.keys[outer.metadata.asof_date.between('2021-01-01','2021-01-31')].reset_index(drop=True)
    train=training_partition(outer,trkeys,role='train',fit_cutoff=cut)
    val=training_partition(outer,vakeys,role='validation',fit_cutoff=cut)
    p=fit_inputs(train);a=fit_targets(train)
    assert len(transform_inputs(p,val))==len(vakeys)
    assert len(a.transform(val.y))==len(vakeys)
    with pytest.raises(ValueError):training_partition(outer,vakeys,role='train',fit_cutoff=cut)
    with pytest.raises(ValueError):training_partition(ds(store,role='test'),vakeys,role='train',fit_cutoff=cut)
    a.save(tmp_path/'target.json')
    wrong=asdict(fit_context(outer));wrong['versions']=dict(wrong['versions'],target_version='wrong')
    with pytest.raises(ValueError):TargetAdapter.load(tmp_path/'target.json',context=wrong)
    p.save(tmp_path/'pre');file=tmp_path/'pre/input_schema.json';r=json.loads(file.read_text());r['output_dtype']='float32';file.write_text(json.dumps(r))
    with pytest.raises(ValueError):FoldPreprocessor.load(tmp_path/'pre')


def test_regression_evaluation_requires_fixed_initial_scale(store):
    train=ds(store);test=ds(store,role='test');pre=fit_inputs(train);adapter=fit_targets(train)
    ctx=prediction_context(test,pre,adapter,model_id='ARTIFICIAL_TEST_ONLY',model_version='test-stub')
    output=regression_output(ctx,pd.DataFrame(np.zeros((len(test.X),7)),columns=CORE),test.target_schema)
    with pytest.raises(ValueError):prepare_evaluation(output,test,EvaluationContext(ctx,'regression'))
    scale=evaluation_scale(market_id='000985.SH',store=store)
    assert len(prepare_evaluation(output,test,EvaluationContext(ctx,'regression',scale)))==len(test.X)


def test_transformed_input_boundary_and_output_schema(store):
    train=ds(store);pre=fit_inputs(train);X=transform_inputs(pre,train)
    validate_model_input(X,pre.schema_,keys=train.keys)
    for bad in [X[X.columns[::-1]],X.astype('float32'),X.iloc[:-1],X.assign(**{X.columns[0]:np.nan})]:
        with pytest.raises(ValueError):validate_model_input(bad,pre.schema_,keys=train.keys)
    schema=prediction_schema('regression',train.target_schema)
    assert [c for c in schema['columns'] if c.startswith('predicted_')]==['predicted_'+c for c in CORE]
    with pytest.raises(ValueError):package_manifest(pre,fit_targets(train),ModelCapabilities('CatBoost','classification','not_applicable'),model_version='template')
