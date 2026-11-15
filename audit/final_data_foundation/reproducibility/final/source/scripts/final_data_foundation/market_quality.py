"""Field/date exceptions supplement dataset-level qualifications; no hidden fill."""
import numpy as np
from .common import *
from .market import rel


def build():
    pieces=[]
    for p in sorted((AUDIT/'source_reconciliation/basic_arithmetic').glob('*.parquet')):
        d=pd.read_parquet(p)
        for field,residual in [('total_mv','total_mv_residual'),('circ_mv','circ_mv_residual'),('turnover_rate','turnover_residual'),('turnover_rate_f','free_turnover_residual')]:
            if field.endswith('mv'):
                flagged=d[residual].abs().gt(np.maximum(.011,d.close*.00005+.00005));precision=d[residual].abs().le(d.close*.0101+.001)
            else:flagged=d[residual].abs().gt(.0001);precision=pd.Series(False,index=d.index)
            q=d.loc[flagged,['ts_code','trade_date','source_record_id']].copy();q['field']=field;q['dataset_id']='stock_daily_basic'
            q['quality_status']=np.where(precision[flagged],'QUALIFIED_EMPIRICAL_SHARE_PRECISION','BLOCKED_UNRESOLVED_SHARE_DENOMINATOR')
            q['quality_reason']=np.where(precision[flagged],'Difference fits 0.01 ten-thousand-share precision; empirical tolerance is not a certified provider precision specification.','Price/share or volume/float identity inconsistent beyond declared tight precision; no silent replacement of source denominator.')
            q['evidence_path']=p.relative_to(ROOT).as_posix();pieces.append(q)
    c=db()
    for year in range(2014,2027):
        path=MARKET/'stock_daily_basic_observations'/f'{year}.parquet'
        for field in ['close','turnover_rate','turnover_rate_f','pe','pe_ttm','pb','total_mv','circ_mv']:
            d=c.execute('SELECT ts_code,trade_date,source_record_id FROM read_parquet(?) WHERE "'+field+'" IS NULL',[str(path)]).df()
            d['field']=field;d['dataset_id']='stock_daily_basic'
            d['quality_status']='UNDEFINED_OR_UNAVAILABLE_PE' if field in ['pe','pe_ttm'] else 'BLOCKED_MISSING_REQUIRED_FIELD'
            d['quality_reason']='Loss-making/undefined PE may be structurally unavailable, but missing PE alone does not prove the reason; do not impute.' if field in ['pe','pe_ttm'] else 'Required source field absent, including explicit quarantine after independent close repair.'
            d['evidence_path']=path.relative_to(ROOT).as_posix()
            if field in ['close','turnover_rate','turnover_rate_f'] and len(d):
                c.register('null_input',d)
                d=c.execute('SELECT n.*,s.status trading_status FROM null_input n LEFT JOIN (SELECT ts_code,trade_date,status FROM '+rel('stock_trading_status')+' WHERE trade_date BETWEEN ? AND ?) s USING(ts_code,trade_date)',[f'{year}0101',min(f'{year}1231',END)]).df()
                halted=d.trading_status.isin(['SUSPENDED_SOURCE_RECORDED','SUSPENDED_OFFICIAL_EVIDENCE'])
                d.loc[halted,'quality_status']='STRUCTURAL_SUSPENSION_NO_TRADE'
                d.loc[halted,'quality_reason']='No observed trade on an explicitly source-/official-evidenced suspension date. Close/turnover is not a missing traded observation; no synthetic quote or zero-turnover fill.'
                d.loc[halted,'evidence_path']=(MARKET/'stock_trading_status'/f'{year}.parquet').relative_to(ROOT).as_posix()
                d=d.drop(columns='trading_status');c.unregister('null_input')
            pieces.append(d)
    for p in sorted((MARKET/'stock_adjustment_observations').glob('*.parquet')):
        d=c.execute("SELECT ts_code,trade_date,source_record_id FROM read_parquet(?) WHERE code_quality='OUTSIDE_REGISTERED_IDENTITY_INTERVAL'",[str(p)]).df()
        d['field']='adj_factor';d['dataset_id']='stock_adjustment';d['quality_status']='BLOCKED_OUTSIDE_REGISTERED_IDENTITY_INTERVAL'
        d['quality_reason']='Provider factor row outside certified active security-code interval; not a traded observation or an input on its own.';d['evidence_path']=p.relative_to(ROOT).as_posix();pieces.append(d)
    special=c.execute('SELECT ts_code,trade_date,source_record_id,limit_rule_status quality_status,quality_reason FROM '+rel('stock_limits_observations')+' WHERE rule_id IS NOT NULL').df()
    special['evidence_path']='data/standardized/market/v4/stock_limit_rule_evidence.parquet'
    for field in ['up_limit','down_limit']:
        piece=special.copy();piece['field']=field;piece['dataset_id']='stock_limits';pieces.append(piece)
    c.close()
    d=pd.read_parquet(AUDIT/'source_reconciliation/factor_adjudications.parquet')
    q=d[['ts_code','trade_date','factor_record_id','classification']].rename(columns={'factor_record_id':'source_record_id','classification':'quality_reason'}).copy()
    q['field']='adj_factor';q['dataset_id']='stock_adjustment';q['evidence_path']='audit/final_data_foundation/source_reconciliation/factor_adjudications.parquet'
    q['quality_status']=np.where(q.quality_reason.str.startswith('OFFICIAL_'),'VERIFIED_SPECIAL_RETURN_BASIS',np.where(q.quality_reason.str.startswith('COMPATIBLE_'),'QUALIFIED_FACTOR_PRECISION','BLOCKED_UNRESOLVED_ACTION_BASIS'));pieces.append(q)
    d=pd.read_parquet(AUDIT/'source_reconciliation/index_quote_adjudication.parquet')
    for field in ['open','close','high','low']:
        m=d.price_resolution.eq('MATERIAL_DIFFERENCE_REQUIRES_REVIEW')&d['difference_'+field].abs().gt(.011)
        q=d.loc[m,['ts_code','trade_date','source_record_id']].copy();q['field']=field;q['dataset_id']='index_daily'
        q['quality_status']='BLOCKED_UNRESOLVED_CROSS_SOURCE_CONFLICT';q['quality_reason']='Primary retained for transparent reconstruction; formal certification blocked until third/official source resolves price difference.'
        q['evidence_path']='audit/final_data_foundation/source_reconciliation/index_quote_adjudication.parquet';pieces.append(q)
    q=pd.concat(pieces,ignore_index=True)
    master=pd.read_parquet(MARKET/'stock_master_history.parquet')[['ts_code','instrument_id']].drop_duplicates()
    assert not master.ts_code.duplicated().any()
    q['instrument_id']=q.ts_code.map(master.set_index('ts_code').instrument_id)
    q.loc[q.dataset_id.eq('index_daily'),'instrument_id']=q.loc[q.dataset_id.eq('index_daily'),'ts_code']
    assert q.instrument_id.notna().all(), 'Every stock exception must resolve to its legal security identity'
    q['quality_record_id']=[hashlib.sha256('|'.join(map(str,x)).encode()).hexdigest() for x in q[['dataset_id','source_record_id','field','quality_status']].itertuples(index=False,name=None)]
    q['data_version']=VERSION;q=q.drop_duplicates('quality_record_id').sort_values(['dataset_id','ts_code','trade_date','field','quality_status'])
    frame(MARKET/'market_data_quality.parquet',q)
    frame(AUDIT/'market_coverage/field_quality_summary.parquet',q.groupby(['dataset_id','field','quality_status']).size().reset_index(name='observations'))
    print('Market field exceptions',len(q),q.quality_status.value_counts().to_dict(),flush=True)


if __name__=='__main__':
    from .deep_market_checks import basic_arithmetic_checks
    basic_arithmetic_checks();build()
