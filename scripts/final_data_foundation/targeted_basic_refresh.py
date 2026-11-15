"""Refresh only actual missing basic fields; discard API payloads in memory."""
import numpy as np
from .common import *


def build():
    from .provider import client
    adapter,catalog = client()
    adapter.settings.max_attempts = 1
    adapter.settings.timeout_seconds = 20
    from quant.data.sources.tushare import SourceError
    quality = pd.read_parquet(MARKET/'market_data_quality.parquet')
    gaps = quality[quality.quality_status.eq('BLOCKED_MISSING_REQUIRED_FIELD')].copy()
    c=db();c.register('gaps',gaps)
    base=c.execute('''SELECT DISTINCT b.source_record_id,b.ts_code,b.trade_date,b.close
      FROM read_parquet(?) b JOIN gaps g USING(source_record_id)''',
      [str(MARKET/'stock_daily_basic_observations/*.parquet')]).df()
    repairs=[];failures={};returned=0
    for i,(code,group) in enumerate(gaps.groupby('ts_code'),1):
        try:
            response=adapter.fetch(catalog['daily_basic'],{'ts_code':code,
                'start_date':group.trade_date.min(),'end_date':group.trade_date.max()})
        except SourceError as exc:
            failures[exc.kind]=failures.get(exc.kind,0)+1
            if exc.kind in ['permission_denied','rate_limit']:break
            continue
        d=pd.DataFrame(response.rows,columns=response.fields)
        if d.empty:continue
        assert len(d)<6000 and d.ts_code.eq(code).all() and not d.duplicated(['ts_code','trade_date']).any()
        returned+=len(d)
        parents=base[base.ts_code.eq(code)].set_index('trade_date')
        rows=d.set_index('trade_date')
        for g in group.itertuples(index=False):
            if g.trade_date not in rows.index:continue
            row=rows.loc[g.trade_date];old=parents.loc[g.trade_date]
            if pd.isna(old.close) or pd.isna(row['close']) or abs(float(row['close'])-old.close)>1e-5:continue
            value=row.get(g.field)
            if pd.isna(value) or not np.isfinite(float(value)):continue
            if g.field!='pb' and value<0:continue
            repairs.append(dict(source_record_id=g.source_record_id,quality_record_id=g.quality_record_id,
                ts_code=code,trade_date=g.trade_date,field=g.field,value=float(value),
                source_url='https://api.tushare.pro',retrieved_at=response.fetched_at,
                quality='historical_reconstructed_provider_refresh'))
        if i%25==0:print('BASIC_TARGETED',i,'/',gaps.ts_code.nunique(),'new fields',len(repairs),flush=True)
    if repairs:
        repaired=pd.DataFrame(repairs);assert not repaired.duplicated(['source_record_id','field']).any()
        path=ROOT/'data/metadata/basic_field_refreshes.parquet'
        old=pd.read_parquet(path) if path.exists() else repaired.iloc[:0]
        frame(path,pd.concat([old,repaired]).drop_duplicates(['source_record_id','field']))
        for year,group in repaired.groupby(repaired.trade_date.str[:4]):
            table=MARKET/'stock_daily_basic_observations'/(year+'.parquet')
            c.execute('CREATE OR REPLACE TEMP TABLE base AS SELECT * FROM read_parquet(?)',[str(table)])
            for field,patch in group.groupby('field'):
                assert field in ['pb','total_mv','circ_mv','turnover_rate_f']
                c.register('patch',patch)
                c.execute(f'UPDATE base SET {field}=p.value FROM patch p WHERE base.source_record_id=p.source_record_id AND base.{field} IS NULL')
            copy_query(c,'SELECT * FROM base ORDER BY instrument_id,trade_date',table)
        mask=quality.quality_record_id.isin(repaired.quality_record_id)
        quality.loc[mask,'quality_status']='REFRESHED_HISTORICAL_PROVIDER_VALUE'
        quality.loc[mask,'quality_reason']='Previously missing field returned on targeted provider reread; same-day close matches canonical quote. Historical reconstruction, not original vintage.'
        quality.loc[mask,'evidence_path']=path.relative_to(ROOT).as_posix()
        frame(MARKET/'market_data_quality.parquet',quality)
    write(ROOT/'data/metadata/basic_refresh_summary.json',{'target_securities':gaps.ts_code.nunique(),
        'returned_rows_inspected':returned,'filled_fields':len(repairs),'failure_counts':failures,
        'raw_responses_retained':False,'scope':'Only missing fields; existing correct values unchanged'})
    c.close();print('BASIC_REFRESH_DONE',len(repairs),failures,flush=True)


if __name__=='__main__':build()
