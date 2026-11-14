"""Executed formula tests, real-data invariance checks, frozen sensitivity and sample accounting."""
from __future__ import annotations
import subprocess
import sys
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from common import *
from core import *

def assert_semantic_equal(left,right):
    # Parquet represents object nulls as None, NumPy calculations can produce NaN.
    # Both mean missing; normalize only null representation, never values or columns.
    left=left.copy();right=right.copy()
    for frame in [left,right]:
        for col in frame.select_dtypes(include='object'):
            frame[col]=frame[col].where(frame[col].notna(),None)
    assert_frame_equal(left,right,check_dtype=False)

def proxy_at_cutoff(cutoff):
    """Re-read only derived eligible observations up to cutoff; reselect complete same-date windows."""
    sourcefiles=sorted((DATA/'stock_proxy_inputs').glob('*.parquet'))
    assert len(sourcefiles)==12,'Full real stock checkpoints required for invariance test'
    dates=pd.read_parquet(DATA/'market_daily_clean.parquet').date
    window=dates[dates<=cutoff].tail(60);start=window.min().strftime('%Y%m%d');end=window.max().strftime('%Y%m%d')
    c=db();files=','.join(qs(p) for p in sourcefiles)
    x=c.execute(f"SELECT ts_code,trade_date,adjusted_return,amihud_daily FROM read_parquet([{files}]) WHERE trade_date BETWEEN '{start}' AND '{end}'").df();c.close()
    rr=x.pivot(index='trade_date',columns='ts_code',values='adjusted_return').reindex(window.dt.strftime('%Y%m%d'))
    ar=x.pivot(index='trade_date',columns='ts_code',values='amihud_daily').reindex(window.dt.strftime('%Y%m%d'))
    last=rr.iloc[-1].dropna();complete=rr.dropna(axis=1).to_numpy();sd=complete.std(axis=0,ddof=1);complete=complete[:,sd>0];n=complete.shape[1]
    z=(complete-complete.mean(0))/complete.std(0,ddof=1)
    rho=(np.square(z.sum(1)).sum()-n*59)/(n*(n-1)*59)
    ami20=ar.tail(20).dropna(axis=1).mean(0)
    return {'down_fraction_proxy':float((last<0).mean()),'mean_corr_60d_proxy':float(rho),'amihud_20d_proxy':float(ami20.mean()),'amihud_20d_median_proxy':float(ami20.median())}

def real_stock_boundary_check():
    dates=pd.read_parquet(DATA/'market_daily_clean.parquet').date
    c=db();evidence=[]
    symbols=['000001.SZ','600000.SH','600519.SH']
    for year in range(2015,2027):
        ix=dates.index[dates.dt.year.eq(year)][0]
        if ix==0:ix=1
        previous=dates.iloc[ix-1].strftime('%Y%m%d');current=dates.iloc[ix].strftime('%Y%m%d')
        predicate='ts_code IN ('+','.join(qs(x) for x in symbols)+f") AND trade_date IN ('{previous}','{current}')"
        ds=latest('daily',predicate);fs=latest('adj_factor',predicate);ss=latest('suspend_d',predicate)
        raw=query(c,f'SELECT d.ts_code,d.trade_date,d.close,d.amount,d.vol,f.adj_factor FROM ({ds}) d LEFT JOIN ({fs}) f USING(ts_code,trade_date)',f'independent_stock_boundary_{year}')
        susp=query(c,f"SELECT ts_code,trade_date FROM ({ss}) WHERE suspend_type='S'",f'independent_suspension_boundary_{year}')
        panel=c.execute(f"SELECT ts_code,adjusted_return,amihud_daily FROM read_parquet({qs(DATA/f'stock_proxy_inputs/{year}.parquet')}) WHERE trade_date='{current}' AND ts_code IN ("+','.join(qs(x) for x in symbols)+')').df().set_index('ts_code')
        for symbol in symbols:
            rows=raw.loc[raw.ts_code.eq(symbol)].set_index('trade_date')
            valid=len(rows)==2 and set(rows.index)=={previous,current} and not susp.ts_code.eq(symbol).any()
            if valid:
                numbers=rows[['close','amount','vol','adj_factor']].to_numpy()
                valid=np.isfinite(numbers).all() and (numbers>0).all()
            if valid:
                value=(rows.loc[current,'close']*rows.loc[current,'adj_factor'])/(rows.loc[previous,'close']*rows.loc[previous,'adj_factor'])-1
                illiq=abs(value)/(1000*rows.loc[current,'amount'])
                assert symbol in panel.index
                np.testing.assert_allclose(panel.loc[symbol,'adjusted_return'],value,rtol=1e-10,atol=1e-14)
                np.testing.assert_allclose(panel.loc[symbol,'amihud_daily'],illiq,rtol=1e-10,atol=1e-20)
            else:assert symbol not in panel.index
            evidence.append({'year':year,'code':symbol,'previous':previous,'current':current,'valid_adjacent_pair':bool(valid),'status':'PASS'})
    c.close();jsonwrite(AUDIT/'independent_stock_boundary_checks.json',evidence)
    return len(evidence)

