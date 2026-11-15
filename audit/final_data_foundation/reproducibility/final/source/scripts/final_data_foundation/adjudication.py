"""Evidence-bound missing-quote adjudication. No synthetic quotes or returns."""
import re
from .common import *
from .collect import PUBLIC
from .market import rel

DATE=r'(20\d{2}年\d{1,2}月\d{1,2}日)'
START_PATTERNS=[r'暂停上市起始日(?:期)?[:：]?'+DATE,
 r'(?:公司|本公司)?股票(?:将|已)?(?:自|于)'+DATE+r'(?:起)?暂停上市',
 r'(?:公司|本公司)?(?:A股)?股票(?:将|已)?(?:自|于)'+DATE+r'.{0,16}?(?:开市起|起)?停牌',
 r'公司股票于'+DATE+r'起被深圳证券交易所（以下简称“深交所”）决定暂停上市',
 r'股票（证券简称：普冉股份，证券代码：688766）自'+DATE+r'（星期三）开市起开始停牌',
 DATE+r'股票被深交所正式通知暂停上市']
END_PATTERNS=[r'(?:公司|本公司)?(?:A股)?股票(?:将|已|获准)?(?:自|于)'+DATE+r'(?:起)?(?:恢复上市|进入退市整理期|复牌)',
 r'公司股票将于'+DATE+r'在上海证券交易所恢复(?:上市|交易)',
 r'自'+DATE+r'起，公司股票交易进入退市整理期',
 r'公司股票进入退市整理期的起始日[:：]'+DATE,
 r'摘牌日期[:：]'+DATE,
 r'本公司股票將於'+DATE+r'進入退市整理期',
 r'（即'+DATE+r'）起，公司股票交易进入退市整理期',
 r'公司股票（证券简称：普冉股份，证券代码：688766）将于'+DATE+r'（星期二）开市起复牌',
 r'上海证券交易所已于'+DATE+r'对上海普天邮通科技股份有限公司（以下简称“上海普天”）股票予以摘牌',
 r'恢复上市(?:的)?(?:首个交易日|日)(?:为|是|[:：])'+DATE,
 r'进入退市整理期(?:交易)?的起始日为'+DATE]

def proposals():
    c=db()
    original=f'read_parquet({qs(AUDIT/"missing_records/stocks/*.parquet")},union_by_name=true)'
    missing=c.execute('SELECT * FROM '+original+" WHERE status IN ('UNEXPLAINED_MISSING','MISSING_WITH_INTRADAY_SUSPENSION') ORDER BY ts_code,trade_date").df()
    cal=c.execute('SELECT exchange,cal_date FROM '+rel('trade_calendar')+" WHERE is_open=1 ORDER BY exchange,cal_date").df();c.close()
    ordinals={ex:{d:i for i,d in enumerate(g.cal_date)} for ex,g in cal.groupby('exchange')}
    documents=read(PUBLIC/'issuer_cninfo_documents.json');out=[]
    for code,g in missing.groupby('ts_code'):
        exchange='SSE' if code.endswith('SH') else 'SZSE';lookup=ordinals[exchange]
        g=g.copy();g['ordinal']=g.trade_date.map(lookup);g['interval']=(g.ordinal.diff().ne(1)).cumsum()
        starts=[];ends=[]
        for d in documents:
            if d['instrument_id']!=code or d['status'] not in ['PRIMARY_REQUIRES_REVIEW','PRIMARY_DOCUMENT_VERIFIED'] or '已取消' in d['announcementTitle']:continue
            text=re.sub(r'\s+','',d['content'])
            for patterns,container in [(START_PATTERNS,starts),(END_PATTERNS,ends)]:
                for pattern in patterns:
                    for m in re.finditer(pattern,text):
                        date=pd.to_datetime(m[1],format='%Y年%m月%d日').strftime('%Y%m%d')
                        container.append({'date':date,'excerpt':m[0],'evidence_path':d['evidence_path'],'sha256':d['sha256'],
                                          'announcement_id':d['announcementId'],'release_date':d['release_date'],'source_url':d['url']})
        for _,chunk in g.groupby('interval'):
            first,last=chunk.trade_date.min(),chunk.trade_date.max();nextday=next((d for d,o in lookup.items() if o==lookup[last]+1),None)
            a=sorted([x for x in starts if x['date']<=first],key=lambda x:(-int(x['date']),x['release_date']))
            b=sorted([x for x in ends if x['date']>=nextday],key=lambda x:(x['date'],x['release_date']))
            if code=='688005.SH' and first==last=='20260116':
                # Reviewed explicit one-trading-day notice; not an inferred duration.
                doc=next(d for d in documents if str(d['announcementId'])=='1224936821')
                literal='公司股票于2026年1月16日将继续停牌1日'
                assert literal in re.sub(r'\s+','',doc['content'])
                b=[{**a[0],'date':nextday,'excerpt':literal,'derivation':'one explicit trading day; next exchange open date'}]
            out.append({'instrument_code':code,'gap_start':first,'gap_end':last,'missing_observations':len(chunk),
                        'start_evidence':a[0] if a else None,'end_evidence':b[0] if b else None,
                        'review_status':'PENDING_REVIEW'})
    write(AUDIT/'issue_closure/stock_interval_proposals.json',out)
    for x in out:
        print(x['instrument_code'],x['gap_start'],x['gap_end'],x['missing_observations'],
              '| START',x['start_evidence']['excerpt'] if x['start_evidence'] else 'MISSING',
              '| END',x['end_evidence']['excerpt'] if x['end_evidence'] else 'MISSING',flush=True)
    return out

