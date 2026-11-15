"""Evidence-bound correction of ordinary price limits on special trading days."""
import re
from .common import *
from .collect import PUBLIC
from .market import rel

DOCUMENT_IDS={
 '000693.SZ':'63471125','000509.SZ':'63482244','000670.SZ':'1200054418',
 '000751.SZ':'1200100623','600385.SH':'1200090979','600610.SH':'1200404716',
 '002506.SZ':'1201424146','300498.SZ':'1201740786','601155.SH':'1201804000',
 '000520.SZ':'1201844011','600732.SH':'1203590981','600710.SH':'1203743097',
 '000155.SZ':'1204231959','001965.SZ':'1204242468','000629.SZ':'1205319473',
 '000950.SZ':'1205338902','600733.SH':'1205467618','688033.SH':'1206466036'}


def certificates():
    targets=read(PUBLIC/'limit_exception_targets.json')
    docs=read(PUBLIC/'issuer_cninfo_documents.json')+read(PUBLIC/'factor_action_announcements.json')+read(PUBLIC/'limit_additional_documents.json')
    ipo={r['code']:r for r in read(PUBLIC/'limit_2014_ipo_documents.json')['records']}
    visual={r['code']:r for r in read(PUBLIC/'limit_visual_reviews.json')}
    rules={r['rule_id']:r for r in read(PUBLIC/'limit_historical_rules.json')}
    for r in rules.values():assert sha(ROOT/r['path'])==r['sha256']
    assert '不实行价格涨跌幅限制' in re.sub(r'\s+','',rules['sz_2013_rule']['text'])
    assert '144%' in rules['sh_2013_ipo']['text'] and '64%' in rules['sh_2013_ipo']['text']
    out=[]
    for target in targets:
        code=target['ts_code'];date=target['trade_date'];day=pd.Timestamp(date)
        is_ipo=code[:6] in ipo
        if is_ipo:r=ipo[code[:6]]
        else:r=next(x for x in docs if x.get('url','').endswith('/'+DOCUMENT_IDS[code]+'.PDF'))
        path=r.get('path',r.get('evidence_path'));digest=r['sha256'];assert sha(ROOT/path)==digest
        text=re.sub(r'\s+','',r.get('text',r.get('content','')))
        formats=[f'{day.year}年{day.month}月{day.day}日',day.strftime('%Y年%m月%d日'),day.strftime('%Y-%m-%d')]
        if code[:6] in visual:
            v=visual[code[:6]];assert v['source_sha256']==digest and v['listing_date']==date and sha(ROOT/v['image_path'])==v['image_sha256']
            date_evidence=v['image_path']+'#page='+str(v['page'])
        else:
            assert any(s in text for s in formats),(code,'Missing literal event date')
            assert code[:6] in text,(code,'Missing issuer code')
            date_evidence=path
        if is_ipo:
            rulelist=[rules['sz_2013_rule'],rules['sz_2013_ipo']] if code.endswith('.SZ') else [rules['sh_2013_ipo']]
            kind='SPECIAL_IPO_AUCTION_REGIME'
            reason='Primary IPO date and contemporaneous exchange rules verified. Ordinary 10% daily limit is inapplicable; session-dependent auction/temporary-halt price controls must not be represented as a fixed ordinary daily limit.'
        else:
            assert re.search('不设涨跌幅|不实行价格涨跌幅|不实行涨跌幅',text),(code,'Missing explicit no-limit clause')
            rulelist=[];kind='STRUCTURAL_NO_DAILY_PRICE_LIMIT'
            reason='Primary issuer announcement explicitly removes daily price limits for the stated event date; auction price ranges and intraday halts remain separate rules.'
        dates=[date]
        if code=='688033.SH':
            assert '上市后5日内' in text
            c=db();dates=c.execute('SELECT cal_date FROM '+rel('trade_calendar')+" WHERE exchange='SSE' AND is_open=1 AND cal_date>=? ORDER BY cal_date LIMIT 5",[date]).df().cal_date.tolist();c.close()
        evidence=json.dumps([path]+[x['path'] for x in rulelist],ensure_ascii=False)
        for event_date in dates:
            rid=hashlib.sha256((code+'|'+event_date+'|'+digest+'|'+kind).encode()).hexdigest()
            out.append({'ts_code':code,'trade_date':event_date,'rule_id':rid,'limit_rule_status':kind,'rule_evidence_path':evidence,'rule_date_evidence':date_evidence,
              'rule_source_sha256':digest,'rule_retrieved_at':max([pd.Timestamp(r['retrieved_at'])]+[pd.Timestamp(x['retrieved_at']) for x in rulelist]),'rule_quality_reason':reason})
    d=pd.DataFrame(out).sort_values(['ts_code','trade_date']);assert len(d)==70 and not d.duplicated(['ts_code','trade_date']).any()
    frame(MARKET/'stock_limit_rule_evidence.parquet',d)
    return d