def period_stats(obs,state,episodes,features,targets,mapping,start,end,exit_days=5):
    # Truncate event recursion at period end so final durations do not import later outcomes.
    mask=obs.date.le(end);so=obs.loc[mask].reset_index(drop=True);ss=state.loc[mask].reset_index(drop=True)
    sd,ee=all_events(so,ss[['date','valid_state','V','D','state_id','state_name','raw_stress','threshold_version','protocol_version']],exit_days)
    valid=sd.loc[sd.date.between(start,end)&sd.valid_state]
    ev=ee.loc[ee.dimension.eq('combined')&ee.observation_start_date.between(start,end)]
    known=ev.loc[~ev.left_censored]
    counts=valid.state_name.value_counts().to_dict()
    stats={'start':start,'end':end,'valid_state_days':len(valid),'state_counts':counts,'state_shares':{k:v/len(valid) for k,v in counts.items()},'raw_stress_days':int(valid.raw_stress.eq(1).sum()),'known_new_combined_events':len(known),'left_censored_episodes':int(ev.left_censored.sum()),'right_censored_episodes':int(ev.right_censored.sum()),'median_observed_episode_days':float(ev.retrospective_duration_days.median()) if len(ev) else None,'max_observed_episode_days':int(ev.retrospective_duration_days.max()) if len(ev) else None,'one_stress_day_episodes':int(ev.stress_days.eq(1).sum()),'stress_days_per_event_median':float(ev.stress_days.median()) if len(ev) else None,'recovery_days_inside_active_episode':int((valid.raw_stress.eq(0)&valid.combined_episode_active.eq(1)).sum())}
    transitions=pd.crosstab(valid.state_name.shift(1),valid.state_name).to_dict()
    stats['transitions']=transitions
    for name,col in [('downside_vol_20d','downside_vol_20d'),('worst_daily_return_20d','worst_daily_return_20d'),('current_drawdown_20d','current_drawdown_20d')]:
        joined=obs[['date',col]].merge(state[['date','state_name']],on='date')
        stats[name+'_by_state']=joined.loc[joined.date.between(start,end)].groupby('state_name')[col].agg(['mean','median','count']).to_dict('index')
    if (DATA/'stock_market_proxies_daily.parquet').exists():
        proxy=pd.read_parquet(DATA/'stock_market_proxies_daily.parquet')
        joined=proxy[['date','down_fraction_proxy']].merge(state[['date','state_name']],on='date')
        stats['down_fraction_proxy_by_state']=joined.loc[joined.date.between(start,end)].groupby('state_name').down_fraction_proxy.agg(['mean','median','count']).to_dict('index')
    return stats

