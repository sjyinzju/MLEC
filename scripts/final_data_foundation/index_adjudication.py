"""Adjudicate quote differences without averaging conflicting providers."""
import numpy as np
from .common import *
from .market import rel


def build():
    d=pd.read_parquet(AUDIT/'source_reconciliation/index_daily_second_source.parquet')
    d['max_price_difference']=d[['difference_'+x for x in ['open','close','high','low']]].abs().max(axis=1)
    d['price_resolution']=np.select([d.tx_close.isna(),d.max_price_difference.le(.0051),d.max_price_difference.le(.011)],
        ['SECOND_SOURCE_MISSING','AGREEMENT_AT_DISPLAY_PRECISION','LAST_CENT_DIFFERENCE_PRIMARY_PRESERVED'],default='MATERIAL_DIFFERENCE_REQUIRES_REVIEW')
    d['independent_evidence']=None
    for r in read(AUDIT/'source_reconciliation/index_third_source.json'):
        if not isinstance(r['response'],list) or not r['response'] or not r['response'][0].get('hq'):continue
        assert sha(ROOT/r['source']['path'])==r['source']['sha256']
        row=r['response'][0]['hq'][0];values={'open':float(row[1]),'close':float(row[2]),'low':float(row[5]),'high':float(row[6])}
        mask=d.ts_code.eq(r['instrument_id'])&d.trade_date.eq(r['trade_date']);assert mask.sum()==1
        primary=d[mask].iloc[0]
        if all(abs(primary[k]-v)<=.011 for k,v in values.items()):
            d.loc[mask,'price_resolution']='PRIMARY_CONFIRMED_BY_THIRD_PROVIDER'
            d.loc[mask,'independent_evidence']=r['source']['path']
    impossible=d.tx_low.gt(d[['tx_open','tx_close']].min(axis=1))|d.tx_high.lt(d[['tx_open','tx_close']].max(axis=1))
    d.loc[impossible,'price_resolution']='SECOND_SOURCE_INVALID_OHLC_PRIMARY_PRESERVED'
    # Raw Tencent volume differences are retained. Empirical board totals do not
    # certify an undocumented scope or justify altering index-component volume.
    d['volume_resolution']=np.where(d.volume_agree,'CROSS_SOURCE_AGREEMENT','PROVIDER_VOLUME_SCOPE_DIFFERENCE_NOT_INTERCHANGEABLE')
    frame(AUDIT/'source_reconciliation/index_quote_adjudication.parquet',d)
    extreme=d[d.ts_code.eq('399006.SZ')&d.trade_date.isin(['20240930','20241008'])]
    assert len(extreme)==2 and extreme.close.sub(extreme.tx_close).abs().le(.011).all()
    c=db();q=c.execute('SELECT ts_code,trade_date,close,pre_close,pct_chg FROM '+rel('index_daily')+" WHERE ts_code='399006.SZ' AND trade_date IN ('20240930','20241008')").df();c.close()
    assert ((q.close/q.pre_close-1)*100-q.pct_chg).abs().lt(.002).all()
    write(AUDIT/'issue_closure/index_adjudication_summary.json',{'price_resolutions':d.price_resolution.value_counts().to_dict(),
        'volume_resolutions':d.volume_resolution.value_counts().to_dict(),'true_extreme_returns_preserved':q.to_dict('records'),
        'unresolved_material_prices':d[d.price_resolution.eq('MATERIAL_DIFFERENCE_REQUIRES_REVIEW')][['ts_code','trade_date','max_price_difference']].to_dict('records')})


if __name__=='__main__':build()
