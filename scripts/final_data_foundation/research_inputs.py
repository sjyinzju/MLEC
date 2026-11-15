"""Data-only as-of views and configurable frozen-sample input eligibility."""
import json
import numpy as np
from .common import *
from .macro_contract import specifications,TSF_REGIMES

FEATURES=ROOT/'data/features/macro/v4'
DATASETS=ROOT/'data/datasets'
LEVELS={'strict':['strict_pit_eligible'],
        'conservative':['strict_pit_eligible','conservative_release_reconstructed'],
        'quote_reconstructed':['strict_pit_eligible','conservative_release_reconstructed'],
        'latest_at_retrieval':['strict_pit_eligible','conservative_release_reconstructed','latest_vintage_reconstructed']}


def prepare(f,level):
    if level not in LEVELS:raise ValueError('Unregistered quality policy')
    f=f.copy();f['effective_available_at']=f.research_available_at
    allowed=f.quality_status.isin(LEVELS[level])
    if level=='quote_reconstructed':
        quote=f.source_class.eq('third_party_historical_quote')&f.reconstructed_quote_at.notna()
        allowed|=quote;f.loc[quote,'effective_available_at']=f.loc[quote,'reconstructed_quote_at']
    f=f[allowed&f.certification_status.eq('ACCEPTED')&f.value.notna()].copy()
    f['quality_rank']=f.quality_status.map({'strict_pit_eligible':2,'conservative_release_reconstructed':1,'latest_vintage_reconstructed':0})
    return f.sort_values(['period_end','effective_available_at','publication_edition_order','quality_rank','source_record_id'])


def make_weekly(f,market,level='conservative'):
    """Four features per scope ID; no imputation or cross-scope change calculation."""
    allowed=prepare(f,level);groups={s:g for s,g in allowed.groupby('series_id')};rows=[];lineage=[]
    specs=specifications()
    timelines={};states={};cursors={}
    for spec in specs:
        sid=spec['series_id']
        if sid in groups:
            g=groups[sid]
            g=g[g.period_end.between(spec['required_start'],spec['required_end'])]
            timelines[sid]=g.sort_values(['effective_available_at','publication_edition_order','quality_rank','source_record_id']).to_dict('records')
        else:timelines[sid]=[]
        states[sid]={};cursors[sid]=0
    assert market.asof_time.is_monotonic_increasing, 'As-of query points must be chronological'
    for point in market[['sample_id','asof_time']].itertuples(index=False):
        row={'sample_id':point.sample_id,'asof_time':point.asof_time}
        for spec in specs:
            sid=spec['series_id'];timeline=timelines[sid];state=states[sid];cursor=cursors[sid]
            while cursor<len(timeline) and timeline[cursor]['effective_available_at']<=point.asof_time:
                record=timeline[cursor];state[record['period_end']]=record;cursor+=1
            cursors[sid]=cursor
            parents=[state[p] for p in sorted(state)[-2:]];last=parents[-1] if parents else None;prev=parents[-2] if len(parents)>1 else None
            scope_break=bool(last and prev and last['statistical_scope_id']!=prev['statistical_scope_id'])
            if scope_break:prev=None
            # The 2015 TSF stock contract is quarterly. Apply the already
            # declared quarterly ceiling, not a monthly ceiling to these facts.
            staleness=150 if last and spec['concept_id'] in ['tsf_stock','tsf_stock_yoy'] and last['period_end'].year==2015 else spec['max_staleness_days']
            reason='NO_ELIGIBLE_RELEASE' if last is None else 'STALE' if (point.asof_time.tz_localize(None).normalize()-last['period_end']).days>staleness else 'AVAILABLE'
            # Out-of-regime source records remain in the raw pool, never become
            # accidental backcasts for the scope-specific research input.
            if last and (last['period_end']<pd.Timestamp(spec['required_start']) or last['period_end']>pd.Timestamp(spec['required_end'])):reason='OUTSIDE_SCOPE_PERIOD'
            valid=reason=='AVAILABLE';reset=bool(valid and prev and spec['measure_type']=='ytd_flow' and last['period_end'].year!=prev['period_end'].year)
            values={'latest':last['value'] if valid else np.nan,'previous':prev['value'] if valid and prev else np.nan,
              'change':last['value']-prev['value'] if valid and prev and not reset else np.nan,
              'days_since_release':(point.asof_time-last['effective_available_at']).total_seconds()/86400 if valid else np.nan}
            for suffix,value in values.items():
                name='macro__'+sid+'__'+suffix;row[name]=value
                used=([last] if suffix in ['latest','days_since_release'] else [prev] if suffix=='previous' else [prev,last]) if pd.notna(value) else []
                lineage.append(dict(sample_id=point.sample_id,asof_time=point.asof_time,series_id=sid,feature=name,value=value,
                  quality_level=level,max_staleness_days=staleness,status='AVAILABLE' if pd.notna(value) else 'YTD_YEAR_RESET' if reset and suffix=='change' else reason if not valid else 'STATISTICAL_SCOPE_BREAK' if scope_break else 'NO_PREVIOUS_OBSERVATION',
                  statistical_scope_ids=json.dumps([p['statistical_scope_id'] for p in used]),latest_scope_id=last['statistical_scope_id'] if last else None,
                  source_record_ids=json.dumps([p['source_record_id'] for p in used]),available_ats=json.dumps([p['effective_available_at'].isoformat() for p in used]),
                  actual_vintage_available_ats=json.dumps([p['research_available_at'].isoformat() for p in used]),
                  period_ends=json.dumps([str(p['period_end'].date()) for p in used]),
                  latest_seen_period_end=last['period_end'] if last else pd.NaT,latest_seen_record_id=last['source_record_id'] if last else None))
        rows.append(row)
    return pd.DataFrame(rows),pd.DataFrame(lineage)