def certify_and_apply():
    """Apply reviewed interval assertions only after full-span quote checks.

    The closed interval is retrospective evidence, not knowledge of a future
    resumption date at suspension start. Publication clocks remain separate.
    """
    rows=read(AUDIT/'issue_closure/stock_interval_proposals.json');c=db();verified=[]
    master=pd.read_parquet(MARKET/'stock_master_history.parquet')
    documents=read(PUBLIC/'issuer_cninfo_documents.json')
    for row in rows:
        a,b=row['start_evidence'],row['end_evidence']
        if not a or not b:continue
        for evidence in [a,b]:
            assert sha(ROOT/evidence['evidence_path'])==evidence['sha256']
            doc=next(d for d in documents if str(d['announcementId'])==str(evidence['announcement_id']))
            assert evidence['excerpt'] in re.sub(r'\s+','',doc['content'])
            assert row['instrument_code'][:6] in re.sub(r'\s+','',doc['content']) or (row['instrument_code']=='600680.SH' and doc.get('extraction_method','').startswith('manual_visual'))
        code=row['instrument_code'];start=max(a['date'],START);end=b['date']
        assert start<=row['gap_start']<=row['gap_end']<end
        quotes=c.execute('SELECT count(*) FROM '+rel('stock_daily')+' WHERE ts_code=? AND trade_date>=? AND trade_date<?',[code,start,end]).fetchone()[0]
        assert quotes==0,(code,'Observed quotes contradict suspension evidence')
        terminal=code in ['600485.SH','600677.SH','600680.SH','601268.SH']
        if terminal:assert end in set(master.loc[master.ts_code.eq(code),'delist_date'])
        else:
            status=c.execute('SELECT status FROM '+rel('stock_trading_status')+' WHERE ts_code=? AND trade_date=?',[code,end]).fetchone()
            assert status and status[0] in ['OBSERVED','SUSPENDED_SOURCE_RECORDED'],(code,'Unverified interval endpoint',status)
        row={**row,'issue_id':'STOCK_GAP_'+code+'_'+row['gap_start'],'review_status':'PRIMARY_INTERVAL_VERIFIED',
             'interval_end_event':'DELISTED' if terminal else 'LISTING_OR_TRADING_RESUMED' if code!='688005.SH' else 'ONE_DAY_NOTICE_EXPIRED',
             'verification_result':'PASS: source hashes/literal excerpts/issuer identity; no quotes anywhere in full interval; endpoint matches trading state or delisting master',
             'closure_available_at':(pd.Timestamp(max(a['release_date'],b['release_date']))+pd.Timedelta(days=1)).tz_localize('Asia/Shanghai').isoformat(),
             'start_notice_available_at':(pd.Timestamp(a['release_date'])+pd.Timedelta(days=1)).tz_localize('Asia/Shanghai').isoformat(),
             'quality_status':'official_interval_retrospectively_verified',
             'quality_reason':'Original issuer/exchange-hosted notice. Whole closed interval is ex post; never expose future end knowledge before end notice. No synthetic prices.'}
        verified.append(row)
    write(AUDIT/'issue_closure/stock_interval_certificates.json',verified)
    intervals=pd.DataFrame([{k:v for k,v in x.items() if k not in ['start_evidence','end_evidence']}|{
        'start_evidence':json.dumps(x['start_evidence'],ensure_ascii=False),'end_evidence':json.dumps(x['end_evidence'],ensure_ascii=False)} for x in verified])
    frame(MARKET/'stock_suspension_intervals.parquet',intervals)
    c.close()  # Release DuckDB's Windows file handles before atomic replacement.
    changed=0
    for path in sorted((MARKET/'stock_trading_status').glob('*.parquet')):
        data=pd.read_parquet(path)
        if 'original_status' not in data:data['original_status']=data.status
        data['status']=data.original_status
        data['adjudication_id']=None;data['adjudication_available_at']=None
        for x in verified:
            mask=data.ts_code.eq(x['instrument_code'])&data.trade_date.between(x['gap_start'],x['gap_end'])&data.original_status.isin(['UNEXPLAINED_MISSING','MISSING_WITH_INTRADAY_SUSPENSION'])
            changed+=int(mask.sum());data.loc[mask,'status']='SUSPENDED_OFFICIAL_EVIDENCE'
            data.loc[mask,'adjudication_id']=x['issue_id'];data.loc[mask,'adjudication_available_at']=x['closure_available_at']
        frame(path,data)
    assert changed==sum(x['missing_observations'] for x in verified)
    c=db()
    summary=c.execute('SELECT status,count(*) observations FROM '+rel('stock_trading_status')+' GROUP BY 1 ORDER BY 1').df()
    frame(AUDIT/'market_coverage/stock_status_after_repair.parquet',summary)
    write(AUDIT/'issue_closure/stock_repair_summary.json',{'intervals_verified':len(verified),'missing_observations_reclassified':changed,'counts':summary.to_dict('records'),'synthetic_quotes_added':0})
    c.close();print('Certified',len(verified),'intervals;',changed,'missing observations reclassified',flush=True)


if __name__=='__main__':proposals();certify_and_apply()
