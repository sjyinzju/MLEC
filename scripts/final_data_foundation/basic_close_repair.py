"""Apply independently verified quote corrections to the actual v5 authority."""
from .common import *


def collect():
    import baostock as bs
    c=db();base=c.execute('SELECT b.*,d.close quote_close,d.volume_shares FROM read_parquet(?) b JOIN read_parquet(?) d USING(instrument_id,trade_date) WHERE abs(b.close-d.close)>.00001',
        [str(MARKET/'stock_daily_basic_observations/*.parquet'),str(MARKET/'stock_daily_observations/*.parquet')]).df();c.close()
    if base.empty:return
    records=[];assert bs.login().error_code=='0'
    try:
        for r in base.itertuples(index=False):
            day=pd.Timestamp(r.trade_date).strftime('%Y-%m-%d')
            reply=bs.query_history_k_data_plus(r.ts_code[-2:].lower()+'.'+r.ts_code[:6],
                'date,close,volume,turn,peTTM,pbMRQ,psTTM',start_date=day,end_date=day,adjustflag='3')
            data=reply.get_data();assert len(data)==1
            row=dict(source_record_id=r.source_record_id,ts_code=r.ts_code,trade_date=r.trade_date,
                quote_close=r.quote_close,volume_shares=r.volume_shares,provider_close=r.close)
            row.update({'alternate_'+f:float(data.iloc[0][f]) for f in ['close','volume','turn','peTTM','pbMRQ','psTTM']})
            records.append(row)
    finally:bs.logout()
    frame(ROOT/'data/metadata/basic_close_independent_basis.parquet',pd.DataFrame(records))


def apply():
    evidence=ROOT/'data/metadata/basic_close_independent_basis.parquet';p=pd.read_parquet(evidence)
    c=db();c.register('parents',p)
    b=c.execute('SELECT b.* FROM read_parquet(?) b JOIN parents USING(source_record_id)',[str(MARKET/'stock_daily_basic_observations/*.parquet')]).df()
    rows=[];unresolved=[]
    for i,r in b.iterrows():
        parent=p[p.source_record_id.eq(r.source_record_id)].iloc[0]
        assert abs(parent.alternate_close-parent.quote_close)<1e-9 and abs(parent.alternate_volume-parent.volume_shares)<=1.01
        if abs(r.close-parent.quote_close)<1e-9:continue
        assert abs(r.close-parent.provider_close)<1e-9
        multiplier=parent.quote_close/parent.provider_close
        # TTM ratios independently agree after correcting only the price.
        for f,alternate in [('pe_ttm','peTTM'),('ps_ttm','psTTM')]:
            if pd.notna(r[f]):assert abs(r[f]*multiplier-parent['alternate_'+alternate])<.000151
        changes=dict(close=parent.quote_close,total_mv=parent.quote_close*r.total_share,
            circ_mv=parent.quote_close*r.float_share,turnover_rate=parent.volume_shares/r.float_share/100,
            turnover_rate_f=parent.volume_shares/r.free_share/100)
        for f in ['pe','pe_ttm','pb','ps','ps_ttm']:
            if pd.notna(r[f]):changes[f]=r[f]*multiplier
        if pd.notna(r.pb) and abs(changes['pb']-parent.alternate_pbMRQ)>.000151:
            changes['pb']=float('nan');unresolved.append(r.source_record_id)
        for field,value in changes.items():
            rows.append(dict(source_record_id=r.source_record_id,ts_code=r.ts_code,trade_date=r.trade_date,
                field=field,old_value=r[field],value=value,quote_close=parent.quote_close,provider_close=parent.provider_close,
                volume_shares=parent.volume_shares,total_share=r.total_share,float_share=r.float_share,free_share=r.free_share,
                formula='Verified quote; cap=price*same-day shares; turnover=volume/shares; price ratios=rescale by corrected/old price holding reported financial denominator fixed. PB disagreement left NULL.',
                source_url='https://baostock.com/mainContent?file=DailyUpdates.md',quality='QUALIFIED_CORRECTED_QUOTE_RECONSTRUCTION'))
            b.at[i,field]=value
    if not rows:c.close();return
    patch=pd.DataFrame(rows);path=ROOT/'data/metadata/basic_close_field_repairs.parquet';frame(path,patch)
    c.register('repairs',b)
    columns=patch.field.unique().tolist()
    for year in b.trade_date.str[:4].unique():
        target=MARKET/'stock_daily_basic_observations'/(year+'.parquet')
        expr=','.join('CASE WHEN r.source_record_id IS NOT NULL THEN r.'+f+' ELSE x.'+f+' END AS '+f for f in columns)
        copy_query(c,'SELECT x.* REPLACE('+expr+') FROM read_parquet('+qs(target)+') x LEFT JOIN repairs r USING(source_record_id) ORDER BY x.instrument_id,x.trade_date',target)
    c.close();qpath=MARKET/'market_data_quality.parquet';q=pd.read_parquet(qpath);extra=[]
    for r in patch.itertuples(index=False):
        mask=q.source_record_id.eq(r.source_record_id)&q.field.eq(r.field)
        status='BLOCKED_MISSING_REQUIRED_FIELD' if pd.isna(r.value) else 'QUALIFIED_CORRECTED_QUOTE_RECONSTRUCTION'
        reason='Independent PB disagrees after quote correction; incompatible book denominator, no substitution.' if pd.isna(r.value) else r.formula
        if mask.any():
            q.loc[mask,'quality_status']=status;q.loc[mask,'quality_reason']=reason;q.loc[mask,'evidence_path']=path.relative_to(ROOT).as_posix()
        else:
            instrument=b.loc[b.source_record_id.eq(r.source_record_id),'instrument_id'].iloc[0]
            extra.append(dict(ts_code=r.ts_code,trade_date=r.trade_date,source_record_id=r.source_record_id,field=r.field,
                dataset_id='stock_daily_basic',quality_status=status,quality_reason=reason,evidence_path=path.relative_to(ROOT).as_posix(),
                instrument_id=instrument,quality_record_id=hashlib.sha256(('corrected_quote:'+r.source_record_id+':'+r.field).encode()).hexdigest(),data_version='practical-research-data-v5'))
    frame(qpath,pd.concat([q,pd.DataFrame(extra)],ignore_index=True))
    print('AUTHORITATIVE_BASIC_CLOSE_REPAIRS',len(b),'FIELDS',len(patch),'PB_CONFLICTS',len(unresolved),flush=True)


if __name__=='__main__':collect();apply()
