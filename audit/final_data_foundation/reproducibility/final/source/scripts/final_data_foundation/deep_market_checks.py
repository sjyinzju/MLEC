"""Population-wide arithmetic, adjustment and optional-field coverage checks."""
from .common import *
from .market import rel


def stock_adjustment_checks():
    c=db()
    master=pd.read_parquet(MARKET/'stock_master_history.parquet')[['instrument_id','ts_code']].drop_duplicates()
    c.register('aliases',master)
    # Every traded observation, including delisted securities and old codes.
    query=f"""WITH aligned AS (
      SELECT a.instrument_id,d.ts_code,d.trade_date,d.close,d.pre_close,d.pct_chg,d.source_record_id quote_record_id,
        f.adj_factor,f.source_record_id factor_record_id,
        lag(d.close) OVER w previous_traded_close,lag(f.adj_factor) OVER w previous_factor,lag(d.trade_date) OVER w previous_trade_date
      FROM {rel('stock_daily_observations')} d JOIN aliases a USING(ts_code)
      LEFT JOIN {rel('stock_adjustment_observations')} f USING(ts_code,trade_date)
      WINDOW w AS(PARTITION BY a.instrument_id ORDER BY d.trade_date,d.ts_code)),
      calculated AS (SELECT *,close*adj_factor/(previous_traded_close*previous_factor)-1 adjusted_holding_return,
        close/pre_close-1 exchange_reference_return,
        previous_traded_close*previous_factor/adj_factor factor_implied_reference_price,
        adj_factor/previous_factor factor_ratio FROM aligned)
      SELECT *,pre_close-factor_implied_reference_price reference_price_residual,
        100*(adjusted_holding_return-exchange_reference_return) return_difference_pp,
        CASE WHEN previous_trade_date IS NULL THEN 'FIRST_OBSERVATION_NO_PRIOR_QUOTE'
         WHEN previous_factor IS NULL OR adj_factor IS NULL OR adj_factor<=0 OR previous_factor<=0 THEN 'INVALID_FACTOR'
         WHEN abs(pre_close-factor_implied_reference_price)>.011 THEN 'REFERENCE_FACTOR_DIFFERENCE_REQUIRES_REVIEW'
         ELSE 'REFERENCE_FACTOR_AGREEMENT' END verification_status
      FROM calculated"""
    path=AUDIT/'market_coverage/adjusted_return_population.parquet';copy_query(c,query,path)
    discrepancies=c.execute('SELECT * FROM read_parquet(?) WHERE verification_status=?',[str(path),'REFERENCE_FACTOR_DIFFERENCE_REQUIRES_REVIEW']).df()
    div=c.execute('SELECT ts_code,ex_date,ann_date,imp_ann_date,stk_div,cash_div_tax,div_proc,source_record_id FROM '+rel('stock_dividend_events')+" WHERE div_proc='实施'").df()
    if len(discrepancies):
        discrepancies=discrepancies.merge(div.rename(columns={'ex_date':'trade_date'}),on=['ts_code','trade_date'],how='left')
    frame(AUDIT/'source_reconciliation/adjustment_discrepancies.parquet',discrepancies)
    summary=c.execute('SELECT verification_status,count(*) observations FROM read_parquet(?) GROUP BY 1',[str(path)]).df()
    frame(AUDIT/'market_coverage/adjusted_return_summary.parquet',summary)
    print('adjustment checks',summary.to_dict('records'),flush=True);c.close()


def basic_arithmetic_checks():
    c=db();rows=[]
    for year in range(2014,2027):
        pred=f"trade_date BETWEEN '{year}0101' AND '{min(str(year)+'1231',END)}'"
        query=f"""SELECT b.ts_code,b.trade_date,b.source_record_id,b.close,b.total_share,b.float_share,b.free_share,
          b.total_mv,b.circ_mv,b.turnover_rate,b.turnover_rate_f,d.vol,
          b.total_mv-b.close*b.total_share total_mv_residual,
          b.circ_mv-b.close*b.float_share circ_mv_residual,
          b.turnover_rate-d.vol/nullif(b.float_share,0) turnover_residual,
          b.turnover_rate_f-d.vol/nullif(b.free_share,0) free_turnover_residual,
          abs(b.total_mv/(b.close*nullif(b.total_share,0))-1) total_mv_relative_error,
          abs(b.circ_mv/(b.close*nullif(b.float_share,0))-1) circ_mv_relative_error,
          CASE WHEN b.ts_code LIKE '689%' THEN 'CDR_REQUIRES_DEPOSITARY_RATIO'
           ELSE 'PROVIDER_SHARE_CAP_BASIS_REQUIRES_REVIEW' END interpretation
          FROM {rel('stock_daily_basic_observations')} b LEFT JOIN {rel('stock_daily_observations')} d USING(ts_code,trade_date)
          WHERE b.{pred}"""
        c.execute('CREATE OR REPLACE TEMP TABLE arithmetic AS '+query)
        # Diagnostic flags are not automatic corrections. Different securities may
        # use different share-class bases; all original fields remain available.
        tests={'total_mv_identity':'abs(total_mv_residual)>greatest(.011,close*.00005+.00005)',
               'circ_mv_identity':'abs(circ_mv_residual)>greatest(.011,close*.00005+.00005)',
               'turnover_identity':'abs(turnover_residual)>.0001',
               'free_turnover_identity':'abs(free_turnover_residual)>.0001'}
        for name,condition in tests.items():
            count=c.execute('SELECT count(*) FROM arithmetic WHERE '+condition).fetchone()[0]
            rows.append({'year':year,'rule':name,'flagged_rows':count})
        copy_query(c,'SELECT * FROM arithmetic WHERE '+' OR '.join('('+v+')' for v in tests.values()),AUDIT/'source_reconciliation/basic_arithmetic'/f'{year}.parquet')
        print('basic arithmetic',year,{r['rule']:r['flagged_rows'] for r in rows if r['year']==year},flush=True)
    frame(AUDIT/'market_coverage/basic_arithmetic_summary.parquet',pd.DataFrame(rows));c.close()


if __name__=='__main__':basic_arithmetic_checks();stock_adjustment_checks()
