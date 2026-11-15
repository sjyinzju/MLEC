"""Issuer-confirmed re-locking, never infer free float from total float."""
from .common import *


def apply():
    c=db()
    b=c.execute("SELECT b.*,d.volume_shares FROM read_parquet(?) b JOIN read_parquet(?) d USING(instrument_id,trade_date) WHERE b.ts_code='002563.SZ' AND b.trade_date BETWEEN '20140416' AND '20150311' ORDER BY b.trade_date",
        [str(MARKET/'stock_daily_basic_observations/*.parquet'),str(MARKET/'stock_daily_observations/*.parquet')]).df()
    assert len(b)==219 and b.total_share.eq(67000).all()
    # April 16 issuer announcement: registered restricted shares 600m;
    # unrestricted 70m through March 11 2015, independently corroborated by
    # 2015 half-year opening share table. Existing observed turnover agrees.
    assert ((b.turnover_rate-b.volume_shares/7000/100).abs()<=.000051).all()
    rows=[]
    for r in b.itertuples():
        for field,value in [('float_share',7000.),('circ_mv',r.close*7000.)]:
            rows.append(dict(source_record_id=r.source_record_id,ts_code=r.ts_code,trade_date=r.trade_date,
                field=field,value=value,registered_total_shares=670000000,registered_restricted_shares=600000000,
                registered_unrestricted_shares=70000000,publication_date='20140417',effective_event_date='20140416',
                source_url='https://epaper.stcn.com/paper/zqsb/html/2014-04/17/content_564492.htm',
                corroborating_url='https://pdf.dfcfw.com/pdf/H2_AN201508280010655551_1.pdf',
                formula='float_share=(registered_total_shares-registered_restricted_shares)/10000; circ_mv=close*float_share',
                quality='issuer_verified_historical_reconstruction_not_original_vintage'))
    p=pd.DataFrame(rows);path=ROOT/'data/metadata/restricted_share_repairs.parquet';frame(path,p)
    b['float_share']=7000.;b['circ_mv']=b.close*7000.;c.register('repairs',b)
    for year in b.trade_date.str[:4].unique():
        target=MARKET/'stock_daily_basic_observations'/(year+'.parquet')
        copy_query(c,'SELECT b.* REPLACE(coalesce(r.float_share,b.float_share) AS float_share,coalesce(r.circ_mv,b.circ_mv) AS circ_mv) FROM read_parquet('+qs(target)+') b LEFT JOIN repairs r USING(source_record_id) ORDER BY b.instrument_id,b.trade_date',target)
    c.close();qpath=MARKET/'market_data_quality.parquet';q=pd.read_parquet(qpath);extra=[]
    for r in b.itertuples():
        for field in ['float_share','circ_mv','turnover_rate']:
            mask=q.source_record_id.eq(r.source_record_id)&q.field.eq(field)
            reason='Issuer registered 600m restricted and70m unrestricted shares through2015-03-11. Correct float and circulating cap; observed turnover agrees with70m. Public confirmation2014-04-17, first event date2014-04-16 is retrospective only. Free float not inferred.'
            if mask.any():
                q.loc[mask,'quality_status']='QUALIFIED_ISSUER_SHARE_RECONSTRUCTION';q.loc[mask,'quality_reason']=reason;q.loc[mask,'evidence_path']=path.relative_to(ROOT).as_posix()
            else:
                extra.append(dict(ts_code=r.ts_code,trade_date=r.trade_date,source_record_id=r.source_record_id,field=field,
                    dataset_id='stock_daily_basic',quality_status='QUALIFIED_ISSUER_SHARE_RECONSTRUCTION',quality_reason=reason,
                    evidence_path=path.relative_to(ROOT).as_posix(),instrument_id=r.instrument_id,
                    quality_record_id=hashlib.sha256(('issuer_relock:'+r.source_record_id+':'+field).encode()).hexdigest(),data_version='practical-research-data-v5'))
    frame(qpath,pd.concat([q,pd.DataFrame(extra)],ignore_index=True))
    print('REGISTERED_RELOCK_REPAIRS',len(p),'TURNOVER_CONFLICTS_CLOSED',len(b),flush=True)


if __name__=='__main__':apply()
