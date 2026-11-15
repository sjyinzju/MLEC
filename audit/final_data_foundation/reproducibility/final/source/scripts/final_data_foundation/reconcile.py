"""Independent provider comparisons and full-population numerical checks."""
import numpy as np
from .common import *
from .market import rel

def index_second_source():
    entries=read(AUDIT/'source_reconciliation/tencent_requests.json');rows=[]
    for r in entries:
        if r['status']!='ok':continue
        if sha(ROOT/r['path'])!=r['sha256']:raise ValueError('Changed Tencent payload')
        obj=read(ROOT/r['path']);symbol=r['instrument_id'][-2:].lower()+r['instrument_id'][:6]
        data=obj.get('data',{}).get(symbol,{})
        for v in data.get('day',[]):
            if not str(v[0]).startswith(str(r['year'])):continue
            rows.append({'ts_code':r['instrument_id'],'trade_date':str(v[0]).replace('-',''),'tx_open':float(v[1]),'tx_close':float(v[2]),'tx_high':float(v[3]),'tx_low':float(v[4]),'tx_vol':float(v[5]),'second_source_path':r['path']})
    tx=pd.DataFrame(rows).drop_duplicates(['ts_code','trade_date'])
    frame(ROOT/'data/raw/market/second_source/v4/tencent_index_daily.parquet',tx)
    c=db();d=c.execute('SELECT ts_code,trade_date,open,close,high,low,vol,source_record_id FROM '+rel('index_daily')).df();c.close()
    joined=d.merge(tx,on=['ts_code','trade_date'],how='left',validate='one_to_one')
    for field in ['open','high','low','close','vol']:joined['difference_'+field]=joined[field]-joined['tx_'+field]
    # Tencent index prices carry 2 decimal economic precision despite 3 printed
    # digits. Tushare carries 3/4; compare against a half-cent rounding interval.
    joined['price_agree']=joined[['difference_'+f for f in ['open','high','low','close']]].abs().le(.0051).all(axis=1)
    joined['volume_agree']=np.isclose(joined.vol,joined.tx_vol,rtol=1e-7,atol=.02)
    joined['review_status']=np.select([joined.tx_close.isna(),~joined.price_agree,~joined.volume_agree],['SECOND_SOURCE_MISSING','PRICE_DIFFERENCE_REQUIRES_REVIEW','VOLUME_DIFFERENCE_REQUIRES_REVIEW'],default='CROSS_SOURCE_AGREEMENT')
    frame(AUDIT/'source_reconciliation/index_daily_second_source.parquet',joined)
    write(AUDIT/'source_reconciliation/index_summary.json',joined.groupby(['ts_code','review_status']).size().reset_index(name='rows').to_dict('records'))
    return joined.review_status.value_counts().to_dict()

def stock_numeric():
    c=db();summaries=[];fieldrows=[]
    for year in range(2014,2027):
        lower=f'{year}0101';upper=min(f'{year}1231',END)
        c.execute(f"CREATE OR REPLACE TEMP TABLE d AS SELECT * FROM {rel('stock_daily_observations')} WHERE trade_date BETWEEN '{lower}' AND '{upper}'")
        c.execute(f"CREATE OR REPLACE TEMP TABLE f AS SELECT * FROM {rel('stock_adjustment_observations')} WHERE trade_date BETWEEN '{lower}' AND '{upper}'")
        c.execute(f"CREATE OR REPLACE TEMP TABLE b AS SELECT * FROM {rel('stock_daily_basic_observations')} WHERE trade_date BETWEEN '{lower}' AND '{upper}'")
        for table,cols in [('d',['open','high','low','close','pre_close','change','pct_chg','vol','amount']),('f',['adj_factor']),('b',['close','turnover_rate','turnover_rate_f','pe','pe_ttm','pb','total_mv','circ_mv'])]:
            counts=c.execute('SELECT count(*),'+','.join(f'count(*) FILTER(WHERE {x} IS NULL)' for x in cols)+' FROM '+table).fetchone()
            for col,n in zip(cols,counts[1:]):fieldrows.append({'year':year,'dataset':{'d':'stock_daily','f':'stock_adjustment','b':'stock_daily_basic'}[table],'field':col,'rows':counts[0],'nulls':n})
        rules={
          'duplicate_quote':"SELECT ts_code,trade_date,'duplicate_quote' rule FROM d GROUP BY 1,2 HAVING count(*)>1",
          'invalid_ohlc':"SELECT ts_code,trade_date,'invalid_ohlc' rule FROM d WHERE open<=0 OR close<=0 OR low<=0 OR high<=0 OR low>least(open,close) OR high<greatest(open,close) OR low>high OR close IS NULL",
          'invalid_turnover':"SELECT ts_code,trade_date,'invalid_turnover' rule FROM d WHERE amount<0 OR vol<0 OR amount IS NULL OR vol IS NULL",
          'pct_arithmetic':"SELECT ts_code,trade_date,'pct_arithmetic' rule FROM d WHERE pre_close>0 AND abs(100*(close/pre_close-1)-pct_chg)>.015",
          'change_arithmetic':"SELECT ts_code,trade_date,'change_arithmetic' rule FROM d WHERE abs(close-pre_close-change)>.011",
          'missing_factor':"SELECT d.ts_code,d.trade_date,'missing_factor' rule FROM d LEFT JOIN f USING(ts_code,trade_date) WHERE f.adj_factor IS NULL OR f.adj_factor<=0",
          'missing_basic':"SELECT d.ts_code,d.trade_date,'missing_basic' rule FROM d LEFT JOIN b USING(ts_code,trade_date) WHERE b.ts_code IS NULL",
          'basic_close_conflict':"SELECT d.ts_code,d.trade_date,'basic_close_conflict' rule FROM d JOIN b USING(ts_code,trade_date) WHERE abs(d.close-b.close)>.011"}
        pieces=[]
        for name,sql in rules.items():
            z=c.execute(sql.replace(" rule FROM",' AS "rule" FROM')).df();pieces.append(z);summaries.append({'year':year,'rule':name,'affected_rows':len(z)})
        frame(AUDIT/'market_coverage/stock_numeric'/f'{year}.parquet',pd.concat(pieces,ignore_index=True).astype({'ts_code':'string','trade_date':'string','rule':'string'}))
        print('stock numeric',year,{x['rule']:x['affected_rows'] for x in summaries if x['year']==year},flush=True)
    frame(AUDIT/'market_coverage/stock_numeric_summary.parquet',pd.DataFrame(summaries));frame(AUDIT/'market_coverage/stock_field_completeness.parquet',pd.DataFrame(fieldrows));c.close()

if __name__=='__main__':
    print(index_second_source());stock_numeric()
