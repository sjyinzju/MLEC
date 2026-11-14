import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[2]/'scripts/research_v2'))
import numpy as np
import pandas as pd
import pytest
from common import stamp
from core import observations,path_mdd,thresholds,states,event_machine,all_events,build_weekly,full_week_dates,temporal_folds

def clean(prices,start='2015-01-05'):
    n=len(prices);dates=pd.bdate_range(start,periods=n)
    out=pd.DataFrame({'date':dates,'close':prices,'amount':np.full(n,10.),'amount_cny':np.full(n,10000.),'index_code':'000300.SH'})
    out['research_available_at']=stamp(dates);out['availability_basis']='synthetic_test_only'
    out['basic_observation_date']=out.date.shift(1);out['basic_research_available_at']=out.research_available_at
    out['basic_availability_basis']='synthetic_test_only'
    for col in ['turnover_rate','turnover_rate_f','pe','pe_ttm','pb','total_mv','float_mv','total_share','float_share','free_share']:out['basic_raw_'+col]=1.
    return out

def calendar(dates):
    d=pd.date_range(dates.min()-pd.Timedelta(days=7),dates.max()+pd.Timedelta(days=7))
    return pd.DataFrame({'date':d,'is_open':d.weekday<5})

@pytest.mark.parametrize('k',[5,20,60])
def test_k_returns_need_k_plus_one_prices(k):
    x=observations(clean(np.arange(100.,181.)))
    assert x[f'vol_{k}d'].iloc[:k].isna().all()
    expected=np.sqrt(252/k*np.log(np.arange(101.,101+k)/np.arange(100.,100+k)).dot(np.log(np.arange(101.,101+k)/np.arange(100.,100+k))))
    assert x[f'vol_{k}d'].iloc[k]==pytest.approx(expected)
    assert x[f'ret_{k}d'].iloc[k]==pytest.approx((100+k)/100-1)

def test_constant_path():
    x=observations(clean(np.full(90,100.)))
    assert pd.isna(x.log_return.iloc[0])
    assert x.loc[60,['vol_60d','mdd_60d','current_drawdown_60d','ret_60d']].eq(0).all()

def test_monotone_rise_not_zero_vol():
    x=observations(clean(np.arange(100.,190.)))
    assert x.mdd_20d.dropna().eq(0).all() and x.vol_20d.dropna().gt(0).all()

def test_slow_decline_and_downside_denominator():
    p=100*np.exp(-.01*np.arange(90));x=observations(clean(p))
    assert x.vol_20d.iloc[20]==pytest.approx(np.sqrt(252)*.01)
    assert x.downside_vol_20d.iloc[20]==pytest.approx(np.sqrt(252)*.01)
    assert x.mdd_20d.iloc[20]==pytest.approx(1-np.exp(-.2))

def test_mdd_differs_from_terminal_drawdown():
    p=np.r_[np.full(65,100.),50.,np.full(24,100.)];x=observations(clean(p))
    assert x.mdd_20d.iloc[70]==pytest.approx(.5)
    assert x.current_drawdown_20d.iloc[70]==0
    assert path_mdd([100,50,100])==.5

def test_future_drawdown_includes_prediction_price():
    p=np.full(110,100.);p[65:]=50.;x=observations(clean(p));thr=thresholds(x)
    s,e=all_events(x,states(x,thr));f,o,t,m=build_weekly(x,s,e,calendar(x.date),thr)
    anchor=x.date.iloc[64]
    value=o.loc[o.asof_date.eq(anchor),'future_mdd_20d'].iloc[0]
    assert value==.5

def test_strict_threshold_and_unknown_state():
    o=pd.DataFrame({'date':pd.bdate_range('2015-01-05',periods=4),'vol_20d':[np.nan,.1,.10000001,.1],'mdd_20d':[np.nan,.2,.2,.2000001]})
    t={'qV':.1,'qD':.2,'loss_metric':'mdd_20d','threshold_version':'test'};s=states(o,t)
    assert pd.isna(s.state_id.iloc[0]);assert s.state_id.iloc[1:].tolist()==[0,1,2]

def test_exit_confirmation_not_backdated_and_short_recovery_merged():
    d=pd.bdate_range('2015-01-05',periods=17);trigger=[0]*5+[1]+[0]*4+[1]+[0]*5+[0]
    s,e=event_machine(d,trigger,5)
    assert len(e)==1 and e.onset_date.iloc[0]==d[5] and e.last_stress_date.iloc[0]==d[10]
    assert e.exit_confirm_date.iloc[0]==d[15]
    assert s.episode_active.iloc[14]==1 and s.risk_set.iloc[15]

def test_left_and_right_censored_not_true_onsets():
    d=pd.bdate_range('2015-01-05',periods=8);s,e=event_machine(d,[1]*8)
    assert e.left_censored.iloc[0] and e.right_censored.iloc[0] and pd.isna(e.onset_date.iloc[0])
    assert not s.onset_today.any() and not s.risk_set.any()