def build():
    rules=certificates();c=db();c.register('rules',rules)
    output=MARKET/'stock_limits_observations';output.mkdir(parents=True,exist_ok=True)
    for p in sorted((MARKET/'stock_limits').glob('*.parquet')):
        sql='''SELECT s.* REPLACE(
          CASE WHEN r.rule_id IS NOT NULL THEN NULL ELSE s.up_limit END AS up_limit,
          CASE WHEN r.rule_id IS NOT NULL THEN NULL ELSE s.down_limit END AS down_limit,
          CASE WHEN r.rule_id IS NOT NULL THEN 'derived:primary_limit_rule' ELSE s.source_id END AS source_id,
          CASE WHEN r.rule_id IS NOT NULL THEN 'limit_rule:'||r.rule_id ELSE s.source_record_id END AS source_record_id,
          CASE WHEN r.rule_id IS NOT NULL THEN greatest(s.research_available_at,r.rule_retrieved_at) ELSE s.research_available_at END AS research_available_at,
          CASE WHEN r.rule_id IS NOT NULL THEN greatest(s.retrieved_at,r.rule_retrieved_at) ELSE s.retrieved_at END AS retrieved_at,
          CASE WHEN r.rule_id IS NOT NULL THEN 'limit-rule-'||r.rule_id ELSE s.vintage_id END AS vintage_id,
          CASE WHEN r.rule_id IS NOT NULL THEN r.limit_rule_status ELSE s.quality_status END AS quality_status,
          CASE WHEN r.rule_id IS NOT NULL THEN r.rule_quality_reason ELSE s.quality_reason END AS quality_reason),
          s.up_limit provider_up_limit,s.down_limit provider_down_limit,s.source_record_id provider_source_record_id,
          r.rule_id,coalesce(r.limit_rule_status,'PROVIDER_RULE_NOT_INDEPENDENTLY_CERTIFIED') limit_rule_status,r.rule_evidence_path
          FROM read_parquet('''+qs(p)+''') s LEFT JOIN rules r USING(ts_code,trade_date) ORDER BY s.ts_code,s.trade_date'''
        copy_query(c,sql,output/p.name)
    # One original absent row is a proven no-limit day, not a missing price.
    missing=c.execute('SELECT r.* FROM rules r ANTI JOIN '+rel('stock_limits')+' s USING(ts_code,trade_date)').df()
    assert len(missing)==1 and missing.iloc[0].ts_code=='688033.SH' and missing.iloc[0].trade_date=='20190722'
    r=missing.iloc[0];item={k:None for k in c.execute('DESCRIBE SELECT * FROM '+rel('stock_limits_observations')).df().column_name}
    item.update(ts_code=r.ts_code,trade_date=r.trade_date,dataset_id='stock_limits',source_id='derived:primary_limit_rule',source_record_id='limit_rule:'+r.rule_id,
      retrieved_at=r.rule_retrieved_at,research_available_at=r.rule_retrieved_at,vintage_id='limit-rule-'+r.rule_id,quality_status=r.limit_rule_status,quality_reason=r.rule_quality_reason,
      data_version=VERSION,observation_date=pd.Timestamp(r.trade_date),rule_id=r.rule_id,limit_rule_status=r.limit_rule_status,rule_evidence_path=r.rule_evidence_path)
    frame(output/'official_absence.parquet',pd.DataFrame([item]))
    verification=c.execute('SELECT count(*) n,count(*) FILTER(WHERE up_limit IS NOT NULL OR down_limit IS NOT NULL) invalid FROM '+rel('stock_limits_observations')+' WHERE rule_id IS NOT NULL').fetchone()
    assert verification==(70,0)
    write(AUDIT/'issue_closure/limit_rule_repairs.json',{'status':'CLOSED_FOR_66_FLAGGED_DATES','certified_rule_dates':70,'original_flagged_dates':66,
      'ordinary_limit_values_removed_with_originals_preserved':69,'missing_source_row_explained_without_numeric_fill':1,'ipo_primary_documents':48,
      'rule_counts':rules.limit_rule_status.value_counts().to_dict(),'verification':'Original PDFs/hash and literal dates; two damaged text layers visually reviewed; all 70 normalized daily-limit pairs NULL.',
      'remaining':'Full historical ST/board-rule coverage for other dates is not independently certified. Special IPO auction ranges are session-dependent and are not ordinary fixed daily limits.'})
    c.close();print('Primary limit rule corrections',len(rules),flush=True)


if __name__=='__main__':build()