def family(spec):
    return 'm1_definition' if spec['series_id'] in ['m1_yoy','m1_new_yoy'] else spec['concept_id']


def qualification(weekly,lineage,groups=None,series=None):
    specs={s['series_id']:s for s in specifications()};valid_groups={s['series_group'] for s in specs.values()}
    if set(groups or [])-valid_groups or set(series or [])-set(specs):raise ValueError('Unknown group or series')
    chosen=set(series or [])|{s for s,r in specs.items() if r['series_group'] in (groups or []) and r.get('required',True)}
    families={}
    for sid in sorted(chosen):families.setdefault(family(specs[sid]),[]).append(sid)
    meta=lineage[lineage.feature.str.endswith('__latest')].set_index(['sample_id','series_id']);records=[]
    for row in weekly.itertuples(index=False):
        values=row._asdict();missing=[];structural=[];selected={}
        for concept,sids in families.items():
            candidates=[(sid,meta.loc[(row.sample_id,sid),'latest_seen_period_end']) for sid in sids if pd.notna(values['macro__'+sid+'__latest'])]
            if candidates:
                sid,_=max(candidates,key=lambda x:(x[1],specs[x[0]]['required_start'],x[0]));selected[concept]=sid
            elif all(row.asof_time.tz_localize(None)<pd.Timestamp(specs[s]['required_start']) for s in sids):structural.append(concept)
            else:missing.append(concept)
        # Structural absence makes the requested combination not applicable;
        # it is not counted as usable, nor confused with collection failure.
        records.append(dict(sample_id=row.sample_id,quality_level=lineage.quality_level.iloc[0],
          macro_complete=not missing and not structural,combination_applicable=not structural,
          missing_concepts=json.dumps(missing),structural_absent_concepts=json.dumps(structural),selected_scope_ids=json.dumps(selected,sort_keys=True),
          eligibility_rule='One applicable known scope per concept; all requested concepts required. No cross-scope values are spliced into a single feature. Unverified scopes never auto-selected.'))
    return pd.DataFrame(records),sorted(chosen)


def load_dataset(*,groups=(),series=(),quality='conservative',start=None,end=None,horizon=20,label='combined',market_policy='frozen_v2_reconstruction',include_market_extensions=False,require_complete_transforms=False):
    """Return features, explicit eligibility, unchanged targets and frozen folds.

    market_policy is explicit because frozen-v2 market inputs are reconstructions,
    not captured original quote vintages. Macro strictness cannot certify M PIT.
    """
    if market_policy!='frozen_v2_reconstruction':raise ValueError('Strict original-vintage market inputs are unavailable; no silent fallback')
    if horizon not in [5,20,40] or label not in ['combined','vol','drawdown']:raise ValueError('Use a frozen horizon and label')
    market=pd.read_parquet(ROOT/'data/research_v2/market_features_weekly.parquet')
    weekly=pd.read_parquet(FEATURES/quality/'macro_weekly.parquet');lin=pd.read_parquet(FEATURES/quality/'macro_lineage.parquet')
    mask,chosen=qualification(weekly,lin,groups,series)
    targets=pd.read_parquet(ROOT/'data/research_v2/prediction_targets_weekly.parquet');targets=targets[targets.horizon.eq(horizon)]
    cols=['macro__'+sid+'__'+s for sid in chosen for s in ['latest','previous','change','days_since_release']]
    data=market.merge(weekly[['sample_id']+cols],on='sample_id',validate='one_to_one')
    if include_market_extensions:
        extension=pd.read_parquet(ROOT/'data/features/market/v4/market_extensions_weekly.parquet').drop(columns='asof_time')
        extension=extension.rename(columns={c:'market_extension__'+c for c in extension if c!='sample_id'})
        data=data.merge(extension,on='sample_id',validate='one_to_one')
    if start:data=data[data.asof_date.ge(pd.Timestamp(start))]
    if end:data=data[data.asof_date.le(pd.Timestamp(end))]
    ids=set(data.sample_id);targets=targets[targets.sample_id.isin(ids)].copy();mask=mask[mask.sample_id.isin(ids)].copy()
    key='combined' if label=='combined' else label
    target_valid=targets.set_index('sample_id')[key+'_target_valid'];risk=targets.set_index('sample_id')[key+'_risk_set']
    mask['market_features_complete']=mask.sample_id.map(market.set_index('sample_id').market_features_complete)
    mask['target_valid']=mask.sample_id.map(target_valid);mask['risk_set']=mask.sample_id.map(risk)
    mask['eligible']=mask.macro_complete&mask.market_features_complete&mask.target_valid&mask.risk_set
    values=weekly.set_index('sample_id');complete=[]
    for r in mask.itertuples(index=False):
        active=json.loads(r.selected_scope_ids).values()
        cols=[f'macro__{sid}__{suffix}' for sid in active for suffix in ['latest','previous','change','days_since_release']]
        complete.append(bool(values.loc[r.sample_id,cols].notna().all()) if cols else bool(r.macro_complete))
    mask['active_transforms_complete']=complete
    mask['eligible_with_complete_transforms']=mask.eligible&mask.active_transforms_complete
    mask['eligibility_basis']='All requested concepts have an eligible latest value; previous/change reset gaps and inactive scope columns remain explicit in feature_lineage.'
    if require_complete_transforms:mask['eligible']=mask.eligible_with_complete_transforms
    mask['market_quality_policy']=market_policy;mask['joint_strict_pit_certified']=False
    mask['market_extensions_requested']=include_market_extensions
    if include_market_extensions:
        required=['declining_fraction_traded','amihud_per_100m_cny','reference_return_dispersion','average_pairwise_correlation_60d']
        complete=data.set_index('sample_id')[['market_extension__'+c for c in required]].notna().all(axis=1)
        mask['market_extensions_complete']=mask.sample_id.map(complete)
        mask['eligible']&=mask.market_extensions_complete
        mask['eligible_with_complete_transforms']&=mask.market_extensions_complete
    folds=pd.read_parquet(ROOT/'data/research_v2/fold_membership.parquet');folds=folds[folds.sample_id.isin(ids)&folds.horizon.eq(horizon)]
    feature_lineage=lin[lin.sample_id.isin(ids)&lin.series_id.isin(chosen)].copy()
    return {'features':data,'eligibility':mask,'targets':targets,'folds':folds,'selected_series':chosen,'feature_lineage':feature_lineage}


