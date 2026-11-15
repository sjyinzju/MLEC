"""Resolve CSI1000 provider conflicts using the index administrator's quotes."""
from .common import *


def build():
    path=ROOT/'data/metadata/index_price_conflicts.parquet';conflicts=pd.read_parquet(path)
    qpath=MARKET/'market_data_quality.parquet';quality=pd.read_parquet(qpath)
    for i,row in conflicts.iterrows():
        proof=ROOT/f'data/metadata/csi1000_official_{row.trade_date}.parquet'
        official=pd.read_parquet(proof)
        assert len(official)==1 and official.iloc[0].tradeDate==row.trade_date and official.iloc[0].indexCode=='000852'
        for field in ['open','high','low','close']:
            assert abs(row[field]-official.iloc[0][field])<=.00501
        conflicts.at[i,'price_resolution']='PRIMARY_CONFIRMED_BY_INDEX_ADMINISTRATOR'
        conflicts.at[i,'review_status']='CLOSED_OFFICIAL_ADJUDICATION'
        conflicts.at[i,'independent_evidence']=proof.relative_to(ROOT).as_posix()
        mask=quality.source_record_id.eq(row.source_record_id)&quality.quality_status.eq('BLOCKED_UNRESOLVED_CROSS_SOURCE_CONFLICT')
        quality.loc[mask,'quality_status']='ACCEPTED_PRIMARY_CONFIRMED_OFFICIAL'
        quality.loc[mask,'quality_reason']='CSI official index-perf confirms primary OHLC within 0.01-point publication rounding. Conflicting Tencent values rejected; primary higher-precision observations retained.'
        quality.loc[mask,'evidence_path']=proof.relative_to(ROOT).as_posix()
    frame(path,conflicts);frame(qpath,quality)
    from .market_features import index_dimensions
    index_dimensions()
    print('CSI1000_CONFLICT_FIELDS_CLOSED',3,flush=True)


if __name__=='__main__':build()
