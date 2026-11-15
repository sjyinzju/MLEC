"""Research-dependent contracts, frozen before any modelling."""
from .common import *
from .macro_contract import specifications

# Required fields mean semantically required; conditional null rules are explicit.
TABLES={
 'index_daily':('index_daily','ts_code,trade_date','open,high,low,close,pre_close,change,pct_chg,vol,amount','P0','trend,volatility,downside,activity'),
 'index_daily_basic':('index_dailybasic','ts_code,trade_date','total_mv,float_mv,turnover_rate,turnover_rate_f,pe,pe_ttm,pb','P0','valuation,activity'),
 'stock_daily':('daily','ts_code,trade_date','open,high,low,close,pre_close,change,pct_chg,vol,amount','P0','breadth,correlation,liquidity'),
 'stock_daily_basic':('daily_basic','ts_code,trade_date','close,turnover_rate,turnover_rate_f,total_mv,circ_mv,pe,pe_ttm,pb','P1','valuation,turnover,market_structure'),
 'stock_adjustment':('adj_factor','ts_code,trade_date','adj_factor','P0','adjusted_returns,correlation,Amihud'),
 'stock_master_history':('stock_basic','instrument_id,valid_from','ts_code,list_date,delist_date,exchange,security_type','P0','historical_universe,delisted_retention,code_history'),
 'stock_name_history':('namechange','ts_code,start_date,name','end_date,ann_date,change_reason','P1','identity,risk_warning_history'),
 'stock_trading_status':('suspend_d','instrument_id,trade_date','ts_code,status,identity_evidence,quote_record_ids,suspension_record_ids','P0','missing_vs_suspension,valid_returns'),
 'index_constituents_history':('official_adjustment_announcements','index_code,con_code,valid_from','valid_to,research_available_at,source_path,quality_status','P1','index_specific_breadth_and_correlation'),
 'index_weights_history':('index_weight','index_code,con_code,trade_date','weight','P1','snapshot_weights; not daily effective membership'),
 'trade_calendar':('trade_cal','exchange,cal_date','is_open,pretrade_date','P0','all_daily_expected_grids'),
 'index_identity':('index_basic','ts_code','list_date,base_date,base_point,publisher','P0','publication_vs_backcast'),
 'stock_limits':('stk_limit','ts_code,trade_date','up_limit,down_limit,limit_rule_status,rule_evidence_path','P1','trading_pressure'),
 'margin_market':('margin','exchange_id,trade_date','rzye,rqye,rzrqye,rzmre,rzche','P2','market_leverage_extension'),
 'margin_security':('margin_detail','ts_code,trade_date','rzye,rqye,rzrqye','P2','cross_sectional_leverage_extension'),
 'stock_moneyflow':('moneyflow','ts_code,trade_date','net_mf_amount,net_mf_vol','P2','provider_classified_order_flow_extension'),
 'exchange_activity_sh':('daily_info','ts_code,trade_date','amount,vol,total_mv,float_mv,tr','P1','independent_activity_reconciliation'),
 'exchange_activity_sz':('sz_daily_info','ts_code,trade_date','amount,vol,total_mv,float_mv','P1','independent_activity_reconciliation'),
 'stock_connect_top10':('hsgt_top10','ts_code,trade_date,market_type','amount,buy,sell,net_amount,rank','P2','top10_only_not_market_total_flow'),
 'stock_dividend_events':('dividend','ts_code,end_date,ann_date,div_proc','ex_date,cash_div_tax,stk_div','P1','independent_adjustment_factor_checks'),
}
DOC_IDS={'index_daily':95,'index_dailybasic':128,'daily':27,'daily_basic':32,'adj_factor':28,'stock_basic':25,'namechange':100,'suspend_d':214,'trade_cal':26,'index_weight':96,'index_basic':94,'stk_limit':183,'margin':58,'margin_detail':59,'moneyflow':170,'daily_info':215,'sz_daily_info':268,'hsgt_top10':48,'dividend':103}

