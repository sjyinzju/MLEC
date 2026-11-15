"""One registry and one join contract for all algorithms."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from .common import ROOT, TARGET, digest, identity, read_json, save_frame, write_json
from scripts.macro_pipeline.govern import CORE, GROUPS

DATA=ROOT/'data/datasets/main_v1'

def asof_features(facts, samples, series, quality=('strict_pit_eligible',)):
    """Select versions within each observation first, then newest observation.

    A late revision of an old period cannot replace a newer economic period.
    All timestamps are Asia/Shanghai aware. Staleness is an explicit exclusion.
    """
    f=facts[facts.quality_status.isin(quality)&facts.series_id.isin(series)].copy()
    grouped={sid:d.sort_values(['period_end','research_available_at','vintage_id','source_record_id']) for sid,d in f.groupby('series_id')}
    daily=set(facts.loc[facts.frequency.eq('D'),'series_id'])
    calendar=pd.read_parquet(ROOT/'audit/research_v2/sse_calendar.parquet')
    open_dates=set(calendar.loc[calendar.is_open.astype(bool),'date'])
    calendar_dates=pd.DatetimeIndex(sorted(open_dates))
    rows=[]; lineage=[]
    for s in samples[['sample_id','asof_time']].itertuples(index=False):
        row={'sample_id':s.sample_id}
        for sid in series:
            source=grouped.get(sid,f.iloc[:0])
            observable=source.period_end<=s.asof_time.tz_localize(None)
            if sid.startswith('pmi_'):observable=observable | source.period_end.dt.to_period('M').eq(s.asof_time.tz_localize(None).to_period('M'))
            d=source[(source.research_available_at<=s.asof_time)&observable]
            d=d.drop_duplicates(['period_start','period_end'],keep='last')
            prefix='z__'+sid+'__'; val=prev=delta=age=np.nan; available=pd.NaT; reason='no_eligible_history'; used=[]
            if len(d):
                last=d.iloc[-1]; available=last.research_available_at
                age=(s.asof_time-available).total_seconds()/86400
                limit=10 if last.frequency=='D' else (150 if last.frequency=='Q' else 75)
                stale=(s.asof_time.tz_localize(None)-last.period_end).days>limit
                reason='stale_observation' if stale else ''
                if not stale:
                    val=last.value;prev=d.iloc[-2].value if len(d)>1 else np.nan;delta=val-prev;used=d.tail(2).source_record_id.tolist()
            row.update({prefix+'latest':val,prefix+'previous':prev,prefix+'change':delta,prefix+'age_days':age if reason=='' else np.nan})
            if sid in daily:
                quotes=d[d.period_end.isin(open_dates)]
                end_pos=calendar_dates.searchsorted(d.period_end.iloc[-1],side='right') if len(d) else 0
                for count in [5,20]:
                    dates=calendar_dates[max(0,end_pos-count):end_pos]
                    window=quotes[quotes.period_end.isin(dates)]
                    row[prefix+f'mean_{count}d']=float(window.value.mean()) if reason=='' and len(window)==count else np.nan
                    if reason=='' and len(window)==count:used.extend(window.source_record_id.tolist())
            if used:available=d.loc[d.source_record_id.isin(used),'research_available_at'].max()
            lineage.append(dict(sample_id=s.sample_id,series_id=sid,feature_available_at=available,exclusion_reason=reason,source_record_ids='|'.join(sorted(set(used)))))
        rows.append(row)
    return pd.DataFrame(rows),pd.DataFrame(lineage)

def build_dataset():
    market=pd.read_parquet(ROOT/'data/research_v2/market_features_weekly.parquet')
    targets=pd.read_parquet(ROOT/'data/research_v2/prediction_targets_weekly.parquet')
    targets=targets[targets.horizon.eq(20)].copy()
    assert market.sample_id.is_unique and targets.sample_id.is_unique
    whitelist=read_json(ROOT/'config/research_v2/feature_whitelist.json')['default_primary_features']
    meta=targets.drop(columns=[c for c in targets if c.startswith('y_')])
    meta['included_market']=meta.target_valid & meta.risk_set
    meta['included_core']=False
    meta['core_exclusion_reason']='required_core_missing_or_stale'
    # Heldout y is intentionally absent from the new modeling dataset.
    labels=targets[['sample_id',TARGET,'asof_time']].copy()
    labels.loc[labels.asof_time.dt.year.ge(2023),TARGET]=pd.NA
    labels=labels.drop(columns='asof_time')
    facts=pd.read_parquet(ROOT/'data/standardized/macro/macro_facts.parquet')
    series=sorted(set(facts.series_id))
    # Only dated official announcements and explicitly lagged official fixings.
    # Latest-vintage macroeconomic reconstructions remain excluded.
    macro,availability=asof_features(facts,market,series,quality=('strict_pit_eligible','conservative_release_reconstructed'))
    core_complete=macro.reindex(columns=[f'z__{sid}__latest' for sid in CORE]).notna().all(axis=1)
    meta['included_core']=meta.included_market & core_complete.to_numpy()
    meta['core_exclusion_reason']=np.where(core_complete,'','required_core_missing_or_stale')
    save_frame(ROOT/'data/features/macro_weekly.parquet',macro)
    save_frame(ROOT/'data/features/macro_availability.parquet',availability)
    for name,df in [('common_samples',meta),('sample_manifest',meta),('market_features',market[['sample_id']+whitelist]),('macro_features',macro),('labels',labels)]:
        save_frame(DATA/f'{name}.parquet',df)
    sets={'M':{'columns':whitelist,'series':[],'status':'eligible','quality_version':'frozen_market_reconstruction','sample_version':'main_v1'}}
    sample_versions={'main_v1':{'manifest':'data/datasets/main_v1/common_samples.parquet','status':'eligible'}}
    # Economic groups contain series with usable initial-history evidence, while
    # the seven predeclared core constituents remain mandatory as a whole.
    supported=[]
    for sid in series:
        present=macro[f'z__{sid}__latest'].notna().to_numpy()
        if (present & market.asof_time.dt.year.lt(2020).to_numpy()).sum()>=40:supported.append(sid)
    macro_groups={'core':CORE,**{g:[s for s in ids if s in supported] for g,ids in GROUPS.items()},'full_eligible':supported}
    macro_groups.update({'core_without_'+g:[s for s in CORE if s not in ids] for g,ids in GROUPS.items() if any(s in CORE for s in ids)})
    for name,ids in macro_groups.items():
        cols=[f'z__{sid}__{suffix}' for sid in ids for suffix in ['latest','previous','change','age_days']]
        cols.extend(c for sid in ids for c in [f'z__{sid}__mean_5d',f'z__{sid}__mean_20d'] if c in macro)
        latest=[f'z__{sid}__latest' for sid in ids]
        complete=macro.reindex(columns=latest).notna().all(axis=1) if ids else pd.Series(False,index=macro.index)
        if name.startswith('core_without_'):complete=core_complete
        joint=meta.merge(macro[['sample_id']].assign(macro_complete=complete),on='sample_id',validate='one_to_one')
        joint['included_market']=joint.included_market & joint.macro_complete
        initial=int((joint.included_market & joint.asof_time.dt.year.lt(2020)).sum())
        by_year={str(y):int((joint.included_market & joint.asof_time.dt.year.eq(y)).sum()) for y in [2020,2021,2022]}
        accepted=initial>=40 and all(by_year.values())
        version='common_core_v1' if name.startswith('core_without_') else 'common_'+name+'_v1'
        if name=='core':
            meta['included_core']=joint.included_market.to_numpy()
            meta['core_exclusion_reason']=np.where(complete,'','required_core_missing_or_stale')
        joint['joint_exclusion_reason']=np.where(joint.macro_complete,'','required_macro_missing_or_stale_or_unverified')
        path=ROOT/f'data/datasets/{version}/common_samples.parquet';save_frame(path,joint)
        sample_versions[version]={'manifest':path.relative_to(ROOT).as_posix(),'status':'eligible' if accepted else 'blocked'}
        sets['M_plus_Z_'+name]={'columns':whitelist+cols,'series':ids,'status':'eligible' if accepted else 'blocked','reason':None if accepted else 'Fewer than 40 eligible initial-training weeks or no eligible weeks in a development year','quality_version':'dated_announcements_plus_official_fixings_end_of_day_v1','sample_version':version,'initial_training_weeks':initial,'development_candidate_weeks':by_year,'missing_policy':'required raw latest values present; derivatives train median; never backfill','feature_count':len(whitelist+cols)}
    write_json(ROOT/'config/experiments/feature_sets.json',sets)
    for name in ['common_samples','sample_manifest']:save_frame(DATA/f'{name}.parquet',meta)
    gate=read_json(ROOT/'audit/framework/macro_gate.json')
    gate.update(core_eligible=sets['M_plus_Z_core']['status']=='eligible',reason=sets['M_plus_Z_core']['reason'],quality_policy='dated_announcements_plus_official_fixings_end_of_day_v1',strict_pit_core=False,strict_pit_core_limitation='Shibor official historical fixings lack correction-vintage archive; no latest-vintage macroeconomic values admitted')
    write_json(ROOT/'audit/framework/macro_gate.json',gate)
    artifacts=sorted(set(DATA.glob('*.parquet')) | {ROOT/v['manifest'] for v in sample_versions.values()})+[ROOT/'data/features/macro_availability.parquet',ROOT/'data/standardized/macro/macro_facts.parquet']
    registry={'version':'main_v1','sample_versions':sample_versions,'artifacts':{str(p.relative_to(ROOT)):digest(p) for p in artifacts},'market_protocol_hash':read_json(ROOT/'config/research_v2/protocol_hash.json')['sha256'],'heldout_labels':'redacted','macro_gate':read_json(ROOT/'audit/framework/macro_gate.json')}
    write_json(ROOT/'data/metadata/dataset_registry.json',registry)
    write_json(ROOT/'data/metadata/schema_registry.json',{p.stem:{k:str(v) for k,v in pd.read_parquet(p).dtypes.items()} for p in DATA.glob('*.parquet')})
    return meta

@dataclass
class Dataset:
    X:pd.DataFrame
    y:pd.Series
    metadata:pd.DataFrame
    feature_names:list
    feature_availability:pd.DataFrame
    fold_metadata:dict
    hashes:dict

def load_dataset(sample_version,feature_set,horizon,fold_id,role):
    if horizon!=20: raise ValueError('Only accepted H20 registered')
    if not fold_id.startswith('dev-'): raise ValueError('Final evaluation locked')
    if role not in ['train','validation']: raise ValueError('Invalid role')
    registry=read_json(ROOT/'config/experiments/feature_sets.json'); spec=registry[feature_set]
    if spec['status']!='eligible': raise ValueError('Macro acceptance gate blocked: '+spec['reason'])
    expected=read_json(ROOT/'data/metadata/dataset_registry.json')
    version=expected['sample_versions'][sample_version]
    if version['status']!='eligible':raise ValueError('Common sample acceptance blocked')
    if feature_set!='M' and spec['sample_version']!=sample_version:raise ValueError('Wrong common sample version')
    for p,h in expected['artifacts'].items():
        if digest(ROOT/p)!=h: raise ValueError('Dataset hash changed: '+p)
    membership=pd.read_parquet(ROOT/'data/research_v2/fold_membership.parquet')
    selected=membership[(membership.fold_id==fold_id)&(membership.horizon==horizon)&(membership.role==role)]
    meta=pd.read_parquet(ROOT/version['manifest'])
    meta=meta[meta.included_market].merge(selected[['sample_id','fit_cutoff','role']],on='sample_id',validate='one_to_one')
    meta=meta.sort_values('asof_time').reset_index(drop=True)
    if role=='train': assert (meta.label_available_at<=meta.fit_cutoff).all()
    assert (meta.feature_available_at<=meta.asof_time).all()
    assert meta.asof_time.dt.year.lt(2023).all()
    X=meta[['sample_id']].merge(pd.read_parquet(DATA/'market_features.parquet'),on='sample_id',validate='one_to_one')
    if spec['series']: X=X.merge(pd.read_parquet(DATA/'macro_features.parquet'),on='sample_id',validate='one_to_one')
    X=X[spec['columns']]
    y=meta[['sample_id']].merge(pd.read_parquet(DATA/'labels.parquet'),on='sample_id',validate='one_to_one')[TARGET].astype(int)
    plan=pd.read_parquet(ROOT/'audit/research_v2/fold_manifest.parquet').set_index('fold_id').loc[fold_id].to_dict()
    avail=meta[['sample_id','feature_available_at']].copy();avail['series_id']='market'
    if spec['series']:
        macro_available=pd.read_parquet(ROOT/'data/features/macro_availability.parquet')
        macro_available=macro_available[macro_available.sample_id.isin(meta.sample_id)&macro_available.series_id.isin(spec['series'])]
        checked=macro_available.merge(meta[['sample_id','asof_time']],on='sample_id',validate='many_to_one')
        assert checked.feature_available_at.le(checked.asof_time).all()
        assert checked.exclusion_reason.eq('').all()
        avail=pd.concat([avail,macro_available],ignore_index=True)
    plan['fold_id']=fold_id
    return Dataset(X,y,meta,list(X.columns),avail,plan,{'dataset':identity(expected),'feature':identity(spec),'protocol':expected['market_protocol_hash']})
