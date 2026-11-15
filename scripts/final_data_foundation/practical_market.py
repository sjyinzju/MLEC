"""Targeted market repairs; external canonical database is opened read-only."""
from .common import *


def remove_empty_suspended_basic_rows():
    """Quarantine suspension-only placeholders, never a real traded observation."""
    c=db()
    d=c.execute('SELECT b.* FROM read_parquet(?) b ANTI JOIN read_parquet(?) q USING(instrument_id,trade_date)',
        [str(MARKET/'stock_daily_basic_observations/*.parquet'),str(MARKET/'stock_daily_observations/*.parquet')]).df()
    if d.empty:c.close();return 0
    fields=['close','turnover_rate','turnover_rate_f','pe','pe_ttm','pb','ps','ps_ttm',
        'dv_ratio','dv_ttm','total_share','float_share','free_share','total_mv','circ_mv']
    assert d[fields].isna().all().all(), 'Nonempty off-quote fundamentals need separate review'
    c.register('candidates',d)
    evidence=c.execute('SELECT b.source_record_id,b.instrument_id,b.ts_code,b.trade_date,b.volume_ratio rejected_volume_ratio,s.status,s.suspension_record_ids,s.adjudication_id FROM candidates b JOIN read_parquet(?) s USING(instrument_id,trade_date)',
        [str(MARKET/'stock_trading_status/*.parquet')]).df()
    assert len(evidence)==len(d) and evidence.status.isin(['SUSPENDED_SOURCE_RECORDED','SUSPENDED_OFFICIAL_EVIDENCE']).all()
    evidence['reason']='No quote on an evidenced suspension day and all 15 price/valuation/share/turnover fields NULL. Provider volume_ratio has no contemporaneous observed trade and is quarantined here, not admitted as a trading measurement. Nontrading placeholder excluded from canonical daily-basic observations.'
    frame(ROOT/'data/metadata/empty_suspended_basic_exclusions.parquet',evidence)
    for year in sorted(d.trade_date.str[:4].unique()):
        path=MARKET/'stock_daily_basic_observations'/(year+'.parquet')
        c.execute('CREATE OR REPLACE TEMP TABLE base AS SELECT * FROM read_parquet(?)',[str(path)])
        copy_query(c,'SELECT * FROM base ANTI JOIN candidates USING(source_record_id) ORDER BY instrument_id,trade_date',path)
    q=pd.read_parquet(MARKET/'market_data_quality.parquet')
    frame(MARKET/'market_data_quality.parquet',q[~q.source_record_id.isin(d.source_record_id)])
    c.close();print('EMPTY_SUSPENDED_BASIC_EXCLUDED',len(d),flush=True);return len(d)


