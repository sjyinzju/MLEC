"""Fill absent SZSE stock-category dates from the official daily report.

Keep only standardized observations and compact field definitions. The current
publisher table no longer contains historical volume/share columns; never
manufacture those from monetary totals.
"""
from concurrent.futures import ThreadPoolExecutor
from html import unescape
import requests
from .common import *

URL='http://www.szse.cn/api/report/ShowReport/data'
CATEGORIES={'股票','主板A股','主板B股','中小板','创业板A股'}


def official_day(day):
    session=requests.Session();session.trust_env=False
    date=pd.Timestamp(day).strftime('%Y-%m-%d')
    response=session.get(URL,params={'SHOWTYPE':'JSON','CATALOGID':'1803_sczm',
        'TABKEY':'tab1','txtQueryDate':date},timeout=20)
    response.raise_for_status();obj=response.json()[0]
    assert obj['metadata']['subname']==date
    cols=obj['metadata']['cols']
    assert all('亿元' in cols[k] for k in ['cjje','sjzz','ltsz'])
    rows=[];capture=pd.Timestamp.now(tz='Asia/Shanghai')
    for item in obj['data']:
        category=unescape(item['lbmc']).strip()
        if category=='创业板':category='创业板A股'
        if category not in CATEGORIES:continue
        row=dict(trade_date=day,ts_code=category,count=float(item['zqsl'].replace(',','')),
            source_url=response.url,source_id='szse:official_daily_statistics',
            source_record_id='szse:daily:'+day+':'+category,
            retrieved_at=capture,research_available_at=capture,
            reconstructed_quote_at=pd.Timestamp(date+' 18:00',tz='Asia/Shanghai'),
            observation_date=pd.Timestamp(date).date(),release_at=pd.NaT,
            dataset_id='exchange_activity_sz',vintage_id='historical_official_daily_read',
            quality_status='historical_reconstructed',data_version='practical-research-data-v5',
            quality_reason='Official daily table in 100 million CNY, normalized to CNY; displayed at 0.01 hundred-million resolution. Publication time assumed 18:00 for historical reconstruction; actual capture kept. Volume/share quantities absent from this table remain NULL.',
            monetary_reported_quantum_cny=1_000_000.)
        for key,target in [('cjje','amount'),('sjzz','total_mv'),('ltsz','float_mv')]:
            row[target]=float(item[key].replace(',',''))*1e8
        rows.append(row)
    return rows


def build():
    c=db();old=c.execute('SELECT * FROM read_parquet(?,union_by_name=true)',[str(MARKET/'exchange_activity_sz/*.parquet')]).df()
    old['ts_code']=old.ts_code.replace({'创业板':'创业板A股'})
    assert not old.duplicated(['ts_code','trade_date']).any()
    days=c.execute("SELECT DISTINCT cal_date FROM read_parquet(?) WHERE exchange='SZSE' AND is_open='1' AND cal_date BETWEEN ? AND ? ORDER BY cal_date",
        [str(MARKET/'trade_calendar/*.parquet'),START,END]).df().cal_date.tolist()
    assert len(days)>3000
    expected={(day,cat) for day in days for cat in CATEGORIES if cat!='中小板' or day<'20210406'}
    missing=expected-set(old[['trade_date','ts_code']].itertuples(index=False,name=None))
    dates=sorted({d for d,k in missing});additions=[];empty=0;failed=[]
    # Verify the currency normalization against the official labeled table.
    proof_path=ROOT/'data/metadata/szse_currency_basis.parquet'
    proofs=pd.read_parquet(proof_path).to_dict('records') if proof_path.exists() else []
    for day in ([] if proofs else ['20150331','20200320','20210901','20260922']):
        for row in official_day(day):
            match=old[old.trade_date.eq(day)&old.ts_code.eq(row['ts_code'])]
            if len(match)!=1:continue
            for field in ['amount','total_mv','float_mv']:
                value=float(match.iloc[0][field]);diff=abs(value-row[field])
                assert diff<=1_000_001,(day,row['ts_code'],field,diff)
                proofs.append(dict(trade_date=day,ts_code=row['ts_code'],field=field,
                    provider_value=value,official_value=row[field],official_unit='100000000 CNY',
                    standardized_unit='CNY',source_url=row['source_url'],comparison_tolerance_cny=1_000_001))
    assert len(proofs)>=45
    frame(proof_path,pd.DataFrame(proofs))
    def bounded_day(day):
        for attempt in range(2):
            try:return day,official_day(day),None
            except requests.RequestException as exc:
                if attempt: return day,[],type(exc).__name__
                time.sleep(1)
    def save():
        new=pd.concat([old,pd.DataFrame(additions)],ignore_index=True)
        assert not new.duplicated(['ts_code','trade_date']).any()
        new['observation_date']=pd.to_datetime(new.observation_date).dt.date
        # Fill original timezone columns only with timestamps/nulls, not strings.
        for col in old.columns:
            if isinstance(old[col].dtype,pd.DatetimeTZDtype):new[col]=pd.to_datetime(new[col],utc=True).dt.tz_convert(old[col].dtype.tz)
        for year,g in new.groupby(new.trade_date.str[:4]):
            frame(MARKET/'exchange_activity_sz'/(year+'.parquet'),g.sort_values(['ts_code','trade_date']))
    for start in range(0,len(dates),20):
        batch=dates[start:start+20];errors=0
        with ThreadPoolExecutor(2) as pool:
            for day,rows,error in pool.map(bounded_day,batch):
                if error:failed.append(day);errors+=1
                additions.extend(r for r in rows if (r['trade_date'],r['ts_code']) in missing)
                empty+=not bool(rows)
        if additions:save()
        print('SZSE_DATES',start+len(batch),'/',len(dates),'new rows',len(additions),'batch errors',errors,flush=True)
        if errors==len(batch):break
        time.sleep(1)
    if not dates:save()
    write(ROOT/'data/metadata/szse_source_scope.json',{'source':URL,'added_rows':len(additions),
        'queried_missing_dates':len(dates),'empty_dates':empty,'unreturned_dates':failed,'money_unit':'CNY',
        'money_definition':'Official category table headers in 100 million CNY; existing values compared within display resolution across four dates and board regimes.',
        'categories':sorted(CATEGORIES),'stock_total_includes_B_shares':True,
        'category_aliases':{'创业板':'创业板A股'},
        'no_volume_or_share_imputation':True,'raw_responses_retained':False})
    c.close();print('SZSE_ADDED',len(additions),flush=True)


