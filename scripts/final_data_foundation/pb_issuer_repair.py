"""Reviewed issuer financial parents for PB, retaining numbers and links only.

All amounts below are consolidated equity attributable to the parent, CNY.
Other equity instruments are liability-side equity instruments, NOT investments.
The four explicitly restated observations carry the later correction clock and
must never be treated as contemporaneously available predictors.
"""
from .common import *


def parents():
    # code, period, actual publication, Sina announcement id, parent equity,
    # other equity instruments; blank equity instrument cells mean zero.
    records = [
        ('000908','20130930','20131031','1239067',-7291589.91,0),
        ('000908','20131231','20140227','1302178',4942188.97,0),
        ('000908','20140331','20140428','1391789',-2130495.24,0),
        ('000908','20140630','20140828','1494247',-10325921.34,0),
        ('000908','20140930','20141028','1535918',-12957459.78,0),
        ('000958','20130930','20131030','1238784',-669175671.54,0),
        ('002015','20140930','20141025','1532528',-54935835.84,0),
        ('600087','20140331','20140415','1359554',-2384755515.74,0),
        ('600217','20140331','20140419','1369291',-36524030.30,0),
        ('600217','20140630','20140819','1477468',-87007834.06,0),
        ('600217','20140930','20141025','1531353',-147563072.72,0),
        ('600217','20141231','20150317','1655592',-209804248.86,0),
        ('002168','20230331','20230420','9012211',2644906.84,0),
        ('002306','20140930','20141113','1552129',493011169.14,0),
        ('002506','20130930','20131028','1234963',576795945.15,0),
        ('002717','20260331','20260429','12271697',-1482834145.37,0),
        ('002775','20260331','20260428','12216773',56130463.79,105809993.71),
        ('300159','20230630','20230829','9465812',70131825.35,0),
        ('300426','20210630','20210830','7504564',11999482.01,0),
        ('300542','20210930','20211026','7607795',533574402.19,0),
        ('002290','20250331','20250424','10962263',855597010.77,0),
        ('002503','20220331','20220429','8146396',210536617.98,135107380.90),
        ('300104','20180630','20180830','4721443',-476513269.77,0),
        ('603005','20190930','20191029','5708055',1924266833.63,0),
        ('600079','20200630','20200822','6525732',9868399763.44,0),
        # Original 300312 report misplaces capital reserve under other equity
        # instruments AND overstates losses. The May 11 correction explicitly
        # supersedes it; these reconstructed numbers are not April 30 PIT data.
        ('300312','20200331','20200511','6265737',76793762.70,0),
    ]
    out=[]
    for code,period,ann,rid,equity,other in records:
        out.append(dict(ts_code=code+('.SH' if code.startswith('6') else '.SZ'),
            report_end=period,publication_date=ann,financial_parent_id='issuer:'+rid,
            parent_equity_cny=equity,other_equity_instruments_cny=other,
            common_equity_cny=equity-other,
            source_url=f'https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?stockid={code}&id={rid}',
            quality='issuer_filing_reviewed_historical_reconstruction',
            corrected_after_target=code=='300312'))
    d=pd.DataFrame(out);frame(ROOT/'data/metadata/pb_issuer_financial_parents.parquet',d)
    return d


def enrich(p):
    """Attach only contemporaneously published/latest relevant issuer periods."""
    f=parents();c=db();c.register('p',p);c.register('f',f[~f.corrected_after_target])
    p=c.execute('''SELECT p.*,f.financial_parent_id issuer_parent_id,
      f.report_end issuer_report_end,f.publication_date issuer_publication_date,
      f.common_equity_cny issuer_common_equity_cny
      FROM p ASOF LEFT JOIN f ON p.ts_code=f.ts_code AND p.trade_date>=f.publication_date''').df()
    c.register('p',p)
    p=c.execute('''SELECT p.*,b.total_mv,b.total_share FROM p
      JOIN read_parquet(?) b USING(source_record_id)''',
      [str(MARKET/'stock_daily_basic_observations/*.parquet')]).df();c.close()
    # An old issuer report cannot override a newer known financial period.
    stale=p.same_day_report_end.notna()&(p.issuer_report_end<p.same_day_report_end)
    p.loc[stale,['issuer_parent_id','issuer_report_end','issuer_publication_date','issuer_common_equity_cny']]=None
    p['issuer_pb']=p.total_mv*10000/p.issuer_common_equity_cny
    p['issuer_pb_agrees']=(p.issuer_pb-p.alternate_pb_mrq).abs().le(.0000011)
    p['bps_precision_agrees']=(p.close/p.alternate_pb_mrq-p.same_day_disclosed_bps).abs().le(.000051)&p.same_day_disclosed_bps.gt(0)
    return p


