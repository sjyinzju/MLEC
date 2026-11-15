"""Verifiable contracts, real-date causality, and exact feature lineage checks."""
import json
import numpy as np
import pandas as pd
from .common import ROOT,STANDARD,FEATURES,DATASETS,AUDIT,METADATA,read_json,write_json,digest
from .features import make_weekly,LEVELS
from .audit import verify_protected


def market_compatibility():
    """Replay frozen data transformations with the saved thresholds, in memory."""
    import sys
    import importlib.util
    sys.path.insert(0,str(ROOT/'.local_deps'))
    def module(name,path):
        spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
    common=module('_market_readonly_common',ROOT/'scripts/research_v2/common.py')
    previous=sys.modules.get('common');sys.modules['common']=common
    try:core=module('_market_readonly_core',ROOT/'scripts/research_v2/core.py')
    finally:
        if previous is None:sys.modules.pop('common',None)
        else:sys.modules['common']=previous
    from .common import read_json
    folder=ROOT/'data/research_v2';clean=pd.read_parquet(folder/'market_daily_clean.parquet')
    cal=pd.read_parquet(ROOT/'data/metadata/market/sse_calendar.parquet')
    thr=read_json(ROOT/'config/research_v2/thresholds.json')
    obs=core.observations(clean)
    state,ep=core.all_events(obs,core.states(obs,thr))
    features,outcomes,targets,mapping=core.build_weekly(obs,state,ep,cal,thr)
    ep=core.event_opportunities(ep,features,targets,mapping,obs.date)
    plan,folds=core.temporal_folds(features,targets,cal)
    rebuilt={'market_observations_daily':obs,'state_labels_daily':state,'risk_episodes':ep,'market_features_weekly':features,
       'future_outcomes_weekly':outcomes,'prediction_targets_weekly':targets,'sample_to_event':mapping,'fold_membership':folds}
    from io import BytesIO
    def artifact_frame(d):
        # Reproduce Parquet's object -> Arrow string round trip before comparing
        # the saved schema. No values or numeric tolerances are changed.
        buffer=BytesIO();d.to_parquet(buffer,index=False);buffer.seek(0);return pd.read_parquet(buffer)
    resolution_casts=[]
    def compare(d,expected,name):
        actual=artifact_frame(d)
        for c in actual:
            if pd.api.types.is_datetime64_any_dtype(actual[c]) and actual[c].dtype!=expected[c].dtype:
                cast=actual[c].astype(expected[c].dtype)
                assert (cast.eq(actual[c])|cast.isna()&actual[c].isna()).all()
                resolution_casts.append({'table':name,'column':c,'from':str(actual[c].dtype),'to':str(expected[c].dtype)})
                actual[c]=cast
        pd.testing.assert_frame_equal(actual,expected.reset_index(drop=True),check_exact=True)
    for name,d in rebuilt.items():compare(d,pd.read_parquet(folder/(name+'.parquet')),name)
    compare(plan,pd.read_parquet(ROOT/'data/metadata/market/fold_manifest.parquet'),'fold_manifest')
    result={'status':'PASS','replayed_tables':{n:len(d) for n,d in rebuilt.items()},'thresholds':'read frozen values; no threshold re-estimation','writes_to_old_outputs':False,'lossless_timestamp_resolution_casts':resolution_casts}
    write_json(AUDIT/'market_compatibility.json',result);return result

def lineage_check():
    f=pd.read_parquet(STANDARD/'macro_facts.parquet')
    if f.source_record_id.duplicated().any():raise AssertionError('Source record ID must uniquely identify a fact')
    index=f.set_index('source_record_id');total=0;derived=0
    # Scalar record lookup avoids constructing a pandas frame for every feature
    # cell while preserving the same availability, scope, quality and value checks.
    records=index[['series_id','value','research_available_at','quality_status','certification_status']].to_dict('index')
    for level in LEVELS:
        line=pd.read_parquet(FEATURES/level/'macro_lineage.parquet');wide=pd.read_parquet(FEATURES/level/'macro_weekly.parquet').set_index('sample_id')
        for x in line.itertuples(index=False):
            ids=json.loads(x.source_record_ids);observed=wide.at[x.sample_id,x.feature]
            assert (pd.isna(observed) and pd.isna(x.value)) or observed==x.value
            if not ids:
                assert pd.isna(x.value);continue
            p=[records[i] for i in ids]
            assert all(r['research_available_at']<=x.asof_time for r in p)
            assert all(r['quality_status'] in LEVELS[level] for r in p)
            assert all(r['series_id']==x.series_id for r in p)
            assert all(r['certification_status']!='VALUE_CONFLICT' for r in p)
            suffix=x.feature.rsplit('__',1)[-1]
            expected=p[-1]['value'] if suffix in ['latest','previous'] else p[-1]['value']-p[0]['value'] if suffix=='change' else (x.asof_time-p[-1]['research_available_at']).total_seconds()/86400
            assert np.isclose(expected,x.value,rtol=0,atol=1e-10)
            total+=1
    for x in f.itertuples(index=False):
        ids=json.loads(x.parent_record_ids)
        if ids:
            p=index.loc[ids];assert p.research_available_at.le(x.research_available_at).all()
            value=p.value.iloc[0]-p.value.iloc[1] if x.series_id=='term_spread_10y_1y' else p.value.iloc[0]
            assert np.isclose(x.value,value,rtol=0,atol=1e-10);derived+=1
    from .reproduce import output_hashes
    result={'status':'PASS','nonmissing_feature_lineages_verified':total,'derived_facts_verified':derived,'validated_output_hashes':output_hashes()}
    write_json(AUDIT/'lineage_validation.json',result);return result