def test_missing_breaks_known_state():
    d=pd.bdate_range('2015-01-05',periods=15);s,e=event_machine(d,[0]*5+[1,1,None,0,1]+[0]*5)
    assert len(e)==2 and e.interrupted_by_unknown.iloc[0] and e.left_censored.iloc[1]
    assert pd.isna(s.episode_active.iloc[7]) and not s.risk_set.iloc[8]
    assert s.risk_set.iloc[-1]

def test_initial_normal_not_assumed_known():
    s,e=event_machine(pd.bdate_range('2015-01-05',periods=5),[0]*5)
    assert s.episode_active.iloc[:4].isna().all();assert s.risk_set.iloc[-1]

def test_holiday_week_ends_thursday_and_partial_tail_excluded():
    d=pd.date_range('2024-01-01','2024-01-21');cal=pd.DataFrame({'date':d,'is_open':(d.weekday<5)&(d!=pd.Timestamp('2024-01-05'))})
    ends=full_week_dates(cal)
    assert pd.Timestamp('2024-01-04') in ends and pd.Timestamp('2024-01-05') not in ends
    observed_tail=pd.Timestamp('2024-01-10');assert observed_tail not in ends

def test_zero_amount_not_epsilon_and_units():
    data=clean(np.full(90,100.));data['amount']=0.;x=observations(data)
    assert x.amount_ratio_5_20.iloc[30:].isna().all()
    assert x.amount_ratio_missing_reason.iloc[30]=='nonpositive_denominator'
    data=clean(np.full(90,100.));assert data.amount_cny.iloc[0]==1000*data.amount.iloc[0]

def test_nonfinite_and_nonpositive_mdd_invalid():
    assert np.isnan(path_mdd([100,np.nan,90])) and np.isnan(path_mdd([100,0,90]))

def test_no_future_factor_normalization():
    p0,p1,a0,a1=10.,5.,1.,2.
    assert p1/p0*a1/a0-1==0
    assert p1/p0*(a1*99)/(a0*99)-1==0

def test_equal_pair_correlation_identity():
    x=np.array([[1.,2.,3.],[3.,5.,-1.],[2.,4.,1.],[4.,6.,-2.]])
    z=(x-x.mean(0))/x.std(0,ddof=1);n=x.shape[1];T=x.shape[0]
    lowdim=(np.square(z.sum(1)).sum()-n*(T-1))/(n*(n-1)*(T-1))
    full=np.corrcoef(x,rowvar=False);assert lowdim==pytest.approx(full[np.triu_indices(n,1)].mean())

def test_vol_to_compound_is_not_second_combined_episode():
    obs=observations(clean(np.full(20,100.)))
    s=pd.DataFrame({'date':obs.date,'valid_state':True,'V':pd.Series([0]*5+[1]*10+[0]*5,dtype='Int8'),'D':pd.Series([0]*9+[1]*6+[0]*5,dtype='Int8'),'threshold_version':'test'})
    s['raw_stress']=(s.V|s.D);s['state_id']=s.V+2*s.D;s['state_name']=s.state_id.map({0:'S0',1:'S1',2:'S2',3:'S3'})
    sd,e=all_events(obs,s);assert len(e[e.dimension=='combined'])==1 and len(e[e.dimension=='drawdown'])==1
    assert e.loc[e.dimension.eq('drawdown'),'onset_date'].iloc[0]==obs.date.iloc[9]

def test_tail_and_active_targets_are_na():
    x=observations(clean(100*np.exp(.001*np.arange(100))))
    t=thresholds(x);s,e=all_events(x,states(x,t));f,o,y,m=build_weekly(x,s,e,calendar(x.date),t)
    for row in y.itertuples():
        target=getattr(row,f'y_new_episode_next{row.horizon}')
        if not row.horizon_complete or not row.risk_set:assert pd.isna(target)

def test_quantile_linear_is_explicit():
    assert np.quantile([0.,10.],.8,method='linear')==8.

def test_unknown_future_rolling_state_not_zero():
    x=observations(clean(np.full(100,100.)));thr=thresholds(x)
    s,e=all_events(x,states(x,thr));f,o,y,m=build_weekly(x,s,e,calendar(x.date),thr)
    assert pd.isna(o.y_any_stress_next20.iloc[0])
    assert o.y_future_window_stress_20d.iloc[0]==0

def test_peak_type_excludes_normal_recovery():
    obs=observations(clean(np.full(20,100.)))
    s=pd.DataFrame({'date':obs.date,'valid_state':True,'V':pd.Series([0]*5+[1]+[0]*14,dtype='Int8'),'D':pd.Series([0]*20,dtype='Int8'),'threshold_version':'test'})
    s['raw_stress']=s.V|s.D;s['state_id']=s.V+2*s.D;s['state_name']=s.state_id.map({0:'S0',1:'S1',2:'S2',3:'S3'})
    sd,e=all_events(obs,s)
    assert e.loc[e.dimension.eq('combined'),'retrospective_peak_type'].iloc[0]=='S1'
