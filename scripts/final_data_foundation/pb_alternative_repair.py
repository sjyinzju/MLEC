"""Independent MRQ valuation evidence for remaining PB gaps, no raw retention."""
import socket
import numpy as np
from .common import *


def collect():
    socket.setdefaulttimeout(20)
    import baostock as bs
    q=pd.read_parquet(MARKET/'market_data_quality.parquet')
    gaps=q[q.field.eq('pb')&q.quality_status.eq('BLOCKED_MISSING_REQUIRED_FIELD')]
    c=db();c.register('gaps',gaps)
    base=c.execute('''SELECT b.source_record_id,b.ts_code,b.trade_date,b.close,b.pb,d.volume_shares
      FROM read_parquet(?) b JOIN (SELECT DISTINCT ts_code FROM gaps) g USING(ts_code)
      JOIN read_parquet(?) d ON b.instrument_id=d.instrument_id AND b.trade_date=d.trade_date''',
      [str(MARKET/'stock_daily_basic_observations/*.parquet'),str(MARKET/'stock_daily_observations/*.parquet')]).df()
    c.close();records=[];checks=[];failures=[]
    assert bs.login().error_code=='0'
    try:
        for number,(code,g) in enumerate(gaps.groupby('ts_code'),1):
            start=(pd.Timestamp(g.trade_date.min())-pd.Timedelta(days=45)).strftime('%Y-%m-%d')
            end=(pd.Timestamp(g.trade_date.max())+pd.Timedelta(days=45)).strftime('%Y-%m-%d')
            symbol=code[-2:].lower()+'.'+code[:6]
            result=bs.query_history_k_data_plus(symbol,'date,code,close,volume,pbMRQ',start_date=start,end_date=end,frequency='d',adjustflag='3')
            if result.error_code!='0':failures.append(dict(ts_code=code,error=result.error_code));continue
            values=[]
            while result.next():values.append(result.get_row_data())
            if not values:failures.append(dict(ts_code=code,error='EMPTY'));continue
            new=pd.DataFrame(values,columns=result.fields)
            for field in ['close','volume','pbMRQ']:new[field]=pd.to_numeric(new[field],errors='coerce')
            new['trade_date']=pd.to_datetime(new.date).dt.strftime('%Y%m%d')
            joined=base[base.ts_code.eq(code)].merge(new[['trade_date','close','volume','pbMRQ']],on='trade_date',suffixes=('_primary','_alternate'),validate='one_to_one')
            price_ok=(joined.close_primary-joined.close_alternate).abs().lt(.00011)
            volume_ok=(joined.volume_shares-joined.volume).abs().le(1.01)
            overlap=joined[joined.pb.gt(0)&joined.pbMRQ.gt(0)&price_ok&volume_ok]
            agreement=(overlap.pb-overlap.pbMRQ).abs().le(.000151)
            # Positive ratio substitution requires actual same-code precision
            # agreement, not just similar-sounding vendor field names.
            compatible=len(overlap)>=5 and agreement.mean()>=.95
            checks.append(dict(ts_code=code,overlap=len(overlap),agree=int(agreement.sum()),compatible=bool(compatible)))
            target=joined[joined.source_record_id.isin(g.source_record_id)&price_ok&volume_ok&joined.pbMRQ.notna()]
            for row in target.itertuples(index=False):
                records.append(dict(ts_code=code,trade_date=row.trade_date,source_record_id=row.source_record_id,
                    alternate_pb_mrq=float(row.pbMRQ),close=float(row.close_primary),volume_shares=float(row.volume_shares),
                    positive_substitution_compatible=bool(compatible),overlap_rows=len(overlap),overlap_agree=int(agreement.sum()),
                    source_url='https://baostock.com/mainContent?file=DailyUpdates.md',
                    retrieved_at=pd.Timestamp.now(tz='Asia/Shanghai'),quality='historical_reconstructed_not_original_vintage'))
            if number%25==0:print('PB_ALTERNATIVE',number,'/',gaps.ts_code.nunique(),len(records),flush=True)
    finally:bs.logout()
    frame(ROOT/'data/metadata/pb_alternative_basis.parquet',pd.DataFrame(records))
    write(ROOT/'data/metadata/pb_alternative_crosscheck.json',dict(checks=checks,failures=failures,
        policy='Same date/code/unadjusted close and actual traded volume; positive PB admission additionally needs >=5 same-code overlapping positive PBs with >=95% agreement within 0.000151, reflecting primary 4-decimal display. Negative MRQ ratios prove nonpositive book denominator, not numeric positive PB.'))
    d=pd.DataFrame(records);print('PB_CANDIDATES',len(d),'negative',int(d.alternate_pb_mrq.lt(0).sum()),'positive_matched',int((d.alternate_pb_mrq.gt(0)&d.positive_substitution_compatible).sum()),flush=True)


