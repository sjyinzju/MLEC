"""Economic feature scope and machine-enforced missingness adjudications."""
import numpy as np
import pandas as pd
from .common import *
from .release import cutoff

GROUPS=['growth','prices','credit','rates','external']
CHOSEN={'pmi_mfg','pmi_new_orders','industrial_va_yoy','retail_sales_yoy','gdp_real_yoy',
 'cpi_yoy','ppi_yoy','m2_yoy','rmb_loan_balance_yoy','new_rmb_loans','shibor_on','shibor_1w','shibor_3m',
 'dr007','cgb_1y','cgb_10y','term_spread_10y_1y','usdcny_fixing','fx_reserves',
 'exports_cny_ytd_yoy','imports_cny_ytd_yoy'}

def macro_facts():
    f=pd.read_parquet(ROOT/'data/standardized/macro/v4/macro_facts.parquet')
    p=OUT/'sources/macro_repairs.parquet'
    if p.exists():f=pd.concat([f,pd.read_parquet(p)],ignore_index=True)
    assert f.source_record_id.is_unique
    return f

def structural_period(sid,date):
    from scripts.data_foundation_v3.quality import structural
    existing=structural(sid,date)
    if existing:return existing
    if sid in ['exports_cny_ytd_yoy','imports_cny_ytd_yoy'] and date.year in [2020,2022] and date.month==1:
        return 'JAN_NOT_SEPARATELY_RELEASED_COMBINED_JAN_FEB'
    if sid in ['exports_cny_yoy','imports_cny_yoy'] and date.year in [2020,2022] and date.month in [1,2]:
        return 'ONLY_COMBINED_CUMULATIVE_NO_TIMELY_STANDALONE_MONTH'
    return None

def period_audit(f,specs):
    from .macro import prepare
    allowed=prepare(f);cal=read('calendar').date;rows=[]
    for s in specs:
        sid=s['series_id'];g=allowed[allowed.series_id.eq(s.get('source_series_id',sid))]
        if 'filter_scope_id' in s:g=g[g.statistical_scope_id.eq(s['filter_scope_id'])]
        grouped=g.groupby('period_end').effective_available_at.agg(['min','size'])
        start=max(pd.Timestamp(s['required_start']),pd.Timestamp('2014-12-01'))
        end=min(pd.Timestamp(s['required_end']),cutoff())
        if s['frequency']=='D':periods=cal[(cal>=max(start,pd.Timestamp('2015-01-01')))&(cal<=end)]
        else:
            last=(cutoff().to_period('M')-1).end_time.normalize() if s['frequency']=='M' else (cutoff().to_period('Q')-1).end_time.normalize()
            periods=pd.date_range(start,min(end,last),freq='ME' if s['frequency']=='M' else 'QE')
        for date in periods:
            exists=date in grouped.index;structural=structural_period(s.get('source_series_id',sid),date)
            # These monthly production reports normally arrive mid/late next month.
            due=date+pd.offsets.MonthBegin(1)+pd.Timedelta(days=19)
            if s['frequency']=='D':due=date+pd.Timedelta(days=1)
            if exists:status='AVAILABLE' if grouped.loc[date,'min']<=clock(cutoff()) else 'NOT_YET_RELEASED_AT_SNAPSHOT'
            elif structural:status='STRUCTURAL_NOT_RELEASED'
            elif due>cutoff() and (s.get('source_series_id',sid) in ['industrial_va_yoy','industrial_va_ytd_yoy','retail_sales_yoy','retail_sales_ytd_yoy','fai_ytd_yoy','new_rmb_loans','rmb_loans_ytd_flow'] or sid.startswith('tsf_')):status='NOT_YET_DUE'
            else:status='SOURCE_GAP'
            rows.append(dict(series_id=sid,series_group=s['series_group'],period_end=date,status=status,
                reason=structural or status,first_available_at=grouped.loc[date,'min'] if exists else pd.NaT,
                due_at=clock(due),source_records=int(grouped.loc[date,'size']) if exists else 0))
    return pd.DataFrame(rows)

