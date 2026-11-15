"""As-of data engineering only. No estimation, imputation, or model imports."""
import json
import re
import numpy as np
import pandas as pd
from .common import ROOT,CONFIG,STANDARD,FEATURES,DATASETS,METADATA,read_json,write_json,save_frame,digest,identity
from .requirements import specifications,GROUPS

LEVELS={'strict':['strict_pit_eligible'],
 'conservative':['strict_pit_eligible','conservative_release_reconstructed'],
 'latest_at_retrieval':['strict_pit_eligible','conservative_release_reconstructed','latest_vintage_reconstructed']}
RANK={'strict_pit_eligible':0,'conservative_release_reconstructed':1,'latest_vintage_reconstructed':2}
SUFFIXES=['latest','previous','change','days_since_release']

def select_at(group,asof,max_age):
    known=group[group.research_available_at.le(asof)]
    if known.empty:return [],'NO_ELIGIBLE_RELEASE'
    # Prefer the latest vintage within each observation period. Exact ties use
    # quality, then immutable record ID; genuine same-time conflicts are blocked.
    known=known.sort_values(['period_end','research_available_at','quality_rank','source_record_id'],ascending=[True,True,False,True]).drop_duplicates('period_end',keep='last')
    selected=known.tail(2).to_dict('records');latest=selected[-1]
    if (asof.tz_localize(None).normalize()-latest['period_end']).days>max_age:return selected,'STALE'
    return selected,'AVAILABLE'

def make_weekly(f,market,level='conservative',series=None):
    if level not in LEVELS:raise ValueError('Unknown quality level')
    specs={r['series_id']:r for r in specifications()}
    series=series or list(specs)
    if any(s not in specs for s in series):raise ValueError('Unregistered series')
    allowed=f[f.quality_status.isin(LEVELS[level])&f.certification_status.ne('VALUE_CONFLICT')].copy()
    allowed['quality_rank']=allowed.quality_status.map(RANK)
    groups={s:g for s,g in allowed.groupby('series_id')}
    weekly=market[['sample_id','asof_time']].copy();lineage=[];all_columns={}
    for sid in series:
        group=groups.get(sid,allowed.iloc[:0]);cols={k:[] for k in SUFFIXES}
        for row in market[['sample_id','asof_time']].itertuples(index=False):
            selected,reason=select_at(group,row.asof_time,specs[sid]['max_staleness_days'])
            latest=selected[-1] if selected else None;previous=selected[-2] if len(selected)>1 else None
            valid=reason=='AVAILABLE'
            values={'latest':latest['value'] if valid else np.nan,
              'previous':previous['value'] if valid and previous else np.nan,
              'change':latest['value']-previous['value'] if valid and previous else np.nan,
              'days_since_release':(row.asof_time-latest['research_available_at']).total_seconds()/86400 if valid else np.nan}
            year_reset=valid and previous and specs[sid]['measure_type']=='ytd_flow' and latest['period_end'].year!=previous['period_end'].year
            if year_reset:values['change']=np.nan
            for name,value in values.items():
                cols[name].append(value)
                parents=([latest] if name in ['latest','days_since_release'] else [previous] if name=='previous' else [previous,latest]) if valid else []
                parents=[p for p in parents if p]
                if pd.isna(value):parents=[]
                lineage.append({'sample_id':row.sample_id,'asof_time':row.asof_time,'quality_level':level,'feature':'macro__'+sid+'__'+name,'series_id':sid,'value':value,
                  'status':'AVAILABLE' if pd.notna(value) else ('YTD_YEAR_RESET' if name=='change' and year_reset else 'NO_PREVIOUS_OBSERVATION' if valid else reason),
                  'source_record_ids':json.dumps([p['source_record_id'] for p in parents]),
                  'period_ends':json.dumps([str(p['period_end'].date()) for p in parents]),
                  'vintage_ids':json.dumps([p['vintage_id'] for p in parents]),
                  'available_ats':json.dumps([p['research_available_at'].isoformat() for p in parents]),
                  'quality_statuses':json.dumps([p['quality_status'] for p in parents]),
                  'evidence_paths':json.dumps([p['evidence_path'] for p in parents]),
                  'latest_seen_record_id':latest['source_record_id'] if latest else '',
                  'latest_seen_period_end':latest['period_end'] if latest else pd.NaT})
        for suffix,values in cols.items():all_columns['macro__'+sid+'__'+suffix]=values
    weekly=pd.concat([weekly,pd.DataFrame(all_columns,index=weekly.index)],axis=1)
    return weekly,pd.DataFrame(lineage)

def build_features():
    f=pd.read_parquet(STANDARD/'macro_facts.parquet');market=pd.read_parquet(ROOT/'data/research_v2/market_features_weekly.parquet')
    for level in LEVELS:
        weekly,lineage=make_weekly(f,market,level)
        save_frame(FEATURES/level/'macro_weekly.parquet',weekly);save_frame(FEATURES/level/'macro_lineage.parquet',lineage)
        print('Features',level,len(weekly),len(lineage),flush=True)

