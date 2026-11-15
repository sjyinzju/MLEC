"""Replace mixed-vintage factor histories with coherent retained API snapshots."""
from .common import *
from .provider import API_RAW


def refresh_parent_snapshot(c):
    """Keep a pre-action backup synchronized when refreshing an existing table."""
    c.execute('UPDATE base SET provider_refreshed_adj_factor=f.adj_factor FROM fresh f WHERE base.ts_code=f.ts_code AND base.trade_date=f.trade_date')


def build():
    codes=read(AUDIT/'issue_closure/factor_refresh_targets.json')['codes'];frames=[];receipts=[]
    for p in (API_RAW/'requests').glob('*.json'):
        r=read(p)
        if r['endpoint']!='adj_factor' or r['status']!='ok' or r['params'].get('ts_code') not in codes or r['params'].get('end_date')!=END or r['params'].get('start_date')!=START:continue
        assert sha(ROOT/r['path'])==r['sha256']
        obj=read(ROOT/r['path']);d=pd.DataFrame(obj['items'],columns=obj['fields']);assert len(d)<5000 and not d.duplicated(['ts_code','trade_date']).any()
        d['new_record_id']='tushare:adj_factor:'+r['sha256']+':'+d.ts_code+':'+d.trade_date
        d['new_vintage']=r['sha256'];d['new_retrieved']=pd.Timestamp(r['retrieved_at']);d['new_evidence']=r['path'];frames.append(d);receipts.append(r)
    fresh=pd.concat(frames);assert set(fresh.ts_code)==set(codes)
    c=db();c.register('fresh',fresh);summ=[]
    for year in range(2014,2027):
        path=MARKET/'stock_adjustment_observations'/f'{year}.parquet'
        # Materialize before atomic replacement to release Windows file handles.
        c.execute('CREATE OR REPLACE TEMP TABLE base AS SELECT * FROM read_parquet(?)',[str(path)])
        fields={x[0] for x in c.execute('DESCRIBE base').fetchall()}
        if 'provider_refreshed_adj_factor' in fields:refresh_parent_snapshot(c)
        if 'provider_adj_factor' not in fields:c.execute('ALTER TABLE base ADD COLUMN provider_adj_factor DOUBLE');c.execute('UPDATE base SET provider_adj_factor=adj_factor')
        if 'factor_parent_record_id' not in fields:c.execute('ALTER TABLE base ADD COLUMN factor_parent_record_id VARCHAR');c.execute('UPDATE base SET factor_parent_record_id=source_record_id')
        if 'factor_evidence_path' not in fields:c.execute('ALTER TABLE base ADD COLUMN factor_evidence_path VARCHAR')
        q="""SELECT d.* EXCLUDE(adj_factor,source_record_id,retrieved_at,research_available_at,vintage_id,quality_reason,factor_evidence_path),
          coalesce(f.adj_factor,d.adj_factor) adj_factor,coalesce(f.new_record_id,d.source_record_id) source_record_id,
          coalesce(f.new_retrieved,d.retrieved_at) retrieved_at,coalesce(f.new_retrieved,d.research_available_at) research_available_at,
          coalesce(f.new_vintage,d.vintage_id) vintage_id,coalesce(f.new_evidence,d.factor_evidence_path) factor_evidence_path,
          CASE WHEN f.new_record_id IS NULL THEN d.quality_reason ELSE 'Coherent API historical factor snapshot replacing mixed-vintage discontinuities. Provider original retained; retrieval-only availability; corporate-action residuals audited separately.' END quality_reason
          FROM base d LEFT JOIN fresh f USING(ts_code,trade_date) ORDER BY instrument_id,trade_date"""
        count=c.execute('SELECT count(*) FROM base d JOIN fresh f USING(ts_code,trade_date) WHERE abs(d.provider_adj_factor-f.adj_factor)>1e-10').fetchone()[0]
        copy_query(c,q,path);summ.append({'year':year,'changed_factor_values':count})
    write(AUDIT/'issue_closure/factor_repairs.json',{'source_codes':codes,'years':summ,'total_changed_values':sum(x['changed_factor_values'] for x in summ),
       'source_receipts':receipts,'reason':'Direct API re-observation demonstrated nonconstant historical scale changes in the mixed-vintage source, including non-corporate-action year boundaries. No arbitrary factor rescaling; provider raw snapshots preserved.',
       'status':'REQUIRES_POST_REPAIR_POPULATION_RECHECK'})
    c.close();print('Factors repaired',sum(x['changed_factor_values'] for x in summ),flush=True)


if __name__=='__main__':build()
