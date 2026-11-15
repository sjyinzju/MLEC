"""Causal market measurements, fixed thresholds, episodes, targets and temporal folds."""
from __future__ import annotations
import numpy as np
import pandas as pd
from common import PROTOCOL, CONFIG, DATA, AUDIT, TZ, jsonwrite, objhash, stamp, saveframe

def path_mdd(values):
    values=np.asarray(values,dtype=float)
    if not np.isfinite(values).all() or (values<=0).any():return np.nan
    return float(np.max(1-values/np.maximum.accumulate(values)))

def observations(clean):
    out=clean.copy();p=out.close
    out['log_return']=np.log(p/p.shift(1))
    for k in [5,20,60]:
        out[f'ret_{k}d']=p/p.shift(k)-1
        out[f'vol_{k}d']=np.sqrt((252/k)*out.log_return.pow(2).rolling(k,min_periods=k).sum())
    out['downside_vol_20d']=np.sqrt((252/20)*out.log_return.clip(upper=0).pow(2).rolling(20,min_periods=20).sum())
    out['negative_return_fraction_20d']=out.log_return.lt(0).where(out.log_return.notna()).rolling(20,min_periods=20).mean()
    out['worst_daily_return_20d']=(p/p.shift(1)-1).rolling(20,min_periods=20).min()
    for k in [20,60]:
        out[f'mdd_{k}d']=p.rolling(k+1,min_periods=k+1).apply(path_mdd,raw=True)
        out[f'current_drawdown_{k}d']=1-p/p.rolling(k+1,min_periods=k+1).max()
    out['amount_ma20']=out.amount.rolling(20,min_periods=20).mean()
    den=out.amount_ma20
    out['amount_ratio_5_20']=out.amount.rolling(5,min_periods=5).mean().div(den.where(den>0))
    out['amount_ratio_missing_reason']=np.select([den.isna(),den.le(0)],['insufficient_history','nonpositive_denominator'],default='')
    for col in ['turnover_rate','turnover_rate_f','pe','pe_ttm','pb','total_mv','float_mv','total_share','float_share','free_share']:
        out[col+'_lag1']=out['basic_raw_'+col].shift(1)
    out['turnover_change_5d']=out.turnover_rate_lag1-out.turnover_rate_lag1.shift(5)
    out['turnover_change_20d']=out.turnover_rate_lag1-out.turnover_rate_lag1.shift(20)
    out['feature_start']=out.date.shift(60)
    out['feature_end']=out.date
    out['feature_available_at']=out.research_available_at
    return out

def thresholds(obs,q=.8,metric='mdd_20d'):
    ref=obs.loc[obs.date.between(PROTOCOL['reference_start'],PROTOCOL['reference_end']) & obs[['vol_20d',metric]].notna().all(axis=1)]
    if not len(ref):raise ValueError('No complete reference observations')
    obj={'q':q,'qV':float(np.quantile(ref.vol_20d,q,method='linear')),'qD':float(np.quantile(ref[metric],q,method='linear')),'loss_metric':metric,'reference_start':str(ref.date.min().date()),'reference_end':str(ref.date.max().date()),'reference_n':len(ref),'vol_unit':'annualized fraction','loss_unit':'nonnegative price loss fraction','algorithm':'numpy.quantile(method=linear)','reference_only':True}
    obj['threshold_version']='thr-'+objhash(obj)[:16];return obj

def states(obs,thr):
    valid=obs[['vol_20d',thr['loss_metric']]].notna().all(axis=1)
    result=pd.DataFrame({'date':obs.date,'valid_state':valid})
    result['V']=(obs.vol_20d>thr['qV']).where(valid).astype('Int8')
    result['D']=(obs[thr['loss_metric']]>thr['qD']).where(valid).astype('Int8')
    result['state_id']=(result.V+2*result.D).astype('Int8')
    result['state_name']=result.state_id.map({0:'S0',1:'S1',2:'S2',3:'S3'})
    result['raw_stress']=((result.V==1)|(result.D==1)).where(valid).astype('Int8')
    result['threshold_version']=thr['threshold_version'];result['protocol_version']=PROTOCOL['protocol_version']
    return result

