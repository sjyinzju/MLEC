"""Two free-float gaps with explicit public/locked demerger share evidence."""
from .common import *
from .practical_market import fill_free_turnover


def apply():
    c=db()
    d=c.execute("SELECT * FROM read_parquet(?) WHERE ts_code='601200.SH' AND trade_date BETWEEN '20170331' AND '20170509' ORDER BY trade_date",
        [str(MARKET/'stock_daily_basic_observations/2017.parquet')]).df()
    # Listing notice separates public shareholders from BOTH strategic owners:
    # Shanghai Chengtou326423076 locked36months; Hony64937708 locked12months.
    # The entire311183100 share remainder is explicitly named A-share public.
    public=(702543884-326423076-64937708)/10000
    assert public==31118.31 and d.total_share.eq(70254.3884).all()
    assert d.float_share.eq(public).all() and d.free_share.dropna().eq(public).all()
    dates=['20170505','20170508'];target=d[d.trade_date.isin(dates)].copy();assert len(target)==2
    rows=[]
    for r in target.itertuples():
        rows.append(dict(source_record_id=r.source_record_id,ts_code=r.ts_code,trade_date=r.trade_date,
            free_share=public,total_share=r.total_share,locked_controlling_shares=326423076,
            locked_strategic_shares=64937708,public_shares=311183100,
            publication_date='2017-03-29',listing_date='20170331',
            source_url='https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=3165826&stockid=601200',
            formula='(702543884-326423076-64937708)/10000; strategic owners locked36/12months; issuer explicitly names remainder A-share public shareholders',
            quality='QUALIFIED_ISSUER_DEMERGER_PUBLIC_FLOAT',unit='10000 shares'))
    p=pd.DataFrame(rows);frame(ROOT/'data/metadata/demerger_free_share_basis.parquet',p)
    c.register('repairs',p);path=MARKET/'stock_daily_basic_observations/2017.parquet'
    copy_query(c,'SELECT b.* REPLACE(coalesce(b.free_share,r.free_share) AS free_share) FROM read_parquet('+qs(path)+') b LEFT JOIN repairs r USING(source_record_id) ORDER BY b.instrument_id,b.trade_date',path)
    c.close();fill_free_turnover()
    qpath=MARKET/'market_data_quality.parquet';q=pd.read_parquet(qpath)
    mask=q.field.eq('turnover_rate_f')&q.source_record_id.isin(p.source_record_id)
    assert mask.sum()==2
    q.loc[mask,'quality_status']='DERIVED_DEMERGER_PUBLIC_FLOAT_TURNOVER'
    q.loc[mask,'quality_reason']='Actual traded volume divided by issuer-listed A-share public float; both strategic shareholders locked and total/public quantities unchanged over reviewed listing interval. Not arbitrary neighbor filling.'
    q.loc[mask,'evidence_path']='data/metadata/demerger_free_share_basis.parquet';frame(qpath,q)
    print('DEMERGER_FREE_FLOAT_REPAIRS',len(p),flush=True)


if __name__=='__main__':apply()