def apply_remaining():
    """Explicit issuer formulas for the last eleven identified observations."""
    f=parents();qpath=MARKET/'market_data_quality.parquet';q=pd.read_parquet(qpath)
    ids={'002290.SZ':['20250424'],'002503.SZ':['20220627','20220628'],
         '300104.SZ':['20180830'],'600087.SH':['20140429'],
         '603005.SH':['20200318'],'600079.SH':['20201023'],
         '300312.SZ':['20200430','20200506','20200507','20200508']}
    keys=pd.DataFrame([dict(ts_code=k,trade_date=d) for k,v in ids.items() for d in v])
    c=db();c.register('keys',keys)
    b=c.execute('SELECT b.* FROM read_parquet(?) b JOIN keys USING(ts_code,trade_date)',
        [str(MARKET/'stock_daily_basic_observations/*.parquet')]).df()
    assert len(b)==11
    rows=[]
    for r in b.itertuples():
        parent=f[f.ts_code.eq(r.ts_code)].iloc[-1]
        assert parent.publication_date<=r.trade_date or parent.corrected_after_target
        assert abs(r.total_mv-r.close*r.total_share)<=.011
        blocked=q[q.source_record_id.eq(r.source_record_id)&q.field.isin(['total_mv','total_share'])&q.quality_status.str.startswith('BLOCKED')]
        assert blocked.empty
        value=r.total_mv*10000/parent.common_equity_cny if parent.common_equity_cny>0 else float('nan')
        restated=parent.publication_date>r.trade_date
        status='STRUCTURAL_NONPOSITIVE_BOOK_EQUITY' if pd.isna(value) else 'QUALIFIED_RESTATED_PB_RECONSTRUCTION' if restated else 'QUALIFIED_ISSUER_PB_RECONSTRUCTION'
        rows.append(dict(source_record_id=r.source_record_id,ts_code=r.ts_code,trade_date=r.trade_date,
            value=value,total_mv=r.total_mv,total_share=r.total_share,close=r.close,
            financial_parent_id=parent.financial_parent_id,common_equity_cny=parent.common_equity_cny,
            source_url=parent.source_url,publication_date=parent.publication_date,
            effective_available_at=pd.Timestamp(parent.publication_date,tz='Asia/Shanghai')+pd.Timedelta(hours=23,minutes=59,seconds=59),
            contemporaneous_before_close=parent.publication_date<r.trade_date,
            quality_status=status,formula='total_mv (10000 CNY) *10000 / (issuer consolidated parent equity - other equity instruments); NULL if denominator nonpositive'))
    p=pd.DataFrame(rows);path=ROOT/'data/metadata/pb_issuer_field_repairs.parquet';frame(path,p)
    c.register('repairs',p)
    for year in p.trade_date.str[:4].unique():
        target=MARKET/'stock_daily_basic_observations'/(year+'.parquet')
        copy_query(c,'SELECT b.* REPLACE(CASE WHEN p.source_record_id IS NOT NULL THEN p.value ELSE b.pb END AS pb) FROM read_parquet('+qs(target)+') b LEFT JOIN repairs p USING(source_record_id) ORDER BY b.instrument_id,b.trade_date',target)
    c.close()
    for r in p.itertuples():
        selected=q.field.eq('pb')&q.source_record_id.eq(r.source_record_id)
        assert selected.sum()==1
        q.loc[selected,'quality_status']=r.quality_status
        q.loc[selected,'quality_reason']=r.formula+('; financial correction published 2020-05-11: historical-restated only, prohibited as pre-publication predictor' if 'RESTATED' in r.quality_status else '; issuer publication clock retained, same-day release not certified before close')
        q.loc[selected,'evidence_path']=path.relative_to(ROOT).as_posix()
    frame(qpath,q)
    print('ISSUER_PB_APPLIED',len(p),'numeric',int(p.value.notna().sum()),'restated',int(p.quality_status.str.contains('RESTATED').sum()),flush=True)


if __name__=='__main__':apply_remaining()