def build_policy():
    from .macro import feature_specifications,SCOPED_INPUTS
    specs=[s for s in feature_specifications() if s.get('required',True)];audit=period_audit(macro_facts(),specs)
    frame('release/macro_period_audit',audit)
    bad=set(audit.loc[audit.status.eq('SOURCE_GAP'),'series_id'])
    # Stock growth scopes are independent institutional regimes, never spliced.
    chosen=CHOSEN|{s['series_id'] for s in specs if s['concept_id']=='tsf_stock_yoy'}
    chosen -= set(SCOPED_INPUTS)
    chosen |= {s['series_id'] for s in specs if s.get('source_series_id') in SCOPED_INPUTS}
    decisions=[]
    for s in specs:
        sid=s['series_id'];formal=sid in chosen and sid not in bad
        reason='ECONOMICALLY_SPECIFIED_COMPLETE_APPLICABLE_PERIODS' if formal else 'UNRESOLVED_SOURCE_PERIOD_GAP' if sid in bad else 'CANDIDATE_ONLY_REDUNDANT_LEVEL_OR_ALTERNATE_DEFINITION'
        if sid in ['exports_cny_yoy','imports_cny_yoy']:reason='EXCLUDE_MONTHLY_SERIES_INCOMPATIBLE_COMBINED_PERIODS_AND_UNRECOVERED_2025_02; use separate CNY YTD series'
        if sid in SCOPED_INPUTS:reason='SOURCE_ONLY; formal columns split into independent documented statistical-scope definitions'
        decisions.append(dict(series_id=sid,group=s['series_group'],formal=formal,reason=reason,
            exclude_all_derived=not formal,source_gap_periods=audit.loc[audit.series_id.eq(sid)&audit.status.eq('SOURCE_GAP'),'period_end'].astype(str).tolist()))
    result=dict(version='formal-missing-policy-v1',cutoff=str(cutoff().date()),series=decisions,
        numeric_policy='train-only variable numeric columns; all-empty and constant value columns dropped; original-column missing indicators fixed; median/IQR from train only',
        categorical_policy='state IDs nominal; one-hot training categories plus explicit missing/unseen reserved states; no scaling of IDs',
        label_policy='No label imputation; invalid/unmatured windows excluded from train/score identically for all information sets',
        source_gap_hold='legal last release may remain in candidate pool, with registered SOURCE_GAP_HELD_VALUE; excluded series cannot enter formal groups or complements',
        reasonable_missing=['historical_warmup','institutional_not_applicable','not_yet_released','confirmed_suspension','future_window_immature'])
    result['policy_version']=digest(result)[:20];write(OUT/'missing_policy.json',result)
    dependencies=[dict(role='object_and_labels',parents=['sources/index_*.parquet','sources/trade_calendar.parquet','security_history','membership_snapshots',
        'standardized stock_daily_observations,stock_adjustment_observations,stock_daily_basic_observations,float_share','sources/factor_adjudication','confirmed suspension evidence'],
        fields=['adjusted log return','close','volume_shares','amount_cny','float_shares','valid listing/code interval','member snapshot date']),
        dict(role='formal_M',parents=['past_window_outcomes(5,20,60)','fixed state dictionary/current and lagged memberships','same-asof cross-market 20-day core']),
        dict(role='formal_Z',parents=[r['series_id'] for r in decisions if r['formal']],availability='effective_available_at <= asof_time; latest economic period, with comparable transforms'),
        dict(role='source_verification',parents=['dividend/ex-date events','original source IDs/URLs/timestamps','code-change notices','index conflict decisions','read-only QuantData metadata']),
        dict(role='outside_formal_research',parents=['valuation PE/PB','moneyflow','margin security tables','other indexes','unselected or excluded macro series'],note='Retained source pool; not a completion gate')]
    write(OUT/'research_dependencies.json',dict(protocol=VERSION,snapshot='mlec-formal-20261113',dependencies=dependencies))
    return result