def causality_check(f=None):
    f=f if f is not None else pd.read_parquet(STANDARD/'macro_facts.parquet')
    market=pd.read_parquet(ROOT/'data/research_v2/market_features_weekly.parquet');checks=[]
    from .requirements import specifications
    selected=[s['series_id'] for s in specifications()]
    for date in ['2020-04-17','2022-04-29','2025-02-14']:
        cutoff=pd.Timestamp(date+' 18:00',tz='Asia/Shanghai');m=market[market.asof_time.le(cutoff)].tail(2)
        full,_=make_weekly(f,m,'conservative',selected)
        truncated,_=make_weekly(f[f.research_available_at.le(cutoff)].copy(),m,'conservative',selected)
        pd.testing.assert_frame_equal(full,truncated)
        changed=f.copy();changed.loc[changed.research_available_at.gt(cutoff),'value']+=999999
        perturbed,_=make_weekly(changed,m,'conservative',selected);pd.testing.assert_frame_equal(full,perturbed)
        checks.append({'cutoff':str(cutoff),'samples':m.sample_id.tolist(),'series_tested':selected,'truncated_equals_full':True,'future_value_perturbation_invariant':True})
    # The contemporaneous Jan-2025 M2 reprint is not available at 18:00 on its
    # publication date under the explicit end-of-day policy.
    q=f[(f.series_id=='m2_yoy')&(f.period_end==pd.Timestamp('2025-01-31'))&f.quality_status.eq('conservative_release_reconstructed')]
    assert len(q) and q.research_available_at.gt(pd.Timestamp('2025-02-14 18:00',tz='Asia/Shanghai')).all()
    return checks

def validate():
    f=pd.read_parquet(STANDARD/'macro_facts.parquet');checks={}
    checks['finite_values']=bool(np.isfinite(f.value).all())
    checks['unique_record_ids']=not bool(f.source_record_id.duplicated().any())
    checks['timezone_timestamps']=all(str(f[c].dtype).endswith('Asia/Shanghai]') for c in ['release_at','research_available_at','retrieved_at'])
    checks['latest_not_backdated']=bool(f.loc[f.quality_status.eq('latest_vintage_reconstructed'),'research_available_at'].ge(f.loc[f.quality_status.eq('latest_vintage_reconstructed'),'retrieved_at']).all())
    checks['no_unregistered_groups']=not bool(f.series_group.eq('unregistered').any())
    checks['evidence_present']=all((ROOT/p).exists() for p in f.evidence_path.unique())
    checks['period_order']=bool(f.period_start.le(f.period_end).all())
    from .requirements import specifications
    good=f[f.quality_status.isin(['strict_pit_eligible','conservative_release_reconstructed'])]
    semantic=[]
    for s in specifications():
        g=good[good.series_id.eq(s['series_id'])]
        ok=all(g[c].eq(s[c]).all() for c in ['unit','currency','frequency','measure_type'])
        semantic.append({'series_id':s['series_id'],'certified_rows':len(g),'schema_semantics_consistent':bool(ok)})
    write_json(AUDIT/'semantic_validation.json',semantic)
    checks['certified_semantics_consistent']=all(x['schema_semantics_consistent'] for x in semantic)
    checks['blocked_cannot_enter']=all(not pd.read_parquet(FEATURES/l/'macro_lineage.parquet').quality_statuses.str.contains('blocked').any() for l in LEVELS)
    manifests=list(DATASETS.rglob('dataset.json'));dataset_checks=[]
    market=pd.read_parquet(ROOT/'data/research_v2/market_features_weekly.parquet')
    targets=pd.read_parquet(ROOT/'data/research_v2/prediction_targets_weekly.parquet')
    for path in manifests:
        spec=read_json(path);data=pd.read_parquet(ROOT/spec['features_path']);elig=pd.read_parquet(ROOT/spec['eligibility_path'])
        pd.testing.assert_frame_equal(data[market.columns],market,check_exact=True)
        pd.testing.assert_frame_equal(elig[['sample_id','horizon']],targets[['sample_id','horizon']],check_exact=True)
        for p,h in {**spec['upstream_hashes'],**spec['macro_upstream_hashes']}.items():assert digest(ROOT/p)==h
        assert not elig.loc[elig.eligible,'missing_macro_series'].ne('[]').any()
        assert not (elig.eligible_all_features&~elig.eligible).any()
        dataset_checks.append({'quality':spec['quality_level'],'set':spec['dataset_id'],'samples':len(data),'target_rows':len(elig),'eligible_h20':spec['eligible_h20']})
    checks['joint_samples_and_upstream_hashes']=len(manifests)>=24
    write_json(AUDIT/'dataset_validation.json',dataset_checks)
    causality=causality_check(f);checks['real_date_causality']=True
    market_compatibility();checks['market_in_memory_replay']=True
    protected=verify_protected();checks['frozen_artifacts_unchanged']=True
    from .reproduce import output_hashes
    result={'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'causality':causality,'protected_files_verified':protected,'model_training_executed':False,'validated_output_hashes':output_hashes()}
    write_json(AUDIT/'validation_results.json',result)
    if not all(checks.values()):raise AssertionError(result)
    return result