def build_datasets(level='conservative',series=None,groups=None,name=None):
    specs={s for g in GROUPS.values() for s in g}
    if groups and any(g not in GROUPS for g in groups):raise ValueError('Unknown group')
    selected=sorted(set(series or [])|{s for g in (groups or []) for s in GROUPS[g]})
    if not selected and name!='market_only':selected=sorted(specs)
    if set(selected)-specs:raise ValueError('Unknown series')
    name=name or ('custom_'+identity([selected,level])[:12]);folder=DATASETS/level/name
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*',name):raise ValueError('Dataset name must be a simple identifier')
    market=pd.read_parquet(ROOT/'data/research_v2/market_features_weekly.parquet')
    targets=pd.read_parquet(ROOT/'data/research_v2/prediction_targets_weekly.parquet')
    folds=pd.read_parquet(ROOT/'data/research_v2/fold_membership.parquet')
    macro=pd.read_parquet(FEATURES/level/'macro_weekly.parquet')
    columns=['macro__'+s+'__'+suffix for s in selected for suffix in SUFFIXES]
    # All frozen samples are retained, including final-period candidates. Target
    # storage copies frozen labels, while the data-only interface never fits them.
    data=market.merge(macro[['sample_id']+columns],on='sample_id',validate='one_to_one')
    eligibility=targets[['sample_id','horizon','asof_time','risk_set','target_valid','label_available_at','exclusion_reason']].copy()
    lookup=data.set_index('sample_id');missing={sid:[s for s in selected if pd.isna(row['macro__'+s+'__latest'])] for sid,row in lookup.iterrows()}
    eligibility['missing_macro_series']=eligibility.sample_id.map(lambda s:json.dumps(missing[s]))
    eligibility['macro_complete']=eligibility.sample_id.map(lambda s:not missing[s])
    eligibility['eligible']=eligibility.risk_set&eligibility.target_valid&eligibility.macro_complete&eligibility.sample_id.map(lookup.market_features_complete)
    eligibility['all_macro_features_complete']=eligibility.sample_id.map(lookup[columns].notna().all(axis=1))
    eligibility['eligible_all_features']=eligibility.eligible&eligibility.all_macro_features_complete
    eligibility['comparison_rule']='M and M+Z must use this same sample_id/horizon eligibility; label maturity still governed by frozen fold membership'
    save_frame(folder/'features.parquet',data);save_frame(folder/'sample_eligibility.parquet',eligibility)
    # Shared data authorities, no redundant copies of 71k fold rows per set.
    write_json(folder/'dataset.json',{'dataset_id':name,'version':'data-foundation-v3.0.0','quality_level':level,'series':selected,'features_path':(folder/'features.parquet').relative_to(ROOT).as_posix(),
      'eligibility_path':(folder/'sample_eligibility.parquet').relative_to(ROOT).as_posix(),
      'targets_path':'data/research_v2/prediction_targets_weekly.parquet','fold_membership_path':'data/research_v2/fold_membership.parquet','fold_manifest_path':'data/metadata/market/fold_manifest.parquet',
      'calendar_path':'data/metadata/market/sse_calendar.parquet','rows':len(data),'eligible_h20':int(eligibility[eligibility.horizon==20].eligible.sum()),
      'upstream_hashes':{p:digest(ROOT/p) for p in ['data/research_v2/market_features_weekly.parquet','data/research_v2/prediction_targets_weekly.parquet','data/research_v2/fold_membership.parquet']},
      'macro_upstream_hashes':{p.relative_to(ROOT).as_posix():digest(p) for p in [STANDARD/'macro_facts.parquet',FEATURES/level/'macro_weekly.parquet',FEATURES/level/'macro_lineage.parquet']},
      'research_uses':['future common-sample model comparisons','quality sensitivity','economic-group combinations'],
      'eligibility_definition':'eligible requires every selected latest value; eligible_all_features also requires previous/change/age. Both M and M+Z must use the chosen identical mask. Inactive definitions (M1 regimes) remain explicit NA; full-pool complete cases can be zero.',
      'limitations':'No imputation or scaling fitted. Final period remains reserved. Some series/groups have zero fully eligible samples; absence is reported, never filled.'})
    return folder

def all_datasets():
    for level in LEVELS:
        build_datasets(level,name='market_only',series=[])
        for group in GROUPS:build_datasets(level,groups=[group],name=group)
        build_datasets(level,name='full_candidate_pool')
        # A coverage-qualified pool is a data-quality convenience, not variable
        # selection based on predictions. Keep the full candidate pool alongside.
        matrix=pd.read_parquet(METADATA/'data_requirements_matrix.parquet')
        column='strict_status' if level=='strict' else 'status'
        eligible=matrix[matrix.period_end.ge('2015-01-01')].groupby('series_id')[column].agg(lambda s:s.isin(['ACCEPTED','STRUCTURAL_NA']).all())
        qualified=sorted(eligible[eligible].index)
        # Mutually exclusive definitions/start dates need separate static sets.
        # Use an explicit stable-regime pool for whole-period ready-to-use inputs;
        # the other certified records remain in the configurable candidate pool.
        stable=[s for s in qualified if s not in ['m1_yoy','m1_new_yoy','lpr_1y'] and not s.startswith('tsf_')]
        build_datasets(level,series=stable,name='qualified_stable_pool')
        write_json(DATASETS/level/'qualification.json',{'basis':'100% accepted or structurally absent required periods from frozen research start 2015; no model results read',
            'coverage_qualified_series':qualified,'stable_series':stable,'static_pool_exclusions':['old/new M1 and post-2019 LPR require a separately chosen period/definition; no splicing']})
    print('Dataset manifests built; no models run',flush=True)