def event_machine(dates,trigger,exit_days=5,dimension='combined'):
    """A day-end recursion. No backdating after recovery and no bridging unknown runs."""
    dates=pd.Series(pd.to_datetime(dates)).reset_index(drop=True)
    trigger=pd.Series(trigger).reset_index(drop=True)
    known=False;active=False;normal=0;ep=None;events=[];rows=[];last_onset_idx=None
    def open_episode(i,left):
        return {'episode_id':f'{dimension}-{dates[i]:%Y%m%d}', 'dimension':dimension,
                'observation_start_date':dates[i],'onset_date':pd.NaT if left else dates[i],
                'last_stress_date':dates[i],'exit_confirm_date':pd.NaT,'left_censored':left,
                'right_censored':False,'interrupted_by_unknown':False,'start_position':i,
                'end_position':None,'stress_days':1}
    for i,(day,trig) in enumerate(zip(dates,trigger)):
        onset=False;exited=False
        if pd.isna(trig):
            if active:
                ep.update(right_censored=True,interrupted_by_unknown=True,end_position=i-1);events.append(ep);ep=None
            known=False;active=False;normal=0
            rows.append({'date':day,'episode_active':pd.NA,'risk_set_known':False,'risk_set':False,'episode_id':None,'onset_today':False,'exit_today':False,'normal_run':0,'elapsed_episode_days':pd.NA,'days_since_known_onset':pd.NA})
            continue
        if active:
            if int(trig)==1:normal=0;ep['last_stress_date']=day;ep['stress_days']+=1
            else:normal+=1
            if normal>=exit_days:
                active=False;known=True;exited=True;ep.update(exit_confirm_date=day,end_position=i);events.append(ep);ep=None
        elif int(trig)==1:
            left=not known;ep=open_episode(i,left);active=True;normal=0
            onset=not left
            if onset:last_onset_idx=i
        else:
            normal+=1
            if normal>=exit_days:known=True
        rows.append({'date':day,'episode_active':int(active) if active or known else pd.NA,
                     'risk_set_known':known or active,'risk_set':known and not active,
                     'episode_id':ep['episode_id'] if ep else None,'onset_today':onset,'exit_today':exited,
                     'normal_run':normal,'elapsed_episode_days':i-ep['start_position']+1 if ep else 0 if known else pd.NA,
                     'days_since_known_onset':i-last_onset_idx if last_onset_idx is not None else pd.NA})
    if active:ep.update(right_censored=True,end_position=len(dates)-1);events.append(ep)
    daily=pd.DataFrame(rows)
    for col in ['episode_active','elapsed_episode_days','days_since_known_onset']:daily[col]=daily[col].astype('Int64')
    columns=['episode_id','dimension','observation_start_date','onset_date','last_stress_date','exit_confirm_date','left_censored','right_censored','interrupted_by_unknown','start_position','end_position','stress_days']
    e=pd.DataFrame(events,columns=columns)
    for col in ['observation_start_date','onset_date','last_stress_date','exit_confirm_date']:e[col]=pd.to_datetime(e[col])
    return daily,e

def all_events(obs,state,exit_days=5):
    merged=state.copy();parts=[]
    for dim,col in [('combined','raw_stress'),('vol','V'),('drawdown','D')]:
        day,e=event_machine(obs.date,state[col],exit_days,dim)
        for field in day.columns:
            if field!='date':merged[f'{dim}_{field}']=day[field].to_numpy()
        for j,row in e.iterrows():
            lo=int(row.start_position);hi=int(row.end_position)
            path=obs.close.iloc[lo:hi+1]
            e.loc[j,'retrospective_duration_days']=hi-lo+1
            e.loc[j,'retrospective_mdd']=path_mdd(path)
            typeids=state.state_id.iloc[lo:hi+1].dropna().astype(int)
            e.loc[j,'retrospective_peak_type']='S3' if 3 in typeids.to_numpy() else ','.join(f'S{x}' for x in sorted(set(typeids)-{0}))
            e.loc[j,'onset_type']=state.state_name.iloc[lo] if not row.left_censored else None
        parts.append(e)
    episodes=pd.concat(parts,ignore_index=True)
    episodes['protocol_version']=PROTOCOL['protocol_version'];episodes['threshold_version']=state.threshold_version.iloc[0]
    return merged,episodes

