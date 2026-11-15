"""One observation per legal security and date, with historical code intervals."""
from .common import *
from .market import rel


def build(years=None):
    c=db();master=pd.read_parquet(MARKET/'stock_master_history.parquet');c.register('history',master)
    c.execute('CREATE TEMP TABLE aliases AS SELECT DISTINCT instrument_id,ts_code FROM history')
    selected_years=list(years) if years is not None else list(range(2014,2027))
    ledger=AUDIT/'market_coverage/canonical_stock_observations.parquet'
    summary=pd.read_parquet(ledger).query('year not in @selected_years').to_dict('records') if years is not None and ledger.exists() else []
    for source in ['stock_daily','stock_adjustment','stock_daily_basic']:
        for year in selected_years:
            pred=f"d.trade_date BETWEEN '{year}0101' AND '{min(str(year)+'1231',END)}'"
            c.execute(f"""CREATE OR REPLACE TEMP TABLE candidates AS SELECT d.*,a.instrument_id,
              h.ts_code historical_code,h.identity_evidence,
              CASE WHEN h.ts_code IS NULL THEN 'OUTSIDE_REGISTERED_IDENTITY_INTERVAL'
               WHEN d.ts_code=h.ts_code THEN 'HISTORICAL_CODE_MATCH'
               ELSE 'VERIFIED_CODE_ALIAS_RECONSTRUCTION' END code_quality
              FROM {rel(source)} d JOIN aliases a USING(ts_code)
              LEFT JOIN history h ON a.instrument_id=h.instrument_id
              AND try_strptime(d.trade_date,'%Y%m%d')::DATE>=h.valid_from
              AND try_strptime(d.trade_date,'%Y%m%d')::DATE<h.valid_to WHERE {pred}""")
            numeric=['open','high','low','close','pre_close','vol','amount'] if source=='stock_daily' else ['adj_factor'] if source=='stock_adjustment' else ['close','total_share','float_share','total_mv','circ_mv']
            checks=','.join(f'max({field})-min({field}) AS spread_{field}' for field in numeric)
            overlaps=f"SELECT instrument_id,trade_date,count(*) source_rows,string_agg(ts_code,',' ORDER BY ts_code) source_codes,{checks} FROM candidates GROUP BY 1,2 HAVING count(*)>1"
            copy_query(c,overlaps,AUDIT/'source_reconciliation/code_alias_overlaps'/source/f'{year}.parquet')
            selected="""SELECT * EXCLUDE(ts_code,historical_code),ts_code source_instrument_code,
              coalesce(historical_code,ts_code) ts_code FROM candidates
              QUALIFY row_number() OVER(PARTITION BY instrument_id,trade_date
                ORDER BY CASE WHEN ts_code=historical_code THEN 0 ELSE 1 END,retrieved_at DESC,source_record_id)=1"""
            path=MARKET/(source+'_observations')/f'{year}.parquet'
            copy_query(c,selected+' ORDER BY instrument_id,trade_date',path)
            counts=c.execute('SELECT count(*),count(*) FILTER(WHERE code_quality=\'OUTSIDE_REGISTERED_IDENTITY_INTERVAL\') FROM read_parquet(?)',[str(path)]).fetchone()
            original=c.execute('SELECT count(*) FROM candidates').fetchone()[0]
            summary.append({'dataset_id':source,'year':year,'source_rows':original,'unique_security_dates':counts[0],
                            'alias_duplicates_resolved':original-counts[0],'outside_registered_identity_interval':counts[1],
                            'authoritative_path':path.relative_to(ROOT).as_posix()})
        print('identity observations',source,sum(x['alias_duplicates_resolved'] for x in summary if x['dataset_id']==source),flush=True)
    frame(AUDIT/'market_coverage/canonical_stock_observations.parquet',pd.DataFrame(summary));c.close()


if __name__=='__main__':build()