def sample_chain(features,targets,mapping,episodes,start,end):
    f=features.loc[features.asof_date.between(start,end)]
    y=targets.loc[targets.horizon.eq(20)&targets.sample_id.isin(f.sample_id)]
    good=y.loc[y.target_valid]
    eventmap=mapping.loc[mapping.horizon.eq(20)&mapping.dimension.eq('combined')&mapping.at_risk_at_prediction&mapping.sample_id.isin(good.sample_id)]
    ev=episodes.loc[episodes.dimension.eq('combined')&episodes.onset_date.between(start,end)]
    mature=good.loc[good.label_available_at<=stamp([pd.Timestamp(end)]).iloc[0]]
    maturemap=eventmap.loc[eventmap.sample_id.isin(mature.sample_id)]
    return {'start':start,'end':end,'candidate_weeks':len(f),'market_feature_complete_weeks':int(f.market_features_complete.sum()),'main_at_risk_weeks':int(y.risk_set.sum()),'complete_main_label_weeks':len(good),'positive_weeks':int(good.y_new_episode_next20.eq(1).sum()),'negative_weeks':int(good.y_new_episode_next20.eq(0).sum()),'deduplicated_events_covered':int(eventmap.episode_id.nunique()),'events_with_true_warning_opportunity':int(ev.has_early_warning_opportunity_20d.sum()),'known_new_events_in_period':len(ev),'mature_by_period_end_weeks':len(mature),'positive_mature_by_period_end':int(mature.y_new_episode_next20.eq(1).sum()),'deduplicated_mature_events':int(maturemap.episode_id.nunique()),'boundary_unmatured_weeks':len(good)-len(mature),'exclusion_reasons':y.exclusion_reason.value_counts().to_dict(),'valid_sample_start':str(good.asof_date.min().date()) if len(good) else None,'valid_sample_end':str(good.asof_date.max().date()) if len(good) else None}

def sensitivity(obs,cal,main_state,main_ep,main_targets):
    default=[];held=[]
    for spec in PROTOCOL['single_factor_sensitivity']:
        ident=spec['id'];q=spec.get('quantile',.8);metric=spec.get('loss_metric','mdd_20d');exit_days=spec.get('exit_normal_days',5)
        if ident in ['h5','h40']:
            state=main_state;ep=main_ep;target=main_targets.loc[main_targets.horizon.eq(spec['horizon'])].copy();thr=readjson(CONFIG/'thresholds.json')
        else:
            thr=thresholds(obs,q,metric);state,ep=all_events(obs,states(obs,thr),exit_days)
            f,o,target,mapping=build_weekly(obs,state,ep,cal,thr,horizons=(20,))
            saveframe(DATA/f'sensitivity/{ident}/state_labels_daily.parquet',state)
            saveframe(DATA/f'sensitivity/{ident}/risk_episodes.parquet',ep)
            saveframe(DATA/f'sensitivity/{ident}/prediction_targets_weekly.parquet',target)
        jsonwrite(CONFIG/f'sensitivity/{ident}.json',{'single_factor':spec,'threshold':thr,'all_other_parameters_fixed':True})
        for role,start,end in [('reference','2015-01-01','2019-12-31'),('development','2020-01-01','2022-12-31'),('heldout','2023-01-01','2026-09-22')]:
            keep=state.date.between(start,end)&state.valid_state&main_state.valid_state
            truncated=obs.date.le(end)
            op=obs.loc[truncated].reset_index(drop=True)
            _,main_period_ep=all_events(op,main_state.loc[truncated].reset_index(drop=True),5)
            _,variant_period_ep=all_events(op,state.loc[truncated].reset_index(drop=True),exit_days)
            me=main_period_ep.loc[main_period_ep.dimension.eq('combined')&main_period_ep.onset_date.between(start,end)]
            ve=variant_period_ep.loc[variant_period_ep.dimension.eq('combined')&variant_period_ep.onset_date.between(start,end)]
            # Greedy one-to-one nearest observed onset within 20 trading days; evaluation diagnostic only.
            pos={d:i for i,d in enumerate(obs.date)};remaining=list(ve.onset_date);shifts=[]
            for d in me.onset_date:
                if not remaining:break
                j=min(range(len(remaining)),key=lambda k:abs(pos[remaining[k]]-pos[d]))
                delta=pos[remaining[j]]-pos[d]
                if abs(delta)<=20:shifts.append(delta);remaining.pop(j)
            yy=target.loc[target.asof_date.between(start,end)]
            active=yy.loc[yy.target_valid];field=f'y_new_episode_next{spec.get("horizon",20)}'
            base_target=main_targets.loc[main_targets.horizon.eq(20),['sample_id','y_new_episode_next20']]
            compared=active[['sample_id',field]].rename(columns={field:'variant_target'}).merge(base_target.rename(columns={'y_new_episode_next20':'main_target'}),on='sample_id')
            a,b='variant_target','main_target'
            valid_cmp=compared[[a,b]].dropna()
            row={'variant':ident,'period':role,'state_agreement':float((state.loc[keep,'state_id']==main_state.loc[keep,'state_id']).mean()),'known_events':len(ve),'main_known_events':len(me),'event_count_change':len(ve)-len(me),'onsets_matched_within20':len(shifts),'median_signed_onset_shift_trading_days':float(np.median(shifts)) if shifts else None,'max_abs_onset_shift_trading_days':int(np.max(np.abs(shifts))) if shifts else None,'single_stress_day_episode_count':int(ve.stress_days.eq(1).sum()),'valid_targets':len(active),'positive_targets':int(active[field].eq(1).sum()),'target_agreement_on_common_valid_samples':float(valid_cmp[a].eq(valid_cmp[b]).mean()) if len(valid_cmp) else None,'state_category_counts':state.loc[keep,'state_name'].value_counts().to_dict()}
            (held if role=='heldout' else default).append(row)
    jsonwrite(AUDIT/'sensitivity_reference_development.json',default)
    jsonwrite(REPORT/'heldout/sensitivity_details.json',held)

