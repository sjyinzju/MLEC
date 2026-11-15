"""Full-population residual checks and compact-parent repair reconciliation."""
from .common import *


def validate(c,check):
    quality='read_parquet('+qs(MARKET/'market_data_quality.parquet')+')'
    calendar='read_parquet('+qs(MARKET/'trade_calendar/*.parquet')+')'
    for name in ['stock_daily_observations','index_daily']:
        relation='read_parquet('+qs(MARKET/name/'*.parquet')+')'
        check(name+':open_exchange_dates',c.execute("SELECT count(*) FROM "+relation+" x WHERE NOT EXISTS (SELECT 1 FROM "+calendar+" t WHERE t.cal_date=x.trade_date AND t.exchange=CASE WHEN x.ts_code LIKE '%.SZ' THEN 'SZSE' ELSE 'SSE' END AND t.is_open=1)").fetchone()[0])
        bad=' OR '.join(f'{f} IS NULL OR NOT isfinite({f})' for f in ['open','high','low','close','vol','amount'])
        check(name+':finite_required_quotes',c.execute('SELECT count(*) FROM '+relation+' WHERE '+bad).fetchone()[0])
    for year in range(2014,2027):
        c.execute('CREATE OR REPLACE TEMP TABLE a AS SELECT b.*,d.volume_shares,d.close quote_close FROM read_parquet(?) b JOIN read_parquet(?) d USING(instrument_id,trade_date)',
            [str(MARKET/'stock_daily_basic_observations'/f'{year}.parquet'),str(MARKET/'stock_daily_observations'/f'{year}.parquet')])
        check(f'basic:{year}:close_matches_quote',c.execute('SELECT count(*) FROM a WHERE abs(close-quote_close)>.00001 OR close IS NULL').fetchone()[0])
        rules={'total_mv':'abs(total_mv-close*total_share)>greatest(.011,close*.00005+.00005)',
               'circ_mv':'abs(circ_mv-close*float_share)>greatest(.011,close*.00005+.00005)',
               'turnover_rate':'abs(turnover_rate-volume_shares/float_share/100)>.0001',
               'turnover_rate_f':'abs(turnover_rate_f-volume_shares/free_share/100)>.0001'}
        for field,condition in rules.items():
            check(f'basic:{year}:{field}:unflagged_identity_errors',c.execute('SELECT count(*) FROM a WHERE '+condition+' AND NOT EXISTS (SELECT 1 FROM '+quality+" q WHERE q.source_record_id=a.source_record_id AND q.field="+qs(field)+" AND q.quality_status IN ('BLOCKED_UNRESOLVED_SHARE_DENOMINATOR','QUALIFIED_EMPIRICAL_SHARE_PRECISION'))").fetchone()[0])
    c.execute('DROP TABLE a')
    index=c.execute("SELECT trade_date,open,high,low,close FROM read_parquet(?,union_by_name=true) WHERE ts_code='000852.SH'",[str(MARKET/'index_daily/*.parquet')]).df().set_index('trade_date')
    for day in ['20151123','20160104']:
        official=pd.read_parquet(ROOT/'data/metadata'/f'csi1000_official_{day}.parquet').iloc[0]
        check('csi1000:'+day+':official_ohlc',int(any(abs(index.loc[day,f]-official[f])>.00501 for f in ['open','high','low','close'])))
    sz=pd.read_parquet(MARKET/'exchange_activity_sz/2014.parquet').set_index(['ts_code','trade_date'])
    p=pd.read_parquet(ROOT/'data/metadata/szse_2014_quantity_repairs.parquet')
    check('sz2014:direct_quantity_fields',len(p),3675)
    check('sz2014:quantity_source_reconciliation',int(sum(abs(sz.loc[(r.ts_code,r.trade_date),r.field]-r.value)>.01 for r in p.itertuples())))
    check('sz2014:monetary_scope_reconciliation',int(sum(any(abs(sz.loc[(r.ts_code,r.trade_date),f]-getattr(r,'matched_'+f+'_cny'))>1_000_001 for f in ['amount','total_mv','float_mv']) for r in p.itertuples())))
    for filename,field in [('free_share_refreshes','free_share'),('ipo_free_share_basis','free_share'),('demerger_free_share_basis','free_share'),('free_turnover_derivations','turnover_rate_f'),('cdr_unit_repairs',None),('basic_close_field_repairs',None),('restricted_share_repairs',None),('pb_issuer_field_repairs','pb')]:
        p=pd.read_parquet(ROOT/'data/metadata'/f'{filename}.parquet');c.register('repairs',p)
        if filename=='basic_close_field_repairs':
            # The interim quarantined PB now has a reviewed issuer denominator.
            later=pd.read_parquet(ROOT/'data/metadata/pb_issuer_field_repairs.parquet')
            p=p[~(p.field.eq('pb')&p.source_record_id.isin(later.source_record_id))]
        b=c.execute('SELECT b.*,d.volume_shares FROM read_parquet(?) b JOIN (SELECT DISTINCT source_record_id FROM repairs) p USING(source_record_id) JOIN read_parquet(?) d USING(instrument_id,trade_date)',
            [str(MARKET/'stock_daily_basic_observations/*.parquet'),str(MARKET/'stock_daily_observations/*.parquet')]).df().set_index('source_record_id')
        bad=0
        for r in p.itertuples():
            col=field or r.field
            value=getattr(r,'value',None)
            if filename in ['ipo_free_share_basis','demerger_free_share_basis']:value=r.free_share
            if filename=='free_turnover_derivations':
                value=r.derived_turnover_rate_f
                assert abs(value-r.volume_shares/r.free_share/100)<1e-10
            actual=b.loc[r.source_record_id,col]
            bad+=not pd.isna(actual) if pd.isna(value) else pd.isna(actual) or abs(actual-value)>1e-8
        check(filename+':applied_parent_values',int(bad))
    p=pd.read_parquet(ROOT/'data/metadata/pb_alternative_basis.parquet');c.register('repairs',p)
    b=c.execute('SELECT source_record_id,pb FROM read_parquet(?) JOIN repairs USING(source_record_id)',[str(MARKET/'stock_daily_basic_observations/*.parquet')]).df().set_index('source_record_id')
    positive=p[p.admission.eq('ALTERNATIVE_PB_MRQ_RECONSTRUCTED')]
    negative=p[p.admission.eq('STRUCTURAL_NONPOSITIVE_BOOK_EQUITY')]
    check('pb:positive_repair_values',int((b.loc[positive.source_record_id,'pb'].to_numpy()!=positive.alternate_pb_mrq.to_numpy()).sum()))
    positive_evidence=positive.positive_substitution_compatible|positive.bps_precision_agrees|positive.issuer_pb_agrees
    check('pb:positive_overlap_and_sign',int((~positive_evidence|positive.same_day_disclosed_bps.le(0)|positive.alternate_pb_mrq.le(0)).sum()))
    negative_evidence=negative.issuer_common_equity_cny.lt(0)|(~negative.same_day_disclosed_bps.gt(0)&(negative.same_day_disclosed_bps.le(0)|negative.positive_substitution_compatible))
    check('pb:negative_semantics',int((negative.alternate_pb_mrq.ge(0)|~negative_evidence).sum())+int(b.loc[negative.source_record_id,'pb'].notna().sum()))
    check('pb:issuer_formula_agreement',int(((p.issuer_pb-p.total_mv*10000/p.issuer_common_equity_cny).abs()>1e-10).sum()))
    check('pb:issuer_parent_not_future',int((p.issuer_publication_date>p.trade_date).sum()))
    parents=pd.read_parquet(ROOT/'data/metadata/pb_issuer_financial_parents.parquet').set_index('financial_parent_id')
    check('pb:issuer_common_equity_formula',int(((parents.parent_equity_cny-parents.other_equity_instruments_cny-parents.common_equity_cny).abs()>1e-6).sum()))
    repairs=pd.read_parquet(ROOT/'data/metadata/pb_issuer_field_repairs.parquet')
    check('pb:issuer_specific_formula',int(sum(pd.notna(r.value) and abs(r.value-r.total_mv*10000/parents.loc[r.financial_parent_id,'common_equity_cny'])>1e-10 for r in repairs.itertuples())))
    late=repairs.publication_date>repairs.trade_date
    check('pb:late_corrections_explicitly_qualified',int((late&(~repairs.quality_status.eq('QUALIFIED_RESTATED_PB_RECONSTRUCTION')|repairs.contemporaneous_before_close)).sum()))
    check('pb:late_corrections_count',int(late.sum()),4)
    check('pb:publication_clock_not_backdated',int(sum(r.effective_available_at<pd.Timestamp(r.publication_date,tz='Asia/Shanghai')+pd.Timedelta(hours=23,minutes=59,seconds=59) for r in repairs.itertuples())))
    facts=pd.read_parquet(MACRO/'macro_facts.parquet')
    for filename in ['mofcom_trade_repairs','attributed_trade_repairs']:
        p=pd.read_parquet(ROOT/'data/metadata'/f'{filename}.parquet')
        for r in p.itertuples():
            actual=facts[facts.series_id.eq(r.series_id)&facts.period_end.eq(r.period_end)&facts.source_url.eq(r.source_url)]
            assert len(actual)==1 and actual.iloc[0].value==r.value
            assert actual.iloc[0].research_available_at>=pd.Timestamp(r.publication_date,tz='Asia/Shanghai')+pd.Timedelta(hours=23,minutes=59,seconds=59)
        check(filename+':admitted_records',len(p),18 if filename=='mofcom_trade_repairs' else 8)
