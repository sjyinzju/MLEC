"""Secondary market sources: exhaustive date/field diagnostics without fake universes."""
from .common import *
from .market import rel


def build():
    c=db();summary=[]
    c.execute('CREATE TEMP TABLE aliases AS SELECT DISTINCT ts_code,instrument_id FROM read_parquet(?)',[str(MARKET/'stock_master_history.parquet')])
    for name in ['stock_limits','stock_moneyflow']:
        for year in range(2014,2027):
            lo,hi=f'{year}0101',min(f'{year}1231',END)
            # Alias reconciliation is diagnostic only and never rewrites raw prices.
            source='stock_limits_observations' if name=='stock_limits' else name
            c.execute('CREATE OR REPLACE TEMP TABLE candidate AS SELECT s.*,a.instrument_id FROM '+rel(source)+
              ' s JOIN aliases a USING(ts_code) WHERE trade_date BETWEEN ? AND ? QUALIFY row_number() OVER(PARTITION BY instrument_id,trade_date ORDER BY retrieved_at DESC,source_record_id)=1',[lo,hi])
            if name=='stock_limits':
                condition="CASE WHEN s.rule_id IS NOT NULL AND s.limit_rule_status IN ('STRUCTURAL_NO_DAILY_PRICE_LIMIT','SPECIAL_IPO_AUCTION_REGIME') THEN 'VERIFIED_SPECIAL_RULE_NOT_ORDINARY_LIMIT' WHEN s.source_record_id IS NULL THEN 'MISSING_SOURCE_ROW' WHEN s.up_limit IS NULL OR s.down_limit IS NULL THEN 'MISSING_LIMIT_VALUE_REQUIRES_RULE_EVIDENCE' WHEN s.up_limit<=0 OR s.down_limit<=0 OR s.up_limit<s.down_limit THEN 'INVALID_LIMIT_BOUNDS' WHEN d.high>s.up_limit+.011 OR d.low<s.down_limit-.011 THEN 'QUOTE_OUTSIDE_REPORTED_LIMIT_REQUIRES_EVENT_REVIEW' ELSE 'BOUNDS_AGREE_NOT_FULL_RULE_CERTIFICATION' END"
            else:condition="CASE WHEN s.source_record_id IS NULL THEN 'MISSING_SOURCE_ROW' WHEN s.net_mf_amount IS NULL OR s.net_mf_vol IS NULL THEN 'MISSING_REQUIRED_VALUE' ELSE 'SOURCE_PRESENT_CLASSIFICATION_NOT_INDEPENDENTLY_VERIFIED' END"
            query='SELECT d.instrument_id,d.ts_code,d.trade_date,d.source_record_id quote_record_id,s.source_record_id supplemental_record_id,'+condition+' status FROM '+rel('stock_daily_observations')+' d LEFT JOIN candidate s USING(instrument_id,trade_date) WHERE d.trade_date BETWEEN '+qs(lo)+' AND '+qs(hi)
            c.execute('CREATE OR REPLACE TEMP TABLE checked AS '+query)
            counts=c.execute('SELECT status,count(*) observations FROM checked GROUP BY status').df()
            for r in counts.to_dict('records'):summary.append({'dataset_id':name,'year':year,**r})
            copy_query(c,"SELECT * FROM checked WHERE status NOT IN ('BOUNDS_AGREE_NOT_FULL_RULE_CERTIFICATION','SOURCE_PRESENT_CLASSIFICATION_NOT_INDEPENDENTLY_VERIFIED','VERIFIED_SPECIAL_RULE_NOT_ORDINARY_LIMIT') ORDER BY instrument_id,trade_date",AUDIT/'missing_records'/name/f'{year}.parquet')
        print('Secondary source grid',name,flush=True)
    calendars=c.execute('SELECT exchange,cal_date FROM '+rel('trade_calendar')+' WHERE is_open=1 AND cal_date BETWEEN ? AND ?',[START,END]).df()
    rows=[]
    for name,key in [('margin_market','exchange_id'),('exchange_activity_sh','ts_code'),('exchange_activity_sz','ts_code'),('margin_security','ts_code'),('stock_connect_top10','market_type')]:
        d=c.execute('SELECT trade_date,count(*) observations,count(DISTINCT "'+key+'") categories FROM '+rel(name)+' GROUP BY trade_date ORDER BY trade_date').df()
        expected=sorted(set(calendars.cal_date));dates=set(d.trade_date)
        for day in expected:
            rows.append({'dataset_id':name,'trade_date':day,'status':'OBSERVED' if day in dates else 'NO_SOURCE_ROW_REQUIRES_SCOPE_REVIEW',
              'expected_security_scope':'Not inferred from current/ever-present constituents; historical margin eligibility/top10 is a separate unpublished or incomplete universe.' if name in ['margin_security','stock_connect_top10'] else 'Exchange-level/category-specific; full category definitions and changes require source confirmation.'})
        frame(AUDIT/'market_coverage'/(name+'_date_counts.parquet'),d)
    margin=c.execute('SELECT *,abs(rzye+rqye-rzrqye) balance_residual FROM '+rel('margin_market')+" WHERE rzye<0 OR rqye<0 OR rzrqye<0 OR abs(rzye+rqye-rzrqye)>.011").df()
    frame(AUDIT/'source_reconciliation/margin_balance_exceptions.parquet',margin)
    frame(AUDIT/'market_coverage/secondary_source_calendar_grid.parquet',pd.DataFrame(rows))
    frame(AUDIT/'market_coverage/secondary_stock_source_summary.parquet',pd.DataFrame(summary));c.close()
    write(AUDIT/'market_coverage/secondary_source_limits.json',{'status':'QUALIFIED_NOT_FULL_RULE_CERTIFICATION',
      'price_limits':'Every traded security/date checked. Seventy special-rule dates are primary-certified individually; ordinary limits are NULL with original provider values retained. All remaining ST/board/IPO rule histories still require independent certification; no blanket exemption.',
      'moneyflow':'Provider order-size classification; full observed-share/date coverage checked, economic meaning not equivalent to true investor fund flow.',
      'margin_security':'Full field/null/date statistics, but historical margin-eligible security master unavailable; do not impose all-stock or current eligibility universe.',
      'margin_balance_exception_rows':len(margin)})


if __name__=='__main__':build()