CORE_FEATURES=['ret_5d','ret_20d','ret_60d','vol_5d','vol_20d','vol_60d','downside_vol_20d','mdd_20d','mdd_60d','current_drawdown_20d','current_drawdown_60d','negative_return_fraction_20d','worst_daily_return_20d','amount_ma20','amount_ratio_5_20','turnover_rate_lag1','turnover_rate_f_lag1','turnover_change_5d','turnover_change_20d']
STATE_FEATURES=['state_id','V','D','combined_episode_active','combined_elapsed_episode_days','combined_normal_run']
OPTIONAL_FEATURES=['down_fraction_proxy','breadth_change_5d_proxy','mean_corr_60d_proxy','amihud_20d_proxy','amihud_20d_median_proxy']
VALUATION_FEATURES=['pe_lag1','pe_ttm_lag1','pb_lag1','total_mv_lag1','float_mv_lag1']

def full_week_dates(cal):
    opened=cal.loc[cal.is_open.eq(1),'date'];groups=opened.groupby(opened.dt.isocalendar().year.astype(str)+'-'+opened.dt.isocalendar().week.astype(str)).max()
    # Require entire calendar week represented by calendar boundary; no partial end-week fabrication.
    return set(d for d in groups if d-pd.Timedelta(days=d.weekday())>=cal.date.min() and d+pd.Timedelta(days=6-d.weekday())<=cal.date.max())