def classify_nonpositive_book_equity():
    quality_path = MARKET/'market_data_quality.parquet'
    quality = pd.read_parquet(quality_path)
    prior_status = ['BLOCKED_MISSING_REQUIRED_FIELD', 'STRUCTURAL_NONPOSITIVE_BOOK_EQUITY']
    missing = quality[quality.field.eq('pb') & quality.quality_status.isin(prior_status)].copy()
    c = db()
    try:
        c.execute('ATTACH '+qs(SOURCE/'quant.duckdb')+' AS financial_source (READ_ONLY)')
        c.register('missing_pb', missing)
        c.execute('''CREATE TEMP TABLE financial_timeline AS WITH history AS (
          SELECT ts_code,ann_date,arg_max(
            struct_pack(bps:=bps,report_end:=end_date,published:=ann_date,parent_id:=_row_hash),
            struct_pack(period:=end_date,published:=ann_date,captured:=_ingested_at,hash:=_row_hash))
            OVER(PARTITION BY ts_code ORDER BY ann_date RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) p
          FROM financial_source.canonical_fina_indicator
          WHERE ts_code IN (SELECT DISTINCT ts_code FROM missing_pb) AND bps IS NOT NULL AND end_date<=ann_date
        ) SELECT DISTINCT ts_code,ann_date,p FROM history''')
        matched = c.execute('''SELECT q.quality_record_id,q.ts_code,q.trade_date,
          f.p.bps bps,f.p.report_end report_end,f.p.published publication_date,
          f.p.parent_id financial_parent_id FROM missing_pb q ASOF LEFT JOIN financial_timeline f
          ON q.ts_code=f.ts_code AND q.trade_date>f.ann_date''').df()
    finally:
        c.close()
    age = (pd.to_datetime(matched.trade_date)-pd.to_datetime(matched.report_end)).dt.days
    # A latest Q3 statement routinely remains the latest disclosed statement
    # until the following annual-report deadline. A blanket 150-day fiscal-age
    # rule falsely classified these nonpositive-equity PBs as data gaps.
    period = pd.to_datetime(matched.report_end)
    annual_deadline = pd.to_datetime((period.dt.year+1).astype('Int64').astype(str)+'-04-30', errors='coerce')
    q3_current = period.dt.month.eq(9) & period.dt.day.eq(30) & pd.to_datetime(matched.trade_date).le(annual_deadline)
    usable = matched[matched.bps.le(0) & (age.between(0,150) | q3_current)].copy()
    assert (usable.publication_date < usable.trade_date).all()
    assert not usable.quality_record_id.duplicated().any()
    basis_path = ROOT/'data/metadata/pb_denominator_basis.parquet'
    basis = usable[['ts_code','financial_parent_id','bps','report_end','publication_date']].drop_duplicates()
    basis['source'] = 'TuShare fina_indicator via E:/QuantData read-only canonical view'
    basis['source_url'] = 'https://tushare.pro/document/2?doc_id=79'
    basis['quality'] = 'historical_reconstructed; financial revisions are not original PIT vintages'
    basis['q3_validity_basis'] = 'https://www.csrc.gov.cn/csrc/c100028/c1002922/content.shtml; latest disclosed Q3 may remain current through next April 30 annual-report deadline'
    frame(basis_path,basis)
    positions = quality.quality_record_id.isin(usable.quality_record_id)
    quality.loc[positions,'quality_status'] = 'STRUCTURAL_NONPOSITIVE_BOOK_EQUITY'
    parent = usable.set_index('quality_record_id').financial_parent_id
    quality.loc[positions,'quality_reason'] = quality.loc[positions,'quality_record_id'].map(parent).map(
        lambda p: 'Positive-book-equity valuation convention: PB not meaningful when latest reported BPS<=0; '
        'report disclosed before trade date, fiscal age<=150 days or latest Q3 before next annual-report deadline; value remains NULL. '
        'Financial history reconstructed, parent='+p)
    quality.loc[positions,'evidence_path'] = basis_path.relative_to(ROOT).as_posix()
    frame(quality_path,quality)
    print('PB_STRUCTURAL',len(usable),'REMAINING_MISSING',len(missing)-len(usable),flush=True)
    return len(usable)


