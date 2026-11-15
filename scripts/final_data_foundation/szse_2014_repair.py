"""Restore SZSE 2014 quantities from same-scope historical provider rows."""
from .common import *
from .provider import client


def build():
    path=MARKET/'exchange_activity_sz/2014.parquet';base=pd.read_parquet(path)
    adapter,catalog=client();adapter.settings.max_attempts=2;adapter.settings.timeout_seconds=20
    records=[]
    for month in range(1,13):
        start=pd.Timestamp(2014,month,1);end=start+pd.offsets.MonthEnd(0)
        r=adapter.fetch(catalog['sz_daily_info'],{'start_date':start.strftime('%Y%m%d'),'end_date':end.strftime('%Y%m%d')})
        fresh=pd.DataFrame(r.rows,columns=r.fields)
        assert len(fresh)<1000 and fresh.trade_date.between(start.strftime('%Y%m%d'),end.strftime('%Y%m%d')).all()
        fresh['provider_category']=fresh.ts_code
        fresh.ts_code=fresh.ts_code.replace({'创业板':'创业板A股'})
        assert not fresh.duplicated(['ts_code','trade_date']).any()
        for row in fresh[fresh.ts_code.isin(base.ts_code)].to_dict('records'):
            previous=base[(base.trade_date==row['trade_date'])&(base.ts_code==row['ts_code'])]
            assert len(previous)==1
            prior=previous.iloc[0];position=previous.index[0]
            assert row['count']==prior['count']
            for field in ['amount','total_mv','float_mv']:
                assert pd.notna(row[field]) and abs(row[field]-prior[field])<=1_000_001,(row['ts_code'],row['trade_date'],field)
            for field in ['vol','total_share','float_share']:
                assert pd.notna(row[field]) and row[field]>0
                records.append(dict(ts_code=row['ts_code'],trade_date=row['trade_date'],field=field,
                    value=float(row[field]),previous_value=prior[field],source_record_id=prior.source_record_id,
                    provider_category=row['provider_category'],matched_amount_cny=row['amount'],
                    matched_total_mv_cny=row['total_mv'],matched_float_mv_cny=row['float_mv'],
                    source_url='https://tushare.pro/document/2?doc_id=268',
                    unit='shares',retrieved_at=pd.Timestamp.now(tz='Asia/Shanghai')))
                base.at[position,field]=row[field]
            base.at[position,'quality_reason']='Official historical daily monetary scope independently reconciled to provider sz_daily_info (amount, total/float capitalization within 1 million CNY display quantum, count exact); direct share/volume quantities restored; old 创业板 category normalized to 创业板A股. Historical reconstruction; actual capture in data/metadata/szse_2014_quantity_repairs.parquet.'
        print('SZ2014',month,len(fresh),flush=True)
    evidence=pd.DataFrame(records)
    assert len(evidence)==3675 and not evidence.duplicated(['ts_code','trade_date','field']).any()
    assert base[['vol','total_share','float_share']].notna().all().all()
    assert base.float_share.le(base.total_share).all()
    frame(ROOT/'data/metadata/szse_2014_quantity_repairs.parquet',evidence)
    frame(path,base)
    retire_superseded_derivations(evidence)
    print('SZ2014_DIRECT_FIELDS',len(evidence),flush=True)


def retire_superseded_derivations(evidence):
    # The direct same-scope quantities supersede rounded board-sum parents.
    # Keep one active lineage for each final quantity, not stale alternatives.
    path=ROOT/'data/metadata/szse_quantity_derivations.parquet'
    old=pd.read_parquet(path);keys=['ts_code','trade_date','field']
    covered=pd.MultiIndex.from_frame(evidence[keys])
    keep=~pd.MultiIndex.from_frame(old[keys]).isin(covered)
    frame(path,old[keep])


if __name__=='__main__':build()
