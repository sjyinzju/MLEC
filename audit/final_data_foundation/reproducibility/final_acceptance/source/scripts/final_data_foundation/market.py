"""Market standardization and exhaustive security/date coverage, without labels."""
import numpy as np
from .common import *
from .contracts import TABLES
from .collect import PUBLIC

KEYS={'trade_cal':'exchange,cal_date','stock_basic':'ts_code','index_basic':'ts_code','namechange':'ts_code,start_date,name',
      'suspend_d':'ts_code,trade_date,suspend_type,suspend_timing','index_weight':'index_code,con_code,trade_date',
      'margin':'exchange_id,trade_date','hsgt_top10':'ts_code,trade_date,market_type','dividend':'ts_code,end_date,ann_date,div_proc',
      'new_share':'ts_code','bse_mapping':'_row_hash','shibor':'date','shibor_lpr':'date','shibor_quote':'date,bank'}
NAMES={v[0]:k for k,v in TABLES.items() if v[0]!='official_adjustment_announcements'}
NAMES.update(stock_basic='stock_master_snapshot',suspend_d='stock_suspension_events')

def standardize(endpoints=None):
    c=db();ledger_path=AUDIT/'integrity/market_standardization.json'
    ledger=read(ledger_path) if ledger_path.exists() else {}
    for ep in sorted(endpoints or NAMES):
        if not (RAW/ep).exists():continue
        name=NAMES.get(ep,ep);keys=KEYS.get(ep,'ts_code,trade_date')
        fields=[r[0] for r in c.execute('DESCRIBE SELECT * FROM '+local_raw(ep)).fetchall()]
        datecol='trade_date' if 'trade_date' in fields else 'cal_date' if 'cal_date' in fields else None
        for src in sorted((RAW/ep).glob('*.parquet')):
            path=MARKET/name/src.name;key=path.relative_to(ROOT).as_posix()
            transform='api_a_share_filter_v1' if src.stem.startswith('api_') else 'external_selected_v1'
            if key in ledger and ledger[key].get('transform')==transform and ledger[key].get('input_sha256')==sha(src) and path.exists() and sha(path)==ledger[key]['sha256']:continue
            where=' WHERE '+A_SCOPE if src.stem.startswith('api_') and ep in ['daily','daily_basic','adj_factor','suspend_d','stk_limit'] else ''
            query=f'SELECT * FROM read_parquet({qs(src)}){where} QUALIFY row_number() OVER(PARTITION BY {keys} ORDER BY _ingested_at DESC,_row_hash DESC,_batch_id)=1'
            dates=f",try_strptime({datecol},'%Y%m%d')::DATE observation_date" if datecol else ''
            extra=',amount*1000.0 amount_cny,vol*100.0 volume_shares' if ep in ['index_daily','daily'] else ''
            # Actual vintage availability is retrieval. A separate opt-in reconstruction
            # time records the frozen EOD convention, never masquerades as strict PIT.
            if datecol:extra+=f",timezone('Asia/Shanghai',try_strptime({datecol},'%Y%m%d')+INTERVAL 18 HOUR) reconstructed_quote_at"
            sql=f"SELECT *,{qs(name)} dataset_id,{qs('tushare:'+ep)} source_id,{qs(ep+':')}||_row_hash source_record_id,_ingested_at retrieved_at,_ingested_at research_available_at,CAST(NULL AS TIMESTAMPTZ) release_at,_batch_id vintage_id,'latest_vintage_reconstructed' quality_status,'Provider historical reconstruction; full correction history unavailable' quality_reason,{qs(VERSION)} data_version{dates}{extra} FROM ({query}) ORDER BY {keys}"
            copy_query(c,sql,path)
            ledger[key]={'sha256':sha(path),'input_sha256':sha(src),'raw_path':src.relative_to(ROOT).as_posix(),'transform':transform,'rows':c.execute('select count(*) from read_parquet(?)',[str(path)]).fetchone()[0]}
            write(ledger_path,ledger);print('standard',name,src.stem,ledger[key]['rows'],flush=True)
    c.close()

def rel(name):return f'read_parquet({qs(MARKET/name/"*.parquet")},union_by_name=true,hive_partitioning=false)'