def refresh_missing_free_shares():
    """Refresh the missing parent, even when the API ratio remains NULL."""
    from .provider import client
    c=db();adapter,catalog=client();rows=[]
    missing=c.execute('SELECT * FROM read_parquet(?) WHERE turnover_rate_f IS NULL AND free_share IS NULL',
        [str(MARKET/'stock_daily_basic_observations/*.parquet')]).df()
    for row in missing.itertuples(index=False):
        reply=adapter.fetch(catalog['daily_basic'],{'ts_code':row.ts_code,'trade_date':row.trade_date})
        data=pd.DataFrame(reply.rows,columns=reply.fields)
        data=data[data.ts_code.eq(row.ts_code)&data.trade_date.eq(row.trade_date)] if len(data) else data
        if len(data)!=1:continue
        value=data.iloc[0]
        if not (pd.notna(value.free_share) and 0<value.free_share<=row.float_share<=row.total_share
                and abs(value.close-row.close)<.00001 and abs(value.float_share-row.float_share)<=.001):continue
        rows.append(dict(source_record_id=row.source_record_id,ts_code=row.ts_code,trade_date=row.trade_date,
            value=value.free_share,retrieved_at=reply.fetched_at,source_url='https://tushare.pro/document/2?doc_id=32',
            field='free_share',unit='10000 shares'))
    if rows:
        repairs=pd.DataFrame(rows);path=ROOT/'data/metadata/free_share_refreshes.parquet'
        old=pd.read_parquet(path) if path.exists() else repairs.iloc[:0]
        frame(path,pd.concat([old,repairs],ignore_index=True).drop_duplicates('source_record_id'))
        c.register('repairs',repairs)
        for year in repairs.trade_date.str[:4].unique():
            p=MARKET/'stock_daily_basic_observations'/(year+'.parquet')
            copy_query(c,'SELECT b.* REPLACE(coalesce(b.free_share,r.value) AS free_share) FROM read_parquet('+qs(p)+') b LEFT JOIN repairs r USING(source_record_id) ORDER BY b.instrument_id,b.trade_date',p)
    c.close();return len(rows)


def fill_free_turnover():
    """Use actual traded volume and same-day free shares, never float shares."""
    c = db()
    try:
        candidates = c.execute('''SELECT b.source_record_id,b.ts_code,b.trade_date,b.free_share,
          q.source_record_id quote_parent,q.volume_shares,
          q.volume_shares/(b.free_share*10000)*100 AS derived_turnover_rate_f
          FROM read_parquet(?) b JOIN read_parquet(?) q USING(instrument_id,trade_date)
          WHERE b.turnover_rate_f IS NULL AND b.free_share>0
            AND b.free_share<=b.float_share AND b.float_share<=b.total_share
            AND abs(b.close-q.close)<0.00001 AND q.volume_shares>=0''',
          [str(MARKET/'stock_daily_basic_observations/*.parquet'),str(MARKET/'stock_daily_observations/*.parquet')]).df()
        if candidates.empty:
            return 0
        evidence = ROOT/'data/metadata/free_turnover_derivations.parquet'
        candidates['formula'] = 'volume_shares/(free_share_in_10000_shares*10000)*100; percent'
        candidates['source_url'] = 'https://tushare.pro/document/2?doc_id=32'
        candidates['quality'] = 'derived_same_day_historical_reconstructed'
        prior = pd.read_parquet(evidence) if evidence.exists() else candidates.iloc[:0]
        frame(evidence,pd.concat([prior,candidates],ignore_index=True).drop_duplicates('source_record_id'))
        c.register('repairs',candidates)
        for year in sorted(candidates.trade_date.str[:4].unique()):
            path = MARKET/'stock_daily_basic_observations'/(year+'.parquet')
            copy_query(c,'''SELECT b.* REPLACE(coalesce(b.turnover_rate_f,r.derived_turnover_rate_f) AS turnover_rate_f)
              FROM read_parquet('''+qs(path)+''') b LEFT JOIN repairs r USING(source_record_id)
              ORDER BY b.instrument_id,b.trade_date''',path)
        quality_path = MARKET/'market_data_quality.parquet'
        quality = pd.read_parquet(quality_path)
        changed = quality.field.eq('turnover_rate_f') & quality.source_record_id.isin(candidates.source_record_id)
        assert changed.sum()==len(candidates)
        quality.loc[changed,'quality_status'] = 'DERIVED_SAME_DAY_FREE_TURNOVER'
        quality.loc[changed,'quality_reason'] = 'Missing turnover computed from traded volume and same-day free shares; percent, not float-share turnover.'
        quality.loc[changed,'evidence_path'] = evidence.relative_to(ROOT).as_posix()
        frame(quality_path,quality)
        print('FREE_TURNOVER_FILLED',len(candidates),flush=True)
        return len(candidates)
    finally:
        c.close()


if __name__ == '__main__':
    classify_nonpositive_book_equity()
    fill_free_turnover()
