"""Bridge missing SZSE stock quantities using independently matched board totals.

The alternate endpoint has malformed old rows; admission requires agreement of
amount and both market-cap measures with existing official-category values.
No correction based on the magnitude of a suspicious source field is allowed.
"""
import numpy as np
from .common import *
from .provider import client


def compatible(row,reference):
    return all(pd.notna(row[k]) and abs(row[k]*1e8-reference[f])<=1_000_001
        for k,f in [('amount','amount'),('total_mv','total_mv'),('float_mv','float_mv')])


def build(months_filter=None):
    c=db();base=c.execute('SELECT * FROM read_parquet(?,union_by_name=true)',[str(MARKET/'exchange_activity_sz/*.parquet')]).df()
    target=base[base.ts_code.isin(['股票','创业板A股'])&base[['vol','total_share','float_share']].isna().any(axis=1)]
    if months_filter is not None:target=target[target.trade_date.str[:6].isin(months_filter)]
    months=sorted(set(target.trade_date.str[:6]));adapter,catalog=client()
    adapter.settings.max_attempts=1;adapter.settings.timeout_seconds=20
    repairs=[];unreturned=[];rejected=0
    for i,month in enumerate(months,1):
        start=pd.Timestamp(month+'01');end=min(start+pd.offsets.MonthEnd(0),pd.Timestamp(END))
        from quant.data.sources.tushare import SourceError
        try:r=adapter.fetch(catalog['daily_info'],{'start_date':start.strftime('%Y%m%d'),'end_date':end.strftime('%Y%m%d'),'exchange':'SZ'})
        except SourceError as exc:
            unreturned.append(month)
            if exc.kind in ['permission_denied','rate_limit']:break
            continue
        fresh=pd.DataFrame(r.rows,columns=r.fields)
        if fresh.empty:continue
        assert len(fresh)<4000 and not fresh.duplicated(['ts_code','trade_date']).any()
        assert fresh.trade_date.between(start.strftime('%Y%m%d'),end.strftime('%Y%m%d')).all()
        bydate={day:g.set_index('ts_code') for day,g in fresh.groupby('trade_date')}
        for b in target[target.trade_date.str.startswith(month)].itertuples(index=False):
            day=bydate.get(b.trade_date)
            if day is None:continue
            code='SZ_MARKET' if b.ts_code=='股票' else 'SZ_GEM'
            if code not in day.index:continue
            row=day.loc[code];reference=b._asdict()
            if not compatible(row,reference):rejected+=1;continue
            values={}
            if pd.notna(row.total_share) and pd.notna(row.float_share) and 0<row.float_share<=row.total_share:
                values.update(total_share=(row.total_share*1e8,[code]),float_share=(row.float_share*1e8,[code]))
            if pd.notna(row.vol) and row.vol>=0:values['vol']=(row.vol*1e8,[code])
            elif code=='SZ_MARKET' and {'SZ_MAIN','SZ_GEM'}<=set(day.index) and b.trade_date>='20210406':
                parts=day.loc[['SZ_MAIN','SZ_GEM']]
                # After the SME/main-board merger these two disjoint boards
                # cover total stocks, including B shares in the main board.
                # Three independent totals must reconcile at display precision.
                sums=parts[['amount','total_mv','float_mv']].sum(min_count=2)
                agrees=all(pd.notna(sums[k]) and abs(sums[k]*1e8-reference[f])<=3_000_001
                    for k,f in [('amount','amount'),('total_mv','total_mv'),('float_mv','float_mv')])
                if agrees and parts.vol.notna().all() and parts.vol.ge(0).all():
                    values['vol']=(parts.vol.sum()*1e8,['SZ_MAIN','SZ_GEM'])
            for field,(value,parents) in values.items():
                if pd.notna(reference[field]):continue
                assert np.isfinite(value)
                repairs.append(dict(source_record_id=b.source_record_id,ts_code=b.ts_code,trade_date=b.trade_date,
                    field=field,value=float(value),source_url='https://tushare.pro/document/2?doc_id=215',
                    source_endpoint='daily_info',parent_board_codes=json.dumps(parents),
                    parent_quantities_100m_shares=json.dumps([float(day.loc[p,field]) for p in parents]),
                    formula='sum(parent quantity in 100 million shares)*100000000',
                    reported_quantum_shares=float(len(parents)*1e6),retrieved_at=r.fetched_at,
                    quality='historical_reconstructed_board_quantity',
                    matched_amount_cny=b.amount,matched_total_mv_cny=b.total_mv,matched_float_mv_cny=b.float_mv))
        if i%12==0:print('SZ_QUANTITY_MONTHS',i,'/',len(months),'fields',len(repairs),flush=True)
    if repairs:
        p=pd.DataFrame(repairs);assert not p.duplicated(['source_record_id','field']).any()
        path=ROOT/'data/metadata/szse_quantity_derivations.parquet'
        old=pd.read_parquet(path) if path.exists() else p.iloc[:0]
        frame(path,pd.concat([old,p]).drop_duplicates(['source_record_id','field']))
        for field,g in p.groupby('field'):
            values=g.set_index('source_record_id').value
            mask=base.source_record_id.isin(values.index)
            assert base.loc[mask,field].isna().all()
            base.loc[mask,field]=base.loc[mask,'source_record_id'].map(values)
        base['observation_date']=pd.to_datetime(base.observation_date).dt.date
        for year in sorted(p.trade_date.str[:4].unique()):
            g=base[base.trade_date.str.startswith(year)]
            frame(MARKET/'exchange_activity_sz'/(year+'.parquet'),g.sort_values(['ts_code','trade_date']))
    write(ROOT/'data/metadata/szse_quantity_policy.json',{'source_url':'https://tushare.pro/document/2?doc_id=215',
        'fields_added':len(pd.read_parquet(ROOT/'data/metadata/szse_quantity_derivations.parquet')),'unreturned_months':unreturned,
        'unit':'shares','source_quantity_unit':'100 million shares',
        'admission':'Amount and both capitalization totals agree with canonical category data. Total stock volume after 2021-04-06 is sum of main board (including B) and ChiNext; component totals also reconcile.',
        'precision':'Source board values normally displayed to 0.01 hundred-million shares; derived total uses summed display quanta.',
        'historical_clock':'Use existing same-day reconstructed quote clock; actual new field capture is retained in the compact derivation table.',
        'raw_responses_retained':False})
    c.close();print('SZ_QUANTITIES_ADDED',len(repairs),flush=True)