def build():
    obj=read(AUDIT/'integrity/external_manifest.json');rows=[]
    for dataset_id,(ep,keys,required,priority,deps) in TABLES.items():
        available=[x['field'] for x in obj['schemas'].get(ep,[]) if not x['field'].startswith('_')]
        fields=list(dict.fromkeys(keys.split(',')+required.split(',')))
        rows.append({'domain':'M','dataset_id':dataset_id,'source_dataset':ep,'required_fields':fields,'optional_fields':[x for x in available if x not in fields],
          'source_definition':'https://tushare.pro/document/2?doc_id='+str(DOC_IDS[ep]) if ep in DOC_IDS else 'Official index-provider adjustment announcements with both publication and effectiveness dates',
          # Dividend proposals can lack ann_date; source identity remains unique.
          'primary_key':['source_record_id'] if dataset_id=='stock_dividend_events' else keys.split(','),'actual_data_start':None,'required_start':'2014-01-01','required_end':'2026-09-22',
          'research_start':'2015-01-01','warmup_policy':'2014 and earlier qualified history; market_state is the sole research authority',
          'expected_frequency':'event' if ep in ['stock_basic','namechange','dividend','official_adjustment_announcements'] else 'snapshot' if ep in ['index_weight','index_basic'] else 'calendar_day' if ep=='trade_cal' else 'trading_day',
          'expected_observations':'all exchange-open dates within independently evidenced security/code validity; event history checked for intervals, not fabricated daily observations',
          'market_scope':'SH/SZ A shares including delisted and code changes; CDR classified separately',
          'security_universe':INDEX_CODES if dataset_id.startswith('index_') else 'All historical SH/SZ listed common shares, without current-status filtering',
          'historical_availability':'Published historical observation is distinct from capture. Unverified revisions use retrieval date. Reconstructed quote view is conditional, not strict PIT.',
          'revision_policy':'Retain source metadata and explicit conflict records; research views rebuilt under the current protocol',
          'allowed_missing_rules':'Pre-listing/post-delisting/nontrading day only with evidence; suspension only explicit source. Loss-making PE may be undefined; missing PB/turnover not automatically waived. No zero-fill.',
          'downstream_dependencies':deps.split(','),'validation_rules':['primary_key','field_nulls','expected_grid','value_semantics','source_reconciliation','historical_availability','lineage'],
          'priority':priority,'required':priority!='P2','quality_status':'UNASSESSED','contract_version':VERSION})
    write(ROOT/'config/data/market_requirements.json',{'version':VERSION,'datasets':rows,'basis':'Research design v1.0 plus final data-engineering task; P2 are declared optional extension analyses, not required by frozen labels or five dimensions'})
    macros=[]
    for s in specifications():
        macros.append({**s,'domain':'Z','dataset_id':'macro_facts','source_dataset':s['source_priority'],'primary_key':['source_record_id'],
          'required_fields':['series_id','period_start','period_end','value','unit','currency','measure_type','release_at','research_available_at','retrieved_at','vintage_id','quality_status','source_record_id'],
          'optional_fields':['revision_status','reported_quantum'],'actual_data_start':None,'source_definition':s['source_definition_url'],
          'expected_frequency':s['frequency'],'expected_observations':'Explicit period-by-period grid; do not count unavailable regimes as missing observations',
          'market_scope':'China macroeconomic releases','security_universe':'not applicable',
          'historical_availability':'Evidence-supported announcement, conservative dated reproduction or retrieval-only unknown vintage',
          'revision_policy':'Every source vintage retained; no cross-scope splicing','allowed_missing_rules':s['structural_rule'],
          'downstream_dependencies':['macro_weekly',s['series_group']],
          'validation_rules':['value_vs_source','period_and_measure','release_and_vintage','scope','completeness','no_future_leakage'],'quality_status':'UNASSESSED','contract_version':VERSION})
    write(ROOT/'config/data/macro_requirements.json',{'version':VERSION,'variables':macros})
    combined=pd.DataFrame(rows+macros)
    for col in combined:
        if combined[col].map(lambda x:isinstance(x,(list,dict))).any():combined[col]=combined[col].map(lambda x:json.dumps(x,ensure_ascii=False) if isinstance(x,(list,dict)) else x)
    frame(ROOT/'data/metadata/research_data_requirements.parquet',combined)

if __name__=='__main__':build()