def identities():
    c=db();master=c.execute('SELECT * FROM '+rel('stock_master_snapshot')).df();c.close()
    changes=read(PUBLIC/'code_change_evidence.json')
    rows=[]
    for r in master.to_dict('records'):
        new=next((x for x in changes if x['new_code']==r['ts_code']),None)
        record={**r,'instrument_id':'CN-EQUITY-'+r['ts_code'],'valid_from':pd.to_datetime(r['list_date'],format='%Y%m%d'),
                'valid_to':pd.to_datetime(r['delist_date'],format='%Y%m%d') if pd.notna(r['delist_date']) else pd.Timestamp('2099-12-31'),
                'security_type':'CDR' if r['ts_code'].startswith('689') else 'A_SHARE',
                'identity_status':'PROVIDER_LISTING_HISTORY','identity_evidence':r['source_record_id']}
        if new:
            if new['review_status']!='PRIMARY_DOCUMENT_VERIFIED':raise ValueError('Code evidence has not been reviewed')
            old={**record,'ts_code':new['old_code'],'valid_to':pd.Timestamp(new['effective_date']),
                 'identity_status':'OFFICIAL_CODE_INTERVAL','identity_evidence':new['source_path']}
            rows.append(old)
            record.update(valid_from=pd.Timestamp(new['effective_date']),identity_status='OFFICIAL_CODE_INTERVAL',identity_evidence=new['source_path'])
        rows.append(record)
    history=pd.DataFrame(rows).sort_values(['instrument_id','valid_from'])
    frame(MARKET/'stock_master_history.parquet',history)
    frame(MARKET/'stock_code_changes.parquet',pd.DataFrame(changes))
    return history

def index_checks():
    c=db();prices=c.execute('SELECT * FROM '+rel('index_daily')+' ORDER BY ts_code,trade_date').df()
    basic=c.execute('SELECT * FROM '+rel('index_daily_basic')).df()
    calendar=c.execute('SELECT * FROM '+rel('trade_calendar')).df()
    identity=c.execute('SELECT * FROM '+rel('index_identity')).df();c.close()
    coverage=[];errors=[];fields=[]
    for code in INDEX_CODES:
        exchange='SSE' if code.endswith('.SH') else 'SZSE'
        days=calendar.loc[calendar.exchange.eq(exchange)&calendar.is_open.astype(int).eq(1)&calendar.cal_date.between(START,END),'cal_date']
        p=prices[prices.ts_code.eq(code)].sort_values('trade_date');b=basic[basic.ts_code.eq(code)]
        launch=identity.loc[identity.ts_code.eq(code),'list_date'].iloc[0]
        for day in days:
            coverage.append({'dataset_id':'index_daily','instrument_id':code,'trade_date':day,'period_role':'warmup' if day<'20150105' else 'frozen_research',
              'status':'MISSING' if day not in set(p.trade_date) else 'PRELAUNCH_BACKCAST' if day<launch else 'OBSERVED','index_launch_date':launch})
        for name,table in [('index_daily',p),('index_daily_basic',b)]:
            for col in TABLES[name][2].split(','):
                fields.append({'dataset_id':name,'instrument_id':code,'field':col,'rows':len(table),'nulls':int(table[col].isna().sum()) if col in table else len(table),'status':'FIELD_PRESENT' if col in table else 'FIELD_ABSENT'})
        checks={'duplicate_key':p.duplicated(['ts_code','trade_date'],keep=False),
                'invalid_price':p[['open','high','low','close','pre_close']].le(0).any(axis=1)|p[['open','high','low','close','pre_close']].isna().any(axis=1),
                'ohlc_constraint':p.low.gt(p[['open','close']].min(axis=1))|p.high.lt(p[['open','close']].max(axis=1))|p.low.gt(p.high),
                'negative_turnover':p.vol.lt(0)|p.amount.lt(0),
                'change_inconsistent':(p.close-p.pre_close-p.change).abs().gt(.002),
                'pct_inconsistent':((p.close/p.pre_close-1)*100-p.pct_chg).abs().gt(.002),
                'preclose_differs_previous':(p.pre_close-p.close.shift()).abs().gt(.002),
                'extreme_return_review':p.pct_chg.abs().gt(15)}
        for rule,mask in checks.items():
            for row in p.loc[mask,['ts_code','trade_date','source_record_id','close','pre_close','pct_chg']].to_dict('records'):errors.append({**row,'rule':rule})
    frame(AUDIT/'market_coverage/index_daily_grid.parquet',pd.DataFrame(coverage))
    frame(AUDIT/'market_coverage/index_fields.parquet',pd.DataFrame(fields))
    frame(AUDIT/'market_coverage/index_value_checks.parquet',pd.DataFrame(errors,columns=['ts_code','trade_date','source_record_id','close','pre_close','pct_chg','rule']))
    return pd.DataFrame(coverage).groupby(['instrument_id','status']).size().to_dict()