def run_validation():
    log('validation_start')
    result=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider',str(BASE/'tests/research_v2'),'--junitxml='+str(AUDIT/'unit_tests.xml')],capture_output=True,text=True,encoding='utf-8',cwd=BASE)
    (AUDIT/'logs/unit_tests.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
    if result.returncode:raise RuntimeError('Formula/event tests failed; see audit/research_v2/logs/unit_tests.log')
    xml=ET.parse(AUDIT/'unit_tests.xml').getroot();suites=xml.findall('testsuite')
    checks=[{'check':'formula_and_event_unit_tests','status':'PASS','tests':sum(int(x.attrib['tests']) for x in suites)}]
    clean=pd.read_parquet(DATA/'market_daily_clean.parquet');obs=pd.read_parquet(DATA/'market_observations_daily.parquet');state=pd.read_parquet(DATA/'state_labels_daily.parquet');episodes=pd.read_parquet(DATA/'risk_episodes.parquet');features=pd.read_parquet(DATA/'market_features_weekly.parquet');targets=pd.read_parquet(DATA/'prediction_targets_weekly.parquet');mapping=pd.read_parquet(DATA/'sample_to_event.parquet');cal=pd.read_parquet(AUDIT/'sse_calendar.parquet');thr=readjson(CONFIG/'thresholds.json')
    full=observations(clean);assert_frame_equal(full,obs,check_dtype=False)
    checks.append({'check':'full_real_observations_recomputed','status':'PASS','rows':len(obs)})
    compare_cols=CORE_FEATURES+['turnover_rate_lag1','pe_lag1','feature_start','feature_end','feature_available_at']
    state_cols=['state_id','V','D','raw_stress','combined_episode_active','combined_risk_set','combined_onset_today','combined_elapsed_episode_days','combined_normal_run','vol_onset_today','drawdown_onset_today']
    for cutoff in ['2020-06-30','2022-12-30','2024-06-28']:
        truncated=clean.loc[clean.date.le(cutoff)].reset_index(drop=True);oo=observations(truncated);ss,ee=all_events(oo,states(oo,thr))
        assert_frame_equal(oo[compare_cols],obs.loc[obs.date.le(cutoff),compare_cols].reset_index(drop=True),check_dtype=False)
        assert_frame_equal(ss[state_cols],state.loc[state.date.le(cutoff),state_cols].reset_index(drop=True),check_dtype=False)
        proxy=proxy_at_cutoff(pd.Timestamp(cutoff));fullproxy=pd.read_parquet(DATA/'stock_market_proxies_daily.parquet').set_index('date').loc[cutoff]
        for field,value in proxy.items():np.testing.assert_allclose(value,fullproxy[field],rtol=1e-10,atol=1e-18)
        checks.append({'check':'real_history_truncation_invariance','cutoff':cutoff,'status':'PASS','rows':len(oo),'includes_stock_proxy_reselection':True})
    cutoff=pd.Timestamp('2022-06-30');mutated=clean.copy();mutated.loc[mutated.date>cutoff,'close']*=np.linspace(.25,2.,(mutated.date>cutoff).sum())
    mm=observations(mutated);ms,me=all_events(mm,states(mm,thr));prior=obs.date.le(cutoff)
    assert_frame_equal(mm.loc[prior,compare_cols],obs.loc[prior,compare_cols],check_dtype=False)
    assert_frame_equal(ms.loc[prior,state_cols],state.loc[prior,state_cols],check_dtype=False)
    assert thresholds(mm)==thr
    checks.append({'check':'future_price_perturbation_and_reference_threshold_invariance','status':'PASS','cutoff':str(cutoff.date())})
    for H in [20,5,40]:
        y=targets.loc[targets.horizon.eq(H)];field=f'y_new_episode_next{H}'
        assert y.loc[~y.target_valid,field].isna().all()
        assert y.loc[y.target_valid,field].isin([0,1]).all()
        assert y.loc[y.target_valid,'label_available_at'].eq(stamp(y.loc[y.target_valid,'label_end']).set_axis(y.index[y.target_valid])).all()
        assert (y.loc[y.target_valid,'label_end']>y.loc[y.target_valid,'asof_date']).all()
        assert y.loc[~y.risk_set,field].isna().all()
    membership=pd.read_parquet(DATA/'fold_membership.parquet');plan=pd.read_parquet(AUDIT/'fold_manifest.parquet')
    train=membership.loc[membership.eligible_for_fit]
    assert train.label_available_at.le(train.fit_cutoff).all()
    joined=train.merge(targets[['sample_id','horizon','label_end','asof_time']],on=['sample_id','horizon'],validate='many_to_one')
    assert joined.asof_time.le(joined.fit_cutoff).all()
    standard=targets[['sample_id','horizon','measurement_standard_available_at']]
    standard_join=train.merge(standard,on=['sample_id','horizon'],validate='many_to_one')
    assert standard_join.measurement_standard_available_at.le(standard_join.fit_cutoff).all()
    assert (features.feature_available_at<=features.asof_time).all()
    assert features.basic_research_available_at.dropna().le(features.loc[features.basic_research_available_at.notna(),'asof_time']).all()
    assert features.loc[features.basic_observation_date.notna(),'basic_observation_date'].lt(features.loc[features.basic_observation_date.notna(),'asof_date']).all()
    for fold in plan.loc[plan.kind.eq('development_expanding')].itertuples():
        j=joined.loc[joined.fold_id.eq(fold.fold_id)]
        assert j.label_end.lt(fold.evaluation_start).all(),'Training outcomes overlap validation year'
    assert membership.loc[membership.role.eq('validation_boundary_purged'),'parameter_selection_allowed'].eq(False).all()
    checks.append({'check':'all_horizon_maturity_risk_sets_and_all_fold_boundaries','status':'PASS','folds':len(plan),'fit_memberships':len(train),'boundary_purged_memberships':int(membership.role.isin(['boundary_purged','validation_boundary_purged']).sum())})
    white=whitelist();inputs=white['default_primary_features']+white['valuation_optional']+white['observed_stock_proxy_optional']
    assert not any(x.startswith(('future_','y_')) or x in white['forbidden_metadata'] for x in inputs)
    assert not any(x.startswith(('future_','y_')) or 'retrospective' in x for x in features)
    checks.append({'check':'feature_input_whitelist_and_physical_target_separation','status':'PASS','default_features':len(white['default_primary_features'])})
    extended=pd.read_parquet(DATA/'market_features_weekly_with_proxies.parquet')
    assert extended.sample_id.tolist()==features.sample_id.tolist()
    assert extended.proxy_available_at.le(extended.asof_time).all()
    assert extended.proxy_status.str.startswith('PROXY').all()
    checks.append({'check':'proxy_availability_and_same_market_sample_ids','status':'PASS','rows':len(extended)})
    checks.append({'check':'independent_raw_stock_year_boundary_return_and_CNY_units','status':'PASS','cases':real_stock_boundary_check()})
    # Main horizon does not shrink to auxiliary H40 eligibility.
    y20=targets.loc[targets.horizon.eq(20)];y40=targets.loc[targets.horizon.eq(40)]
    assert y20.target_valid.sum()>=y40.target_valid.sum()
    assert len(features.loc[features.market_features_complete].merge(y20.loc[y20.horizon_complete],on='sample_id'))==582
    # Rebuild full real state/episode/target chain and compare semantics; no random sample used.
    s2,e2=all_events(full,states(full,thr));f2,o2,t2,m2=build_weekly(full,s2,e2,cal,thr)
    e2=event_opportunities(e2,f2,t2,m2,obs.date)
    assert_semantic_equal(s2,state);assert_semantic_equal(f2,features)
    assert_semantic_equal(t2,targets);assert_semantic_equal(m2,mapping)
    assert_semantic_equal(e2,episodes)
    assert_semantic_equal(o2,pd.read_parquet(DATA/'future_outcomes_weekly.parquet'))
    checks.append({'check':'complete_real_core_pipeline_semantic_reproduction','status':'PASS','weekly_rows':len(features),'target_rows':len(targets),'candidate_60past_20future':582})
    # No filtering/sensitivity ranking based on heldout statistics.
    sensitivity(obs,cal,state,episodes,targets)
    stats={};chains={}
    for role,start,end in [('reference','2015-01-01','2019-12-31'),('development','2020-01-01','2022-12-31'),('heldout','2023-01-01','2026-09-22')]:
        stat=period_stats(obs,state,episodes,features,targets,mapping,start,end)
        chain=sample_chain(features,targets,mapping,episodes,start,end)
        if role=='heldout':jsonwrite(REPORT/'heldout/state_event_diagnostics.json',stat);jsonwrite(REPORT/'heldout/sample_chain.json',chain)
        else:stats[role]=stat;chains[role]=chain
    jsonwrite(AUDIT/'reference_development_statistics.json',stats);jsonwrite(AUDIT/'sample_count_chain.json',chains)
    jsonwrite(AUDIT/'validation_checks.json',{'status':'PASS','checks':checks,'no_models_trained':True})
    saveframe(AUDIT/'sample_exclusions.parquet',targets.loc[~targets.target_valid])
    saveframe(AUDIT/'boundary_purged.parquet',membership.loc[membership.role.isin(['boundary_purged','validation_boundary_purged'])])
    jsonwrite(CONFIG/'paired_prediction_schema.json',{'key':['sample_id','fold_id','horizon','model_id'],'required_columns':{'sample_id':'same M and M+Z market ID','fold_id':'frozen manifest','horizon':'20 primary,5/40 auxiliary','model_id':'M or M_plus_Z','probability':'future actual model probability in [0,1]; no fabricated values','trained_at_cutoff':'must match fold fit_cutoff','feature_version':'frozen version','common_sample_version':'same for paired models'},'pairing':'inner join on shared sample_id,fold_id,horizon after joint macro-coverage acceptance, NOT independently dropped samples','scoring':['Brier','Log Loss','event detection','false alarms','lead_to_trigger'],'event_attribution':'onset date defines evaluation period; earliest eligible pre-onset alarm per event, no duplicate event count across samples; multiple alarms are not multiple events','lead_to_trigger':'SSE trading-day distance from alarm to frozen threshold-trigger onset, not crash beginning','mature_label_release':'end of full H at 18:00, symmetric for positive/negative','no_predictions_produced':True})
    log('validation_complete',checks=len(checks),tests=checks[0]['tests'])
