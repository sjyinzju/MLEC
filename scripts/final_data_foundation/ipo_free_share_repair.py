"""Initial public-float reconstruction from reviewed issuer listing notices.

Only the named IPO first/second days qualify. Never equate arbitrary historical
unrestricted shares with free float, or backfill from a future quote.
"""
from .common import *
from .practical_market import fill_free_turnover

# All pre-IPO shares locked; the new public shares have no lock or strategic
# allotment. Reviewed issuer tables distinguish public shares from incumbents.
ISSUES = [
    ('002897.SZ','20170907',['20170907','20170908'],2667.,10667.,'2017-09-06','3736419'),
    ('300697.SZ','20170907',['20170907','20170908'],4000.,16000.,'2017-09-06','3735192'),
    ('603527.SH','20170907',['20170907','20170908'],3110.,12440.,'2017-09-06','3736367'),
    ('603011.SH','20141107',['20141107'],4500.,17950.,'2014-11-06','1548090'),
    ('603348.SH','20180426',['20180426'],5500.,22000.,'2018-04-25','4332450'),
]


def build():
    c=db();rows=[]
    for code,listing,dates,public,total,published,identifier in ISSUES:
        d=c.execute('SELECT b.*,q.volume_shares FROM read_parquet(?) b JOIN read_parquet(?) q USING(instrument_id,trade_date) WHERE b.ts_code=? AND b.trade_date BETWEEN ? AND ?',
            [str(MARKET/'stock_daily_basic_observations/*.parquet'),str(MARKET/'stock_daily_observations/*.parquet'),code,dates[0],dates[-1]]).df()
        assert set(d.trade_date)==set(dates)
        assert d.float_share.eq(public).all() and d.total_share.eq(total).all()
        assert d.volume_shares.sum()<total*10000*.001 # tiny first-day trading; no blanket long carry
        for r in d[d.free_share.isna()].itertuples(index=False):
            rows.append(dict(source_record_id=r.source_record_id,ts_code=code,trade_date=r.trade_date,
                free_share=public,total_share=total,listing_date=listing,publication_date=published,
                source_url=f'https://money.finance.sina.com.cn/corp/view/vISSUE_MarketBulletinDetail.php?id={identifier}&stockid={code[:6]}',
                denominator_basis='IPO public shares without lock or strategic allotment; all pre-IPO shares locked; only listed first/second days reviewed',
                quality='QUALIFIED_ISSUER_IPO_PUBLIC_FLOAT_RECONSTRUCTION',unit='10000 shares'))
    if rows:
        r=pd.DataFrame(rows);c.register('repairs',r)
        path=ROOT/'data/metadata/ipo_free_share_basis.parquet'
        old=pd.read_parquet(path) if path.exists() else r.iloc[:0]
        frame(path,pd.concat([old,r],ignore_index=True).drop_duplicates('source_record_id'))
        for year in r.trade_date.str[:4].unique():
            p=MARKET/'stock_daily_basic_observations'/(year+'.parquet')
            copy_query(c,'SELECT b.* REPLACE(coalesce(b.free_share,r.free_share) AS free_share) FROM read_parquet('+qs(p)+') b LEFT JOIN repairs r USING(source_record_id) ORDER BY b.instrument_id,b.trade_date',p)
    c.close();fill_free_turnover()
    if rows:
        path=MARKET/'market_data_quality.parquet';q=pd.read_parquet(path)
        m=q.source_record_id.isin(r.source_record_id)&q.field.eq('turnover_rate_f')
        q.loc[m,'quality_status']='DERIVED_IPO_PUBLIC_FLOAT_TURNOVER'
        q.loc[m,'quality_reason']='Actual volume / initial public shares from reviewed pre-listing issuer notice; qualified first/second-day free-float reconstruction, not general float-share substitution.'
        q.loc[m,'evidence_path']='data/metadata/ipo_free_share_basis.parquet'
        frame(path,q)
    print('IPO_FREE_SHARE_FILLED',len(rows),flush=True)


if __name__=='__main__':build()
