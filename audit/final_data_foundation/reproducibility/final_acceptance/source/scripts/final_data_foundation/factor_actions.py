"""Primary-announcement adjudication; explicit factor patch, never price smoothing."""
import re
from .common import *
from .collect import PUBLIC


def build():
    documents=read(PUBLIC/'factor_action_announcements.json')
    doc=next(r for r in documents if r['url'].endswith('/1200713708.PDF'))
    assert sha(ROOT/doc['path'])==doc['sha256']
    text=re.sub(r'\s+','',doc['text'])
    assert all(x in text for x in ['每10股转增3股','除权日为：2015年3月26日','000545'])
    tx=read(AUDIT/'source_reconciliation/factor_000545_hfq.json')
    assert sha(ROOT/tx['path'])==tx['sha256']
    rows=read(ROOT/tx['path'])['data']['sz000545']['hfqday'];prices={x[0]:float(x[2]) for x in rows}
    primary_return=15.34*1.3/19.4-1
    independent_return=prices['2015-03-26']/prices['2015-03-25']-1
    assert abs(primary_return-independent_return)<.0002
    c=db();changed=0
    for year in range(2015,2027):
        path=MARKET/'stock_adjustment_observations'/f'{year}.parquet'
        c.execute('CREATE OR REPLACE TEMP TABLE base AS SELECT * FROM read_parquet(?)',[str(path)])
        cols={r[0] for r in c.execute('DESCRIBE base').fetchall()}
        if 'provider_refreshed_adj_factor' not in cols:
            c.execute('ALTER TABLE base ADD COLUMN provider_refreshed_adj_factor DOUBLE')
            c.execute('UPDATE base SET provider_refreshed_adj_factor=adj_factor')
        if 'official_action_evidence' not in cols:c.execute('ALTER TABLE base ADD COLUMN official_action_evidence VARCHAR')
        if 'official_action_parent_id' not in cols:
            c.execute('ALTER TABLE base ADD COLUMN official_action_parent_id VARCHAR')
        where="ts_code='000545.SZ' AND trade_date>='20150326'"
        c.execute('UPDATE base SET official_action_parent_id=NULL WHERE NOT ('+where+')')
        c.execute("UPDATE base SET official_action_parent_id=source_record_id WHERE "+where+" AND source_record_id NOT LIKE 'derived:official_000545_20150326:%'")
        changed+=c.execute('SELECT count(*) FROM base WHERE '+where).fetchone()[0]
        c.execute("UPDATE base SET adj_factor=provider_refreshed_adj_factor*1.3,source_record_id='derived:official_000545_20150326:'||trade_date, source_id='mlec:official_corporate_action',official_action_evidence=?,quality_reason=? WHERE "+where,
          [doc['path'],'Official 10-for-3 capitalisation on 2015-03-26 omitted from provider factor. Full subsequent factor scale multiplied by 1.3; all subsequent provider ratios retained. Independent Tencent adjusted day return agrees within 0.02 percentage points. Actual vintage availability remains retrieval.'])
        copy_query(c,'SELECT * FROM base ORDER BY instrument_id,trade_date',path)
    c.close()
    write(AUDIT/'issue_closure/official_factor_repair.json',{'instrument_id':'000545.SZ','event_date':'2015-03-26','factor_multiplier':1.3,'affected_rows':changed,
      'primary_evidence':doc['path'],'primary_sha256':doc['sha256'],'independent_evidence':tx['path'],
      'primary_return':primary_return,'independent_return':independent_return,'status':'REPAIRED_REQUIRES_POPULATION_RECHECK',
      'root_cause':'Fresh provider factor unchanged across documented 10-for-3 capitalisation. This understates holding return by 23.74 percentage points on ex-date.'})


def classify():
    c=db();p=AUDIT/'market_coverage/adjusted_return_population.parquet'
    d=c.execute("SELECT * FROM read_parquet(?) WHERE verification_status='REFERENCE_FACTOR_DIFFERENCE_REQUIRES_REVIEW'",[str(p)]).df();c.close()
    d['precision_bound_price']=.011+d.previous_traded_close*.0005*(1/d.adj_factor+d.previous_factor/d.adj_factor.pow(2))
    d['classification']='UNRESOLVED_FACTOR_OR_REFERENCE_BASIS'
    d.loc[d.reference_price_residual.abs().le(d.precision_bound_price),'classification']='COMPATIBLE_WITH_0_001_FACTOR_QUANTIZATION_NOT_CERTIFIED'
    d['evidence_path']=None
    docs=read(PUBLIC/'factor_action_announcements.json')
    for code,date,suffix,multiplier in [('000670.SZ','20140715','1200046784.PDF',3.),('600610.SH','20141125','1200404715.PDF',4.2)]:
        doc=next(r for r in docs if r['url'].endswith(suffix));txt=re.sub(r'\s+','',doc['text'])
        assert sha(ROOT/doc['path'])==doc['sha256'] and '不计算除权参考价' in txt
        m=d.ts_code.eq(code)&d.trade_date.eq(date);assert m.sum()==1
        assert (d.loc[m,'factor_ratio']-multiplier).abs().max()<.003
        d.loc[m,'classification']='OFFICIAL_SHARE_REFORM_HOLDING_RETURN_DIFFERS_FROM_EXCHANGE_REFERENCE'
        d.loc[m,'evidence_path']=doc['path']
    # 600733 still has competing share-compensation interpretations. Agreement
    # between two quotation providers is insufficient to override issuer terms.
    m=d.ts_code.eq('600733.SH')&d.trade_date.eq('20180927')
    d.loc[m,'classification']='OPEN_SHARE_REFORM_FACTOR_BASIS';d.loc[m,'evidence_path']=next(r['path'] for r in docs if r['url'].endswith('1205465503.PDF'))
    frame(AUDIT/'source_reconciliation/factor_adjudications.parquet',d)
    summary=d.classification.value_counts().to_dict()
    r=read(AUDIT/'issue_closure/official_factor_repair.json');r['status']='REPAIRED_POPULATION_RECHECK_COMPLETED';r['remaining_discrepancy_classes']=summary
    assert not (d.ts_code.eq('000545.SZ')&d.trade_date.eq('20150326')).any()
    write(AUDIT/'issue_closure/official_factor_repair.json',r)
    r=read(AUDIT/'issue_closure/factor_repairs.json');r['status']='REPAIRED_WITH_REMAINING_FACTOR_QUALIFICATIONS';r['remaining_discrepancy_classes']=summary
    write(AUDIT/'issue_closure/factor_repairs.json',r)
    print('Factor adjudications',summary,flush=True)


if __name__=='__main__':
    from .deep_market_checks import stock_adjustment_checks
    build();stock_adjustment_checks();classify()