def enrich_financial_basis():
    path=ROOT/'data/metadata/pb_alternative_basis.parquet';p=pd.read_parquet(path)
    p=p.drop(columns=[s for s in p if s.startswith(('latest_disclosed','financial_','same_day_'))])
    c=db();c.execute('ATTACH '+qs(SOURCE/'quant.duckdb')+' AS ext (READ_ONLY)');c.register('p',p)
    c.execute('''CREATE TEMP TABLE f AS WITH history AS (
      SELECT ts_code,ann_date,arg_max(struct_pack(bps:=bps,report_end:=end_date,published:=ann_date,parent_id:=_row_hash),
        struct_pack(period:=end_date,published:=ann_date,captured:=_ingested_at,hash:=_row_hash))
        OVER(PARTITION BY ts_code ORDER BY ann_date RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) r
      FROM ext.canonical_fina_indicator WHERE ts_code IN (SELECT DISTINCT ts_code FROM p)
        AND bps IS NOT NULL AND end_date<=ann_date)
      SELECT DISTINCT ts_code,ann_date,r FROM history''')
    out=c.execute('''SELECT p.*,f.r.bps same_day_disclosed_bps,f.r.report_end same_day_report_end,
      f.r.published same_day_ann_date,f.r.parent_id same_day_financial_parent_id
      FROM p ASOF LEFT JOIN f ON p.ts_code=f.ts_code AND p.trade_date>=f.ann_date''').df()
    c.close();frame(path,out)


def apply():
    path=ROOT/'data/metadata/pb_alternative_basis.parquet';p=pd.read_parquet(path)
    if 'same_day_disclosed_bps' not in p:enrich_financial_basis();p=pd.read_parquet(path)
    p['source_url']='https://baostock.com/mainContent?file=DailyUpdates.md'
    from .pb_issuer_repair import enrich
    p=p.drop(columns=[s for s in p if s.startswith('issuer_') or s in ['total_mv','total_share','bps_precision_agrees']])
    p=enrich(p)
    # Sign evidence needs an independent financial parent or validated same-code
    # convention. A newer issuer common-equity figure can resolve stale local
    # BPS, including the explicit deduction of other equity instruments.
    issuer_negative=p.issuer_common_equity_cny.lt(0)
    negative=p[p.alternate_pb_mrq.lt(0)&(issuer_negative|(~p.same_day_disclosed_bps.gt(0)&(p.same_day_disclosed_bps.le(0)|p.positive_substitution_compatible)))]
    positive=p[p.alternate_pb_mrq.gt(0)&~p.same_day_disclosed_bps.le(0)&(p.positive_substitution_compatible|p.bps_precision_agrees|p.issuer_pb_agrees)]
    p['admission']='UNRESOLVED_DENOMINATOR_OR_CROSS_SOURCE'
    p.loc[p.source_record_id.isin(negative.source_record_id),'admission']='STRUCTURAL_NONPOSITIVE_BOOK_EQUITY'
    p.loc[p.source_record_id.isin(positive.source_record_id),'admission']='ALTERNATIVE_PB_MRQ_RECONSTRUCTED'
    frame(path,p)
    c=db()
    for year,g in positive.groupby(positive.trade_date.str[:4]):
        c.register('patch',g);target=MARKET/'stock_daily_basic_observations'/(year+'.parquet')
        copy_query(c,'SELECT b.* REPLACE(coalesce(b.pb,p.alternate_pb_mrq) AS pb) FROM read_parquet('+qs(target)+') b LEFT JOIN patch p USING(source_record_id) ORDER BY instrument_id,trade_date',target)
    c.close()
    qpath=MARKET/'market_data_quality.parquet';q=pd.read_parquet(qpath)
    for data,status,reason in [(negative,'STRUCTURAL_NONPOSITIVE_BOOK_EQUITY',
        'Independent negative MRQ ratio corroborated by local nonpositive BPS, validated source convention or a latest issuer common-equity parent. Issuer common equity excludes other equity instruments and can supersede stale total BPS. Retrospective NULL semantics, not before-close PIT certification.'),
        (positive,'ALTERNATIVE_PB_MRQ_RECONSTRUCTED',
        'Independent MRQ history; same-day unadjusted close/volume match. Admission uses validated same-code overlap, disclosed BPS precision or exact issuer common-equity/market-cap reconciliation. Qualified historical reconstruction; parent dates retained, not original-vintage certification.')]:
        selected=q.field.eq('pb')&q.source_record_id.isin(data.source_record_id)
        q.loc[selected,'quality_status']=status;q.loc[selected,'quality_reason']=reason
        q.loc[selected,'evidence_path']=path.relative_to(ROOT).as_posix()
    frame(qpath,q)
    print('PB_ALTERNATIVE_APPLIED','numeric',len(positive),'structural',len(negative),'unresolved',int((q.field.eq('pb')&q.quality_status.eq('BLOCKED_MISSING_REQUIRED_FIELD')).sum()),flush=True)


if __name__=='__main__':
    collect();enrich_financial_basis();apply()