def build_weekly(obs,state,episodes,cal,thr,horizons=(20,5,40)):
    week_ends=full_week_dates(cal)
    positions=[i for i,d in enumerate(obs.date) if d in week_ends]
    weekly=obs.iloc[positions].reset_index(drop=True)
    for col in state.columns:
        if col!='date':weekly[col]=state.iloc[positions][col].to_numpy()
    weekly['asof_date']=weekly.date;weekly['asof_time']=stamp(weekly.date)
    weekly['sample_id']='CSI300-'+weekly.date.dt.strftime('%Y%m%d')
    weekly['market_features_complete']=weekly[CORE_FEATURES].notna().all(axis=1)
    weekly['market_feature_missing_count']=weekly[CORE_FEATURES].isna().sum(axis=1)
    weekly['protocol_version']=PROTOCOL['protocol_version'];weekly['threshold_version']=thr['threshold_version']
    weekly['time_role']=np.select([weekly.date.dt.year.le(2019),weekly.date.dt.year.le(2022)],['initial_reference_train','development'],default='heldout')
    weekly['initial_threshold_realtime_claim']=False
    weekly['reference_period_realtime_eligible']=weekly.date.gt(PROTOCOL['reference_end'])
    weekly['measurement_standard_available_at']=stamp([pd.Timestamp(PROTOCOL['reference_end'])]).iloc[0]
    weekly['state_history_start']=obs.date.iloc[0]
    targets=[];outcomes=[];mapping=[]
    onset_positions={dim:np.flatnonzero(state[f'{dim}_onset_today'].to_numpy(bool)) for dim in ['combined','vol','drawdown']}
    bystart={(r.dimension,int(r.start_position)):r for _,r in episodes.iterrows() if not r.left_censored}
    p=obs.close.to_numpy();r=obs.log_return.to_numpy()
    for wi,t in enumerate(positions):
        w=weekly.iloc[wi];has_features=bool(w.market_features_complete)
        for H in horizons:
            e=t+H;complete=e<len(obs)
            row={'sample_id':w.sample_id,'index_code':PROTOCOL['index_code'],'asof_date':w.date,'asof_time':w.asof_time,'horizon':H,
                 'feature_start':w.feature_start,'feature_end':w.date,'feature_available_at':w.feature_available_at,
                 'label_start':obs.date.iloc[t+1] if t+1<len(obs) else pd.NaT,'label_end':obs.date.iloc[e] if complete else pd.NaT,
                 'label_available_at':stamp([obs.date.iloc[e]]).iloc[0] if complete else pd.NaT,
                 'horizon_complete':complete,'time_role':w.time_role,'protocol_version':PROTOCOL['protocol_version'],'threshold_version':thr['threshold_version']}
            row['measurement_standard_available_at']=w.measurement_standard_available_at
            row['reference_period_realtime_eligible']=w.reference_period_realtime_eligible
            for dim,target in [('combined',f'y_new_episode_next{H}'),('vol',f'y_new_vol_episode_next{H}'),('drawdown',f'y_new_drawdown_episode_next{H}')]:
                risk=bool(state.loc[t,f'{dim}_risk_set']) and has_features
                row[f'{dim}_risk_set']=risk
                valid=risk and complete
                row[f'{dim}_target_valid']=valid
                future=onset_positions[dim];future=future[(future>t)&(future<=e)] if complete else np.array([],dtype=int)
                row[target]=int(len(future)>0) if valid else pd.NA
                if dim=='combined':
                    row['risk_set']=risk;row['target_valid']=valid
                    row['exclusion_reason']='insufficient_market_history' if not has_features else 'unknown_state_or_initialization' if not state.loc[t,'combined_risk_set_known'] else 'not_at_risk' if not risk else 'incomplete_future_horizon' if not complete else ''
                    row['next_event_onset_type']=state.state_name.iloc[future[0]] if valid and len(future) else None
                if complete:
                    for j in future:
                        ev=bystart[(dim,int(j))]
                        mapping.append({'sample_id':w.sample_id,'horizon':H,'dimension':dim,'episode_id':ev.episode_id,'onset_date':ev.onset_date,'lead_to_trigger':int(j-t),'at_risk_at_prediction':risk,'onset_type':ev.onset_type,'current_drawdown_at_prediction':w.current_drawdown_20d,'loss_since_future_onset_at_prediction':np.nan,'loss_since_onset_reason':'future_onset_not_yet_observed; use current_drawdown_at_prediction'})
            targets.append(row)
            if H==20:
                outcome={'sample_id':w.sample_id,'asof_date':w.date,'label_end':row['label_end'],'label_available_at':row['label_available_at'],'future_path_valid':complete}
                if complete:
                    rr=r[t+1:e+1];path=p[t:e+1]
                    vol=np.sqrt(252/20*np.sum(rr**2));mdd=path_mdd(path)
                    rolling_known=bool(state.valid_state.iloc[t+1:e+1].all())
                    outcome.update(future_return_20d=p[e]/p[t]-1,future_vol_20d=vol,future_mdd_20d=mdd,future_downside_vol_20d=np.sqrt(252/20*np.sum(np.minimum(rr,0)**2)),future_worst_return_20d=np.min(p[t+1:e+1]/p[t]-1),future_worst_daily_return_20d=np.min(np.expm1(rr)),future_rolling_states_valid=rolling_known,y_any_stress_next20=int(state.raw_stress.iloc[t+1:e+1].eq(1).any()) if rolling_known else np.nan,y_future_window_stress_20d=int(vol>thr['qV'] or mdd>thr['qD']))
                else:
                    outcome['future_rolling_states_valid']=False
                    for col in ['future_return_20d','future_vol_20d','future_mdd_20d','future_downside_vol_20d','future_worst_return_20d','future_worst_daily_return_20d','y_any_stress_next20','y_future_window_stress_20d']:outcome[col]=np.nan
                outcomes.append(outcome)
    target=pd.DataFrame(targets)
    for col in target:
        if col.startswith('y_'):target[col]=target[col].astype('Int8')
    # Features and outcomes are physically separate; no future episode metadata in features.
    meta=['sample_id','index_code','asof_date','asof_time','feature_start','feature_end','feature_available_at','research_available_at','availability_basis','basic_observation_date','basic_research_available_at','basic_availability_basis','market_features_complete','market_feature_missing_count','protocol_version','threshold_version','reference_period_realtime_eligible','measurement_standard_available_at','state_history_start']
    allowed=meta+CORE_FEATURES+STATE_FEATURES+VALUATION_FEATURES
    features=weekly[allowed].copy()
    for col in CORE_FEATURES+STATE_FEATURES+VALUATION_FEATURES:features['missing__'+col]=features[col].isna()
    return features,pd.DataFrame(outcomes),target,pd.DataFrame(mapping)

def event_opportunities(episodes,features,targets,mapping,dates):
    out=episodes.copy();datepos={d:i for i,d in enumerate(dates)}
    for H in [20,5,40]:
        for dim in ['combined','vol','drawdown']:
            for i,e in out.loc[out.dimension.eq(dim)].iterrows():
                full=not e.left_censored and datepos[e.onset_date]>=H
                mm=mapping.loc[(mapping.horizon==H)&(mapping.episode_id==e.episode_id)&mapping.at_risk_at_prediction] if len(mapping) else mapping
                points=features.loc[features.sample_id.isin(mm.sample_id)] if len(mm) else features.iloc[:0]
                out.loc[i,f'full_{H}d_lead_window']=full
                out.loc[i,f'weekly_at_risk_opportunities_{H}d']=len(points)
                out.loc[i,f'has_early_warning_opportunity_{H}d']=bool(full and len(points))
        # Each sample-event mapping includes all known future onsets, not only the first.
    out['onset_period']=out.onset_date.dt.year.map(lambda y:'unknown_left_censored' if pd.isna(y) else 'initial_reference_train' if y<=2019 else 'development' if y<=2022 else 'heldout')
    out['crosses_evaluation_boundary']=False
    for boundary in ['2020-01-01','2023-01-01']:
        out['crosses_evaluation_boundary']|=(out.observation_start_date<pd.Timestamp(boundary))&(out.exit_confirm_date.fillna(dates.iloc[-1])>=pd.Timestamp(boundary))
    return out