def stock_gaps():
    history=pd.read_parquet(MARKET/'stock_master_history.parquet');c=db();c.register('history_input',history)
    c.execute('CREATE TEMP TABLE master AS SELECT * FROM history_input')
    # Keep listing span and code-effective span separate. Daily source aliasing is
    # explicitly reconciled to the same legal entity; original codes remain stored.
    c.execute('CREATE TEMP TABLE aliases AS SELECT DISTINCT instrument_id,ts_code FROM master')
    c.execute('CREATE TEMP TABLE calendar AS SELECT exchange,cal_date trade_date FROM '+rel('trade_calendar')+f" WHERE is_open=1 AND cal_date BETWEEN '{START}' AND '{END}'")
    for year in range(2014,2027):
        pred=f"trade_date BETWEEN '{year}0101' AND '{min(str(year)+'1231',END)}'"
        c.execute('CREATE OR REPLACE TEMP TABLE d AS SELECT d.*,a.instrument_id FROM '+rel('stock_daily')+' d LEFT JOIN aliases a USING(ts_code) WHERE '+pred)
        c.execute('CREATE OR REPLACE TEMP TABLE f AS SELECT f.*,a.instrument_id FROM '+rel('stock_adjustment')+' f LEFT JOIN aliases a USING(ts_code) WHERE '+pred)
        c.execute('CREATE OR REPLACE TEMP TABLE s AS SELECT s.*,a.instrument_id FROM '+rel('stock_suspension_events')+' s LEFT JOIN aliases a USING(ts_code) WHERE '+pred)
        sql=f"""WITH expected AS (
          SELECT m.instrument_id,m.ts_code,m.list_date,m.delist_date,m.identity_status,m.identity_evidence,c.trade_date
          FROM master m JOIN calendar c ON c.exchange=m.exchange
            AND try_strptime(c.trade_date,'%Y%m%d')::DATE>=m.valid_from
            AND try_strptime(c.trade_date,'%Y%m%d')::DATE<m.valid_to WHERE {pred}),
          observed AS (SELECT instrument_id,trade_date,count(*) quote_count,array_to_string(list_sort(list_distinct(list(ts_code))),',') source_codes,
            array_to_string(list_sort(list_distinct(list(source_record_id))),',') quote_record_ids FROM d GROUP BY 1,2),
          factors AS (SELECT instrument_id,trade_date,count(*) factors FROM f GROUP BY 1,2),
          suspended AS (SELECT instrument_id,trade_date,bool_or(suspend_type='S' AND suspend_timing IS NULL) full_day_s,
            bool_or(suspend_type='S') any_s,array_to_string(list_sort(list_distinct(list(source_record_id))),',') suspension_record_ids FROM s GROUP BY 1,2)
          SELECT e.*,o.source_codes,o.quote_record_ids,s.suspension_record_ids,coalesce(f.factors,0)>0 factor_present,
            CASE WHEN o.quote_count>0 THEN 'OBSERVED' WHEN s.full_day_s THEN 'SUSPENDED_SOURCE_RECORDED'
            WHEN s.any_s THEN 'MISSING_WITH_INTRADAY_SUSPENSION' ELSE 'UNEXPLAINED_MISSING' END status
          FROM expected e LEFT JOIN observed o USING(instrument_id,trade_date)
          LEFT JOIN factors f USING(instrument_id,trade_date) LEFT JOIN suspended s USING(instrument_id,trade_date)
          ORDER BY instrument_id,trade_date"""
        path=MARKET/'stock_trading_status'/f'{year}.parquet';copy_query(c,sql,path)
        copy_query(c,'SELECT * FROM read_parquet('+qs(path)+") WHERE status!='OBSERVED'",AUDIT/'missing_records/stocks'/f'{year}.parquet')
        unknown=c.execute('SELECT ts_code,count(*) n,min(trade_date) period_start,max(trade_date) period_end FROM d WHERE instrument_id IS NULL GROUP BY 1').df()
        frame(AUDIT/'market_coverage'/f'unknown_identity_{year}.parquet',unknown)
        print('stock grid',year,c.execute('select status,count(*) from read_parquet(?) group by 1',[str(path)]).fetchall(),flush=True)
    summary=c.execute('SELECT ts_code,status,count(*) observations,min(trade_date) period_start,max(trade_date) period_end FROM '+rel('stock_trading_status')+" WHERE status!='OBSERVED' GROUP BY 1,2 ORDER BY observations DESC").df()
    frame(AUDIT/'missing_records/stock_gap_summary.parquet',summary);c.close()
    return summary

if __name__=='__main__':
    standardize();identities();print(index_checks());stock_gaps()
