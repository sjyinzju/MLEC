"""Normalize demonstrated 10:1 CDR unit errors, not arbitrary share residuals."""
import numpy as np
from .common import *

EVIDENCE = ROOT/'data/metadata/cdr_unit_repairs.parquet'
URL = 'https://imgweboss.ninebot.com/segway-website/system/202010/28/6532377842d9ba1de8987d679732b436.pdf'


def build():
    c=db()
    b=c.execute("SELECT b.*,d.volume_shares FROM read_parquet(?) b JOIN read_parquet(?) d USING(instrument_id,trade_date) WHERE b.ts_code='689009.SH'",
        [str(MARKET/'stock_daily_basic_observations/*.parquet'),str(MARKET/'stock_daily_observations/*.parquet')]).df()
    records=[]
    # Issuer listing prospectus pp.21/38: one underlying share = ten CDRs.
    # Require both independent cap identities to identify the mixed-unit rows.
    mixed=((b.total_mv/b.close/b.total_share-10).abs()<.0001)&((b.circ_mv/b.close/b.float_share-10).abs()<.0001)
    for idx in b.index[mixed]:
        for field in ['total_share','float_share','free_share']:
            old=b.at[idx,field];new=old*10
            records.append(dict(source_record_id=b.at[idx,'source_record_id'],ts_code='689009.SH',trade_date=b.at[idx,'trade_date'],field=field,old_value=old,value=new,rule='Underlying shares to quoted CDR units: multiply by documented conversion ratio 10'))
            b.at[idx,field]=new
    expected=b.volume_shares/b.free_share/100
    # With shares now in CDR units, repair only the exact residual unit factor.
    # No correction of other free-float denominator disagreements is inferred.
    factor10=(b.turnover_rate_f-expected*10).abs().le(.00011)
    valid=(b.total_mv-b.close*b.total_share).abs().le(b.close*.0101+.001)&(b.circ_mv-b.close*b.float_share).abs().le(b.close*.0101+.001)
    valid &= b.free_share.gt(0)&b.free_share.le(b.float_share)&b.float_share.le(b.total_share)
    for idx in b.index[factor10&valid]:
        records.append(dict(source_record_id=b.at[idx,'source_record_id'],ts_code='689009.SH',trade_date=b.at[idx,'trade_date'],field='turnover_rate_f',old_value=b.at[idx,'turnover_rate_f'],value=expected.at[idx],rule='Actual CDR volume / same-day free CDR quantity * 100; source rate differs by documented factor 10'))
        b.at[idx,'turnover_rate_f']=expected.at[idx]
    if not records:
        c.close();return
    e=pd.DataFrame(records);e['source_url']=URL;e['source_pages']='21,38'
    e['quality']='documented_unit_normalization; historical_reconstructed; original free-float classification not independently certified'
    old=pd.read_parquet(EVIDENCE) if EVIDENCE.exists() else e.iloc[:0]
    frame(EVIDENCE,pd.concat([old,e],ignore_index=True).drop_duplicates(['source_record_id','field']))
    c.register('repaired',b)
    for year in sorted(e.trade_date.str[:4].unique()):
        path=MARKET/'stock_daily_basic_observations'/(year+'.parquet')
        fields=['total_share','float_share','free_share','turnover_rate_f']
        expr=','.join('coalesce(r.'+f+',x.'+f+') AS '+f for f in fields)
        copy_query(c,'SELECT x.* REPLACE('+expr+') FROM read_parquet('+qs(path)+') x LEFT JOIN repaired r USING(source_record_id) ORDER BY x.instrument_id,x.trade_date',path)
    qpath=MARKET/'market_data_quality.parquet';q=pd.read_parquet(qpath)
    resolved=[]
    for field in ['total_mv','circ_mv','turnover_rate','turnover_rate_f']:
        target=b.close*b[{'total_mv':'total_share','circ_mv':'float_share'}.get(field,'free_share')] if field.endswith('_mv') else b.volume_shares/b['float_share' if field=='turnover_rate' else 'free_share']/100
        # Only unmask discrepancies removed by these recorded unit repairs.
        ids=b.loc[(b[field]-target).abs().le(.0001 if not field.endswith('_mv') else np.maximum(.011,b.close*.00005+.00005)),'source_record_id']
        mask=q.ts_code.eq('689009.SH')&q.field.eq(field)&q.quality_status.eq('BLOCKED_UNRESOLVED_SHARE_DENOMINATOR')&q.source_record_id.isin(ids)
        q.loc[mask,'quality_status']='QUALIFIED_DOCUMENTED_CDR_UNIT_REPAIR'
        q.loc[mask,'quality_reason']='Issuer 1:10 CDR conversion resolves mixed underlying-share quantities or factor-ten turnover. Corrected field identity passes tight source rounding; remaining free-float classification remains source-defined.'
        q.loc[mask,'evidence_path']=EVIDENCE.relative_to(ROOT).as_posix()
        resolved.append((field,int(mask.sum())))
    frame(qpath,q);c.close()
    print('CDR_REPAIRED',len(e),'FIELDS; RESOLVED',resolved,flush=True)


if __name__=='__main__':build()