def build():
    f=pd.read_parquet(MACRO/'macro_facts.parquet');market=pd.read_parquet(ROOT/'data/research_v2/market_features_weekly.parquet');summ=[]
    for level in LEVELS:
        weekly,lineage=make_weekly(f,market,level);frame(FEATURES/level/'macro_weekly.parquet',weekly);frame(FEATURES/level/'macro_lineage.parquet',lineage)
        for group in ['M','growth','prices','credit','rates','external','all_candidates']:
            groups=[] if group=='M' else sorted({s['series_group'] for s in specifications()}) if group=='all_candidates' else [group]
            result=load_dataset(groups=groups,quality=level)
            path=DATASETS/'sample_manifests/v4'/level/(group+'.parquet');frame(path,result['eligibility'])
            spec={'dataset_id':group,'data_version':VERSION,'groups':groups,'macro_quality':level,'market_policy':'frozen_v2_reconstruction',
                'features_authorities':['data/research_v2/market_features_weekly.parquet',str((FEATURES/level/'macro_weekly.parquet').relative_to(ROOT))],
                'sample_manifest':path.relative_to(ROOT).as_posix(),'targets_authority':'data/research_v2/prediction_targets_weekly.parquet',
                'folds_authority':'data/research_v2/fold_membership.parquet','selected_series':result['selected_series'],'rows':len(result['features']),
                'eligible_h20':int(result['eligibility'].eligible.sum()),'joint_strict_pit_certified':False}
            write(DATASETS/'feature_sets/v4'/level/(group+'.json'),spec);summ.append({k:spec[k] for k in ['dataset_id','macro_quality','rows','eligible_h20']})
        print('Weekly inputs',level,len(weekly),flush=True)
    frame(AUDIT/'temporal_validation/sample_eligibility_summary.parquet',pd.DataFrame(summ))
    write(DATASETS/'research_base/v4/authority.json',{'version':VERSION,'sample_ids':'data/research_v2/market_features_weekly.parquet','count':599,'no_rows_deleted':True,
          'interface':'scripts.final_data_foundation.research_inputs.load_dataset','labels':'frozen v2 combined, volatility, drawdown; horizons 5,20,40; no regeneration'})
    quality_policies()


def quality_policies():
    for level,allowed in LEVELS.items():
        write(DATASETS/'quality_versions/v4'/(level+'.json'),{'quality_version':level,'data_version':VERSION,
          'accepted_macro_statuses':allowed,'certification_status_required':'ACCEPTED',
          'availability_field':'effective_available_at','non_null_value_required':True,
          'quote_reconstruction_exception':'third_party_historical_quote with explicit reconstructed_quote_at' if level=='quote_reconstructed' else None,
          'market_policy':'frozen_v2_reconstruction','joint_strict_pit_certified':False,
          'excluded':['source conflicts','semantic errors','unverified facts','outside scope period'],
          'sample_rows_preserved':599,'eligibility_is_explicit_mask':True})


if __name__=='__main__':build()