def shanghai_warmup():
    from .provider import client
    path=MARKET/'exchange_activity_sh/2014.parquet'
    if path.exists() and not pd.read_parquet(path).empty:return
    adapter,catalog=client();adapter.settings.max_attempts=1;adapter.settings.timeout_seconds=20
    response=adapter.fetch(catalog['daily_info'],{'start_date':'20140101','end_date':'20141231','exchange':'SH'})
    d=pd.DataFrame(response.rows,columns=response.fields)
    assert 0<len(d)<4000 and not d.duplicated(['ts_code','trade_date']).any()
    assert d.trade_date.between('20140101','20141231').all() and d.exchange.eq('SH').all()
    c=db();days=c.execute("SELECT cal_date FROM read_parquet(?) WHERE exchange='SSE' AND is_open='1' AND cal_date BETWEEN '20140101' AND '20141231'",
        [str(MARKET/'trade_calendar/*.parquet')]).df().cal_date
    assert set(d.trade_date)==set(days) and len(days)==245
    digest=hashlib.sha256(d.to_json(orient='split').encode()).hexdigest()
    d['source_record_id']='tushare:daily_info:'+digest+':'+d.ts_code+':'+d.trade_date
    d['source_id']='tushare:daily_info';d['dataset_id']='exchange_activity_sh'
    d['retrieved_at']=response.fetched_at;d['research_available_at']=response.fetched_at
    d['observation_date']=pd.to_datetime(d.trade_date)
    d['reconstructed_quote_at']=d.observation_date.dt.tz_localize('Asia/Shanghai')+pd.Timedelta(hours=18)
    d['quality_status']='historical_reconstructed';d['vintage_id']=digest
    d['quality_reason']='Historical provider daily exchange statistics; documented native units retained. Historical 18:00 quote clock is assumed, actual capture retained; no original-vintage PIT claim.'
    d['data_version']='practical-research-data-v5'
    c.execute('CREATE TEMP TABLE standard AS SELECT * FROM read_parquet(?) WHERE false',[str(MARKET/'exchange_activity_sh/2015.parquet')])
    c.register('append_rows',d);c.execute('INSERT INTO standard BY NAME SELECT * FROM append_rows')
    copy_query(c,'SELECT * FROM standard ORDER BY ts_code,trade_date',path)
    write(ROOT/'data/metadata/sse_warmup_source.json',{'source_url':'https://tushare.pro/document/2?doc_id=215',
        'provider_endpoint':'daily_info','period':['20140102','20141231'],'dates':245,'rows':len(d),
        'categories':sorted(d.ts_code.unique()),'raw_response_retained':False,
        'units':'Original documented daily_info units; no magnitude-based rescaling'})
    c.close();print('SSE_WARMUP_ADDED',len(d),'rows, 245 dates',flush=True)


def repair_zero_stock_totals():
    """Replace demonstrably empty stock-category placeholders with official data."""
    c=db();d=c.execute('SELECT * FROM read_parquet(?,union_by_name=true)',[str(MARKET/'exchange_activity_sz/*.parquet')]).df()
    bad=d[d.ts_code.isin(CATEGORIES)&d.total_mv.le(0)]
    repairs=[]
    for day in sorted(bad.trade_date.unique()):
        fresh={r['ts_code']:r for r in official_day(day)}
        for idx,row in bad[bad.trade_date.eq(day)].iterrows():
            new=fresh.get(row.ts_code)
            if new is None or new['total_mv']<=0:continue
            repairs.append(dict(trade_date=day,ts_code=row.ts_code,
                replaced_source_record_id=row.source_record_id,
                replacement_source_record_id=new['source_record_id'],
                reason='Provider stock-category capitalization/count/turnover were zero; official historical report has positive values.',
                source_url=new['source_url']))
            for key,value in new.items():d.at[idx,key]=pd.Timestamp(value) if key=='observation_date' else value
    if repairs:
        d['observation_date']=pd.to_datetime(d.observation_date).dt.date
        for year in sorted({r['trade_date'][:4] for r in repairs}):
            frame(MARKET/'exchange_activity_sz'/(year+'.parquet'),d[d.trade_date.str.startswith(year)])
        frame(ROOT/'data/metadata/szse_zero_repairs.parquet',pd.DataFrame(repairs))
    c.close();print('SZSE_ZERO_ROWS_REPAIRED',len(repairs),flush=True)


if __name__=='__main__':build()
