"""Shared full-state cohorts, synchronized folds and future evaluation contracts."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from .common import *

def build_framework(dictionary):
    from .dictionary import apply_dictionary
    future=read('future_window_outcomes');targets=apply_dictionary(future,dictionary,'future')
    target_version=digest(dict(dictionary=dictionary['label_version'],
        outcomes=future.sort_values(KEY).to_dict('records'),worst_cumulative_definition='min over h=1..H, exclude anchor'))[:20]
    targets['target_version']=target_version
    frame('supervised_targets',targets)
    past=read('past_window_outcomes');current=apply_dictionary(past[past.window_length.eq(20)],dictionary,'current')
    frame('current_states',current)
    feature_cols=[c for c in CORE+['downside_semivol','worst_daily_return','worst_cumulative_return','up_day_fraction','path_slope','vol_concentration','return_dispersion','amount_cny','quote_coverage','return_coverage','float_coverage','suspension_fraction','unexplained_unquoted_fraction'] if c in past]
    features=future[KEY+['asof_time']].copy()
    for h in [5,20,60]:
        q=past[past.window_length.eq(h)][KEY+feature_cols].rename(columns={c:f'market__{c}_{h}d' for c in feature_cols})
        features=features.merge(q,on=KEY,validate='one_to_one')
    statecols=[c for c in current if c.startswith('current_state')]
    features=features.merge(current[KEY+statecols],on=KEY,validate='one_to_one')
    features['current_state_id']=features.current_state_id.astype(float)
    for lag in [1,2,4]:
        for col in ['current_state_id']+[c for c in statecols if 'prob_' in c]:
            features[col+f'_lag{lag}w']=features.groupby('market_id')[col].shift(lag)
    # Other markets' SAME-ASOF past information, never their future outcomes.
    cross=features[['market_id','asof_date']+[f'market__{c}_20d' for c in CORE]].pivot(index='asof_date',columns='market_id')
    cross.columns=['cross__'+m.replace('.','_')+'__'+c for c,m in cross.columns]
    features=features.merge(cross.reset_index(),on='asof_date',validate='many_to_one')
    features['feature_version']=VERSION;features['label_version']=dictionary['label_version'];frame('market_features',features)
    manifest=targets[KEY+['asof_time','label_available_at','measurement_valid','missing_reason','label_version']].copy()
    manifest['target_version']=target_version
    pastvalid=current.set_index(KEY).measurement_valid
    manifest['history_valid']=[bool(pastvalid.loc[tuple(k)]) for k in manifest[KEY].itertuples(index=False,name=None)]
    manifest['continuous_valid']=manifest.measurement_valid
    manifest['class_valid']=targets.future_state_id.notna()
    manifest['eligible']=manifest.history_valid&manifest.continuous_valid&manifest.class_valid
    manifest['period']=np.select([manifest.asof_date.dt.year.le(2019),manifest.asof_date.dt.year.le(2022)],['initial_train','development'],default='test')
    manifest['evaluation_eligible']=manifest.eligible & ~((manifest.period.eq('development')&targets.label_end.gt(pd.Timestamp('2022-12-31')))|(manifest.period.eq('initial_train')&targets.label_end.gt(pd.Timestamp('2019-12-31'))))
    manifest['eligibility_reason']=np.where(manifest.eligible,'AVAILABLE',manifest.missing_reason.where(manifest.missing_reason.ne(''),'CURRENT_WINDOW_INCOMPLETE'))
    frame('sample_manifest',manifest)
    rows=[];plans=[]
    # Initial training role is strictly mature by 2019 end. Development/test
    # windows are assigned by prediction date and scored only if fully mature.
    cut=clock('2019-12-31')
    for r in manifest[manifest.eligible&manifest.label_available_at.le(cut)].itertuples():
        rows.append({**{k:getattr(r,k) for k in KEY},'fold_id':'initial','role':'train','fit_cutoff':cut})
    for month in sorted(manifest.loc[manifest.asof_date.dt.year.ge(2020),'asof_date'].dt.to_period('M').unique()):
        prediction_dates=manifest.loc[manifest.asof_date.dt.to_period('M').eq(month),'asof_date'];first=prediction_dates.min()
        # Monthly fit before the first prediction day's open, using prior exchange close.
        cal=read('calendar').date;prior=cal[cal<month.start_time].max();cut=clock(prior)
        fold_id=str(month);role='validation' if month.year<=2022 else 'test'
        plans.append(dict(fold_id=fold_id,fit_cutoff=cut,prediction_start=first,prediction_end=prediction_dates.max(),period=role))
        train=manifest[manifest.eligible&manifest.label_available_at.le(cut)&manifest.asof_date.lt(first)]
        evaluation=manifest[manifest.evaluation_eligible&manifest.asof_date.dt.to_period('M').eq(month)]
        for part,rname in [(train,'train'),(evaluation,role)]:
            for r in part.itertuples():rows.append({**{k:getattr(r,k) for k in KEY},'fold_id':fold_id,'role':rname,'fit_cutoff':cut})
    frame('fold_membership',pd.DataFrame(rows));frame('time_splits',pd.DataFrame(plans))
    mcols=[c for c in features if c not in KEY+['asof_time','feature_version','label_version']]
    macro=read('macro/historical_reconstructed/features');candidate_z=[c for c in macro if c!='asof_date']
    from .formal import GROUPS
    policy=json.loads((OUT/'missing_policy.json').read_text(encoding='utf8'))
    allowed={r['series_id'] for r in policy['series'] if r['formal']}
    zcols=[c for c in candidate_z if c[len('macro__'):].rsplit('__',1)[0] in allowed]
    specs=json.loads((OUT/'macro/specifications.json').read_text(encoding='utf8'))
    group_for={s['series_id']:s['series_group'] for s in specs}
    groups={g:[c for c in zcols if group_for[c[len('macro__'):].rsplit('__',1)[0]]==g] for g in GROUPS}
    sets={'M':mcols,'M+Z':mcols+zcols,**{'M+Z_'+g:mcols+cols for g,cols in groups.items()},
        **{'M+Z_without_'+g:mcols+[c for c in zcols if c not in groups[g]] for g in GROUPS}}
    by_market={market:{name:[c for c in cols if not c.startswith('cross__'+market.replace('.','_')+'__')] for name,cols in sets.items()} for market in MARKETS}
    feature_version=digest(dict(sets=sets,by_market=by_market,policy=policy['policy_version'],label_version=dictionary['label_version']))[:20]
    features['feature_version']=feature_version;frame('market_features',features)
    write(OUT/'feature_sets.json',dict(version=VERSION,feature_version=feature_version,target_version=target_version,label_version=dictionary['label_version'],sets=sets,by_market=by_market,groups=groups,
        candidate_macro_columns=candidate_z,formal_macro_series=sorted(allowed),missing_policy_version=policy['policy_version'],
        categorical_columns=[c for c in mcols if c=='current_state_id' or c.startswith('current_state_id_lag')],
        missing_policy='No whole-sample imputation/scaling; macro missingness does not remove rows; fit preprocessing within each training fold',
        paired_cohort='same sample_manifest and fold_membership for every information set and task'))

@dataclass
class Dataset:
    X: pd.DataFrame
    y: pd.DataFrame
    metadata: pd.DataFrame
    feature_names: list
    keys: pd.DataFrame = None
    X_market: pd.DataFrame = None
    X_macro: pd.DataFrame = None
    feature_schema: dict = None
    target_schema: dict = None
    versions: dict = None
    context: dict = None

def load_universe(market_id,asof):
    """Historical legal securities, with the actually observed member precision."""
    if market_id not in MARKETS:raise ValueError('Unknown market')
    t=pd.Timestamp(asof);date=t.tz_localize(None).normalize() if t.tzinfo else t.normalize()
    h=read('security_history');active=h[h.valid_from.le(date)&h.valid_to.gt(date)].copy()
    if market_id=='000985.SH':
        active=active[active.security_type.eq('A_SHARE')].copy()
        active['membership_precision']='historical_listing_intervals';return active.reset_index(drop=True)
    w=read('membership_snapshots');w=w[w.index_code.eq(market_id)&w.snapshot_date.le(date)]
    snap=w.snapshot_date.max()
    if pd.isna(snap) or (date-snap).days>45:return active.iloc[:0].assign(membership_precision='NO_RECENT_SNAPSHOT')
    codes=w[w.snapshot_date.eq(snap)].con_code
    # Alias lookup maps old observed codes to the same stable legal security.
    members=set(h[h.ts_code.isin(codes)].instrument_id)
    active=active[active.instrument_id.isin(members)].copy()
    active['snapshot_date']=snap;active['membership_precision']='observed_snapshot_max_45d_plus_known_listing_exits'
    return active.reset_index(drop=True)

def load_dataset(*,market_id=None,start=None,end=None,information_set='M',task='classification',fold_id=None,role=None,quality='historical_reconstructed',eligible_only=True,view=None,store=None):
    """One keyed read chain. Prediction never opens targets or sample_manifest."""
    from .model_contract import CONTRACT_VERSION, target_schema, validate_dataset
    if task not in ['classification','probability','regression']:raise ValueError('Unknown task')
    if quality not in ['strict','historical_reconstructed','latest_at_retrieval']:raise ValueError('Unknown macro view')
    if (fold_id is None)!=(role is None):raise ValueError('fold_id and role must be specified together')
    if view not in [None,'analysis']:raise ValueError('Unknown view')
    if fold_id is None and view!='analysis':raise ValueError('Specify fold_id/role; all-period inspection requires explicit view="analysis"')
    if fold_id is not None and role not in ['train','validation','test','prediction']:raise ValueError('Unknown role')
    if store is None and view!='analysis':store=DataStore()
    if view!='analysis' and not isinstance(store,DataStore):raise ValueError('Formal reads require sealed DataStore')
    if market_id is not None and market_id not in MARKETS:raise ValueError('Unknown market')
    spec=store.spec if store is not None else json.loads((OUT/'feature_sets.json').read_text(encoding='utf8'))
    if information_set not in spec['sets']:raise ValueError('Unknown information set')
    get=store.get if store is not None else read
    features=store.features(quality) if store is not None else get('market_features').merge(get('macro/'+quality+'/features'),on='asof_date',validate='many_to_one')
    if features.duplicated(KEY).any():raise ValueError('Duplicate feature key')
    prediction=role=='prediction'
    if prediction:
        plans=get('time_splits');plan=plans[plans.fold_id.eq(fold_id)]
        if len(plan)!=1:raise ValueError('Prediction needs an existing monthly fold')
        plan=plan.iloc[0]
        meta=features[KEY+['asof_time']].copy()
        # Historical state validity alone; no future eligibility or labels.
        meta['prediction_eligible']=features.current_state_id.notna()
        meta=meta[meta.asof_date.between(plan.prediction_start,plan.prediction_end)]
        if eligible_only:meta=meta[meta.prediction_eligible]
        meta=meta.assign(fold_id=fold_id,role=role,fit_cutoff=plan.fit_cutoff)
    else:
        meta=get('sample_manifest').copy()
        if eligible_only:meta=meta[meta.eligible]
        if fold_id:
            folds=get('fold_membership');part=folds[folds.fold_id.eq(fold_id)&folds.role.eq(role)]
            plans=get('time_splits')
            expected='train' if fold_id=='initial' else (plans.set_index('fold_id').period.get(fold_id))
            if expected is None or role not in ['train',expected]:raise ValueError('Unknown fold/role')
            meta=meta.merge(part,on=KEY,validate='one_to_one')
        else:meta=meta.assign(fold_id='analysis',role='analysis',fit_cutoff=pd.NaT)
    if market_id:meta=meta[meta.market_id.eq(market_id)]
    if start is not None:meta=meta[meta.asof_date.ge(pd.Timestamp(start))]
    if end is not None:meta=meta[meta.asof_date.le(pd.Timestamp(end))]
    meta=meta.sort_values(['asof_date','market_id']).reset_index(drop=True)
    if meta.duplicated(KEY).any():raise ValueError('Duplicate sample key')
    joined=meta[KEY].merge(features,on=KEY,how='left',validate='one_to_one',indicator=True)
    if not joined._merge.eq('both').all():raise ValueError('Missing feature key')
    cols=spec['by_market'][market_id][information_set] if market_id else spec['sets'][information_set]
    X=joined[cols].copy();mcols=[c for c in cols if not c.startswith('macro__')];zcols=[c for c in cols if c.startswith('macro__')]
    schema=store.target_schema() if store else target_schema(get)
    if schema['dictionary_version']!=spec['label_version']:raise ValueError('Dictionary version mismatch')
    y=None
    if not prediction:
        ycols=schema['columns'][task]
        truth=_read_targets(meta[KEY],schema,task,get)
        y=truth[ycols].copy()
        meta['label_start']=truth.label_start;meta['label_end']=truth.label_end
    versions=dict(data_version=store.data_version if store else None,feature_version=spec['feature_version'],
        target_version=spec['target_version'],dictionary_version=spec['label_version'],contract_version=CONTRACT_VERSION)
    for name,value in versions.items():meta[name]=value
    # Availability evidence is independent of realized future coverage.
    if store is None:
        lineage=get('macro/'+quality+'/lineage')
        if lineage.available_at.gt(lineage.asof_time).any():raise ValueError('Macro source available after prediction time')
    context=dict(market_id=market_id,fold_id=fold_id,role=role or 'analysis',information_set=information_set,
        quality=quality,view=view,versions=versions)
    ds=Dataset(X,y,meta,cols,meta[KEY].copy(),X[mcols].copy(),X[zcols].copy(),
        dict(columns=cols,dtypes=X.dtypes.astype(str).to_dict(),information_set=information_set),schema,versions,context)
    validate_dataset(ds)
    return ds

def _read_targets(keys,schema,task,get):
    targets=get('supervised_targets');cols=schema['columns'][task]
    truth=keys.merge(targets[KEY+cols+['label_start','label_end']],on=KEY,how='left',validate='one_to_one',indicator=True)
    if not truth._merge.eq('both').all():raise ValueError('Missing target key')
    return truth

def target_view(ds,task,*,store):
    """Reuse a keyed input read for another existing target, without resampling X."""
    from dataclasses import replace
    from .model_contract import validate_dataset
    if task not in ds.target_schema['columns']:raise ValueError('Unknown task')
    if ds.y is None:raise ValueError('Prediction has no realized targets')
    truth=_read_targets(ds.keys,ds.target_schema,task,store.get)
    return validate_dataset(replace(ds,y=truth[ds.target_schema['columns'][task]].copy()))

def preprocessing():
    """An UNFITTED factory; caller must fit only on fold's train.X."""
    from .preprocessing import FoldPreprocessor
    return FoldPreprocessor()

