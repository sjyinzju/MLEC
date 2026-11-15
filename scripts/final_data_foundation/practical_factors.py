"""Repair four documented action boundaries without changing frozen v2 inputs.

Cash events use the gross-cash ex-price continuity convention, not a claim of
cash-reinvested total return. The share-reform factor follows an original
tradable shareholder's sequential entitlements, not the exchange reference.
"""
import numpy as np
from .common import *


EVIDENCE = ROOT/'data/metadata/corporate_action_repairs.parquet'


def events():
    rows = []
    for day, cash, previous, factor_before, factor_after, url in [
        ('20200518', .36, 9.15, 3.603, 3.744, 'https://static.cninfo.com.cn/finalpage/2020-05-09/1207723267.PDF'),
        ('20210430', .41, 12.90, 3.744, 3.874, 'https://data.eastmoney.com/notices/detail/000011/AN202104231487303776.html'),
        ('20220711', .68, 12.86, 3.874, 4.082, 'https://static.cninfo.com.cn/finalpage/2022-07-02/1213919661.PDF'),
    ]:
        rows.append(dict(ts_code='000011.SZ', event_date=day, cash_per_share=cash,
            previous_traded_close=previous, provider_before=factor_before,
            provider_after=factor_after, expected_ratio=previous/(previous-cash),
            source_url=url, basis='Gross CNY cash dividend; no share change; exact ex-price continuity.',
            document_type='issuer_announcement' if 'cninfo' in url else 'issuer_announcement_fulltext_reproduction'))
    rows.append(dict(ts_code='600733.SH', event_date='20180927', cash_per_share=0.,
        previous_traded_close=52.69, provider_before=2.34, provider_after=9.36,
        expected_ratio=1.5*3.5,
        source_url='https://static.cninfo.com.cn/finalpage/2018-09-26/1205465503.PDF; '
            'https://data.eastmoney.com/notices/detail/600733/AN201808191180565942.html; '
            'https://data.eastmoney.com/notices/detail/600733/AN201809121194183608.html',
        basis='Original tradable holders: 10-for-5 compensation credited 2018-08-21, then 10-for-25 capitalisation ex 2018-09-19. 75.6m original shares -> 113.4m -> 396.9m. First resumed trade 2018-09-27; exchange pre_close 15.05 reflects only capitalisation and must remain unchanged.',
        document_type='issuer_announcement_and_implementation_reproductions'))
    d=pd.DataFrame(rows)
    d['correction_multiplier']=d.expected_ratio/(d.provider_after/d.provider_before)
    d['quality']='historical_reconstructed_official_action'
    return d


def build():
    e=events();c=db()
    a=c.execute("SELECT * FROM read_parquet(?,union_by_name=true) WHERE ts_code IN ('000011.SZ','600733.SH') ORDER BY ts_code,trade_date",
        [str(MARKET/'stock_adjustment_observations/*.parquet')]).df()
    assert not a.duplicated(['ts_code','trade_date']).any()
    # The pre-action parent column was introduced in 2015 partitions.
    a=a[a.trade_date.ge('20150101')].copy()
    assert a.provider_refreshed_adj_factor.notna().all()
    # Validate the retained provider parent and current quoted action terms.
    quotes=c.execute("SELECT ts_code,trade_date,close,pre_close,lag(close) OVER(PARTITION BY ts_code ORDER BY trade_date) previous_close FROM read_parquet(?) WHERE ts_code IN ('000011.SZ','600733.SH')",
        [str(MARKET/'stock_daily_observations/*.parquet')]).df().set_index(['ts_code','trade_date'])
    for r in e.itertuples(index=False):
        observed=a[a.ts_code.eq(r.ts_code)&a.trade_date.eq(r.event_date)].iloc[0]
        assert abs(observed.provider_refreshed_adj_factor-r.provider_after)<1e-10
        q=quotes.loc[(r.ts_code,r.event_date)]
        assert abs(q.previous_close-r.previous_traded_close)<1e-10
        if r.ts_code=='000011.SZ':assert abs(q.pre_close-(r.previous_traded_close-r.cash_per_share))<1e-10
    a['new_factor']=a.provider_refreshed_adj_factor.copy()
    for r in e[e.ts_code.eq('000011.SZ')].itertuples(index=False):
        m=a.ts_code.eq(r.ts_code)&a.trade_date.ge(r.event_date)
        a.loc[m,'new_factor']*=r.correction_multiplier
    # Credit the two legs on their actual effective dates, including suspension.
    m=a.ts_code.eq('600733.SH')
    stage1=m&a.trade_date.between('20180821','20180918')
    stage2=m&a.trade_date.between('20180919','20180926')
    assert a.loc[stage1,'provider_refreshed_adj_factor'].eq(2.34).all()
    assert np.allclose(a.loc[stage2,'provider_refreshed_adj_factor'],8.192)
    a.loc[stage1,'new_factor']=2.34*1.5
    a.loc[stage2,'new_factor']=2.34*1.5*3.5
    a.loc[m&a.trade_date.ge('20180927'),'new_factor']*=1.3125
    a=a[(a.ts_code.eq('000011.SZ')&a.trade_date.ge('20200518'))|
        (a.ts_code.eq('600733.SH')&a.trade_date.ge('20180821'))].copy()
    a['new_id']='derived:practical_action:'+a.ts_code+':'+a.trade_date
    assert a.new_factor.gt(0).all()
    # No source-record copy: the original factor and lineage already live here.
    frame(EVIDENCE,e)
    for year,patch in a.groupby(a.trade_date.str[:4]):
        path=MARKET/'stock_adjustment_observations'/(year+'.parquet')
        c.execute('CREATE OR REPLACE TEMP TABLE base AS SELECT * FROM read_parquet(?)',[str(path)])
        c.register('patch',patch)
        c.execute("""UPDATE base SET adj_factor=p.new_factor,
          official_action_parent_id=CASE WHEN base.source_record_id LIKE 'derived:practical_action:%' THEN base.official_action_parent_id ELSE base.source_record_id END,
          source_record_id=p.new_id,source_id='mlec:official_corporate_action',
          official_action_evidence=?,quality_reason=?,data_version='practical-research-data-v5'
          FROM patch p WHERE base.ts_code=p.ts_code AND base.trade_date=p.trade_date""",
          [EVIDENCE.relative_to(ROOT).as_posix(),'Historical action reconstruction; original provider factor retained. Cash events use gross-cash ex-price continuity; 600733 uses sequential tradable-holder entitlements. Other subsequent provider ratios unchanged. Actual retrieval availability retained.'])
        copy_query(c,'SELECT * FROM base ORDER BY instrument_id,trade_date',path)
    q=pd.read_parquet(MARKET/'market_data_quality.parquet')
    for r in e.itertuples(index=False):
        mask=q.ts_code.eq(r.ts_code)&q.trade_date.eq(r.event_date)&q.field.eq('adj_factor')
        assert mask.sum()==1
        q.loc[mask,'source_record_id']='derived:practical_action:'+r.ts_code+':'+r.event_date
        q.loc[mask,'quality_status']='REPAIRED_OFFICIAL_ACTION_HISTORICAL'
        q.loc[mask,'quality_reason']=r.basis
        q.loc[mask,'evidence_path']=EVIDENCE.relative_to(ROOT).as_posix()
        q.loc[mask,'data_version']='practical-research-data-v5'
    frame(MARKET/'market_data_quality.parquet',q)
    c.close();print('ACTION_BOUNDARIES_REPAIRED',len(e),'FACTOR_ROWS',len(a),flush=True)


if __name__=='__main__':build()