def complete_parent_lineage():
    """Keep only normalized numeric parents, never original API responses."""
    path=ROOT/'data/metadata/szse_quantity_derivations.parquet';d=pd.read_parquet(path)
    if 'parent_quantities_100m_shares' not in d:d['parent_quantities_100m_shares']=None
    adapter,catalog=client();adapter.settings.max_attempts=1;adapter.settings.timeout_seconds=20
    months=sorted(d.loc[d.parent_quantities_100m_shares.isna(),'trade_date'].str[:6].unique())
    for i,month in enumerate(months,1):
        start=pd.Timestamp(month+'01');end=min(start+pd.offsets.MonthEnd(0),pd.Timestamp(END))
        response=adapter.fetch(catalog['daily_info'],{'start_date':start.strftime('%Y%m%d'),'end_date':end.strftime('%Y%m%d'),'exchange':'SZ'})
        p=pd.DataFrame(response.rows,columns=response.fields).set_index(['trade_date','ts_code'])
        assert p.index.is_unique
        for idx,r in d[d.trade_date.str.startswith(month)&d.parent_quantities_100m_shares.isna()].iterrows():
            values=[float(p.loc[(r.trade_date,code),r['field']]) for code in json.loads(r.parent_board_codes)]
            assert abs(sum(values)*1e8-r.value)<1,(r.trade_date,r.ts_code,r['field'])
            d.at[idx,'parent_quantities_100m_shares']=json.dumps(values)
        if i%12==0:print('SZ_QUANTITY_PARENT_MONTHS',i,'/',len(months),flush=True)
    assert d.parent_quantities_100m_shares.notna().all()
    frame(path,d);print('SZ_PARENT_LINEAGE_COMPLETE',len(d),flush=True)


if __name__=='__main__':build()