def temporal_folds(features,targets,cal):
    opened=cal.loc[cal.is_open.eq(1),'date'].reset_index(drop=True)
    plans=[]
    for year in [2020,2021,2022]:
        cutoff=opened[opened<pd.Timestamp(f'{year}-01-01')].max()
        end=opened[opened<=pd.Timestamp(f'{year}-12-31')].max()
        plans.append({'fold_id':f'dev-{year}','evaluation_start':pd.Timestamp(f'{year}-01-01'),'evaluation_end':pd.Timestamp(f'{year}-12-31'),'fit_cutoff':stamp([cutoff]).iloc[0],'evaluation_release_cutoff':stamp([end]).iloc[0],'kind':'development_expanding'})
    held=features.loc[features.asof_date.ge('2023-01-01')]
    for period,group in held.groupby(held.asof_date.dt.to_period('M')):
        first=group.asof_date.min();cutoff=opened[opened<first].max()
        plans.append({'fold_id':f'heldout-{period}','evaluation_start':period.start_time,'evaluation_end':period.end_time.normalize(),'fit_cutoff':stamp([cutoff]).iloc[0],'evaluation_release_cutoff':pd.NaT,'kind':'heldout_monthly_prequential_plan'})
    membership=[]
    for fold in plans:
        for row in targets.itertuples(index=False):
            if row.asof_date>fold['evaluation_end']:continue
            train=row.asof_time<=fold['fit_cutoff']
            evaluation=fold['evaluation_start']<=row.asof_date<=fold['evaluation_end']
            mature=pd.notna(row.label_available_at) and row.label_available_at<=fold['fit_cutoff']
            if train:
                role='train' if row.target_valid and mature else 'boundary_purged' if row.risk_set and not mature else 'excluded_train'
                reason='' if role=='train' else 'label_not_mature_at_fit_cutoff' if row.risk_set and not mature else row.exclusion_reason
            elif evaluation:
                cross=fold['kind']=='development_expanding' and pd.notna(row.label_available_at) and row.label_available_at>fold['evaluation_release_cutoff']
                role='validation_boundary_purged' if cross and row.risk_set else 'validation' if fold['kind']=='development_expanding' else 'heldout'
                reason='boundary_purged: label needs next evaluation year' if cross and row.risk_set else row.exclusion_reason
            else:continue
            membership.append({'fold_id':fold['fold_id'],'sample_id':row.sample_id,'horizon':row.horizon,'role':role,'reason':reason,'fit_cutoff':fold['fit_cutoff'],'label_available_at':row.label_available_at,'target_valid':row.target_valid,'eligible_for_fit':role=='train','parameter_selection_allowed':role=='validation' and row.target_valid})
    return pd.DataFrame(plans),pd.DataFrame(membership)

def whitelist():
    obj={'protocol_version':PROTOCOL['protocol_version'],'required_numeric':CORE_FEATURES+[x for x in STATE_FEATURES if x!='state_id'],'categorical':['state_id'],'valuation_optional':VALUATION_FEATURES,'observed_stock_proxy_optional':OPTIONAL_FEATURES,'default_primary_features':CORE_FEATURES+STATE_FEATURES,'forbidden_prefixes':['future_','y_','missing__'],'forbidden_metadata':['sample_id','index_code','episode_id','split','time_role','threshold_version','protocol_version','next_event_onset_type','asof_date','asof_time','reference_period_realtime_eligible','measurement_standard_available_at','state_history_start'],'missing_masks':'separate missing__ columns permitted only by explicit later fold-fitted design, not automatic all-numeric selection'}
    jsonwrite(CONFIG/'feature_whitelist.json',obj);return obj