class DataStore:
    """One immutable in-process read snapshot for batch data preflight."""
    def __init__(self,data_root=None):
        from .release import assert_sealed_products
        self.root=Path(data_root).resolve() if data_root is not None else OUT
        self.data_version=assert_sealed_products(data_root=data_root)
        self.spec=json.loads((self.root/'feature_sets.json').read_text(encoding='utf8'));self.tables={};self.views={}
        self.config_stamps={name:((self.root/name).stat().st_size,(self.root/name).stat().st_mtime_ns)
            for name in ['feature_sets.json','state_dictionary/dictionary.json','missing_policy.json','release/seal.json']}
    def get(self,name):
        for config,expected in self.config_stamps.items():
            p=self.root/config
            if (p.stat().st_size,p.stat().st_mtime_ns)!=expected:raise RuntimeError('Configuration changed during immutable read: '+config)
        path=self.root/(name+'.parquet');stamp=(path.stat().st_size,path.stat().st_mtime_ns)
        if name not in self.tables:
            self.tables[name]=pd.read_parquet(path)
            if not hasattr(self,'stamps'):self.stamps={}
            self.stamps[name]=stamp
        elif self.stamps[name]!=stamp:raise RuntimeError('Data changed during immutable batch read: '+name)
        return self.tables[name]
    def features(self,quality):
        market=self.get('market_features');macro=self.get('macro/'+quality+'/features')
        lineage=self.get('macro/'+quality+'/lineage')
        if quality not in self.views:
            if lineage.available_at.gt(lineage.asof_time).any():raise ValueError('Macro source available after prediction time')
            self.views[quality]=market.merge(macro,on='asof_date',validate='many_to_one')
        return self.views[quality]
    def target_schema(self):
        from .model_contract import target_schema
        self.get('state_dictionary/profiles');self.get('field_dictionary')
        if not hasattr(self,'_target_schema'):
            dictionary=json.loads((self.root/'state_dictionary/dictionary.json').read_text(encoding='utf8'))
            self._target_schema=target_schema(self.get,dictionary=dictionary)
        return self._target_schema

def information_view(ds,information_set,*,store):
    """Exact column restriction of an already keyed read; no alternate joins/cohorts."""
    from dataclasses import replace
    from .model_contract import validate_dataset
    market=ds.context['market_id']
    cols=store.spec['by_market'][market][information_set] if market else store.spec['sets'][information_set]
    if not set(cols)<=set(ds.X):raise ValueError('Requested information is absent; read its superset through load_dataset')
    X=ds.X[cols].copy()
    result=replace(ds,X=X,X_market=X[[c for c in cols if not c.startswith('macro__')]].copy(),
        X_macro=X[[c for c in cols if c.startswith('macro__')]].copy(),feature_names=cols,
        feature_schema=dict(columns=cols,dtypes=X.dtypes.astype(str).to_dict(),information_set=information_set),
        context=dict(ds.context,information_set=information_set))
    return validate_dataset(result)

def paired_losses(left,right,*,task,schema=None):
    """Pair checked, truth-attached scores by key; positive M-MZ means lower loss."""
    from .model_contract import IDENTITY,OUTPUT_CONTEXT_FIELDS,target_schema,unique_keys
    if task not in ['classification','probability','regression']:raise ValueError('Unknown task')
    targets=(schema or target_schema())['columns'][task]
    required=KEY+IDENTITY+OUTPUT_CONTEXT_FIELDS+targets+['loss']
    # These identities describe the independently fitted input/model instances.
    different={'information_set','preprocessing_version','model_version'}
    shared=IDENTITY+[c for c in OUTPUT_CONTEXT_FIELDS if c not in different]
    for scores in [left,right]:
        if not scores.columns.is_unique:raise ValueError('Duplicate paired column')
        missing=[c for c in required if c not in scores]
        if missing:raise ValueError('Missing paired columns: '+', '.join(missing))
        if scores[required].isna().any().any():raise ValueError('Missing paired identity, target or loss')
        if scores[IDENTITY+OUTPUT_CONTEXT_FIELDS].eq('').any().any():raise ValueError('Missing paired identity')
        unique_keys(scores[KEY])
        if not pd.api.types.is_numeric_dtype(scores.loss) or not np.isfinite(scores.loss.to_numpy(float)).all():raise ValueError('Non-finite or non-numeric paired loss')
        if not np.isfinite(scores[targets].to_numpy(float)).all():raise ValueError('Non-finite paired target')
    if set(map(tuple,left[KEY].to_numpy()))!=set(map(tuple,right[KEY].to_numpy())):raise ValueError('Unpaired rows')
    d=left.merge(right,on=KEY,suffixes=('_M','_MZ'),validate='one_to_one',sort=False)
    for col in shared+targets:
        if not d[col+'_M'].eq(d[col+'_MZ']).all():raise ValueError('Unpaired '+col)
    d['loss_difference']=d.loss_M-d.loss_MZ
    if not np.isfinite(d.loss_difference.to_numpy(float)).all():raise ValueError('Non-finite paired loss difference')
    return d
