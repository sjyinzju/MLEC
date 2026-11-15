"""Rebuild the v4 data layer from retained local inputs with networking disabled.

All writes are generated v4 authorities. Byte hashes and exact logical content
checks are reported independently; snapshots are reused by verified hash.
"""
import socket
import time
from .common import *


def aligned_exact_rows(before,after,names):
    """Bounded-memory exact comparison; None requires unordered fallback.

    Matching key order establishes row correspondence. Nulls and NaNs match
    DuckDB set semantics. No numeric tolerance, hashing or sampling is used.
    """
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    a=pq.ParquetFile(before);b=pq.ParquetFile(after)
    if a.metadata.num_rows!=b.metadata.num_rows:return None
    keys=next((k for k in [['instrument_id','trade_date'],['ts_code','trade_date'],['source_record_id'],['sample_id','feature'],['sample_id'],['quality_record_id']] if set(k)<=set(names)),None)
    differences=0
    for x,y in zip(a.iter_batches(batch_size=10000,columns=names),b.iter_batches(batch_size=10000,columns=names)):
        if x.num_rows!=y.num_rows:return None
        if x.equals(y):continue
        if keys is None or any(not x.column(names.index(k)).equals(y.column(names.index(k))) for k in keys):return None
        unequal=pa.array([False]*x.num_rows)
        for i in range(len(names)):
            left,right=x.column(i),y.column(i)
            if left.equals(right):continue
            equal=pc.fill_null(pc.equal(left,right),False)
            equal=pc.or_(equal,pc.and_(pc.is_null(left),pc.is_null(right)))
            if pa.types.is_floating(left.type):equal=pc.or_(equal,pc.fill_null(pc.and_(pc.is_nan(left),pc.is_nan(right)),False))
            unequal=pc.or_(unequal,pc.invert(equal))
        differences+=pc.sum(unequal).as_py()
    return differences


def products():
    folders=[MARKET,MACRO,ROOT/'data/features/market/v4',ROOT/'data/features/macro/v4']
    folders += [ROOT/'data/datasets'/name/'v4' for name in ['feature_sets','sample_manifests','research_base','quality_versions']]
    paths=[p for folder in folders for p in folder.rglob('*') if p.is_file() and p.suffix in ['.parquet','.json']]
    paths += [ROOT/'data/metadata'/name for name in ['research_data_requirements.parquet','dataset_registry.json','schema_registry.json','field_dictionary.parquet','source_registry.parquet','data_lineage.parquet','quality_registry.parquet']]
    paths += [ROOT/'config/data'/name for name in ['market_requirements.json','macro_requirements.json']]
    return sorted(paths)


def rebuild(run_name='final'):
    from . import market,adjudication,market_repairs,stock_identity_views,factor_repairs,factor_actions,deep_market_checks,constituents,market_features,macro,research_inputs,catalogue,market_quality,reconcile,identity_amendment,source_coverage,limit_rules
    assert run_name and all(x.isalnum() or x in '-_' for x in run_name)
    run=AUDIT/'reproducibility'/run_name;snapshot=run/'before';manifest=[];budget()
    code_files=sorted((ROOT/'scripts').rglob('*.py'))
    code_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in code_files}
    code_path=run/'source_code_hashes.json'
    if code_path.exists():
        assert read(code_path)==code_hashes, 'Source changed since checkpoint; use a new run-name and preserve prior evidence'
    else:write(code_path,code_hashes)
    original_snapshot=AUDIT/'reproducibility/before'
    for path in products():
        dest=snapshot/path.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True)
        old=original_snapshot/path.relative_to(ROOT)
        if old.exists() and sha(old)==sha(path):dest=old
        # Preserve an existing baseline for interrupted-run continuation.
        if not dest.exists():
            try:os.link(path,dest)
            except PermissionError:
                if budget()-path.stat().st_size<10_000_000_000:raise RuntimeError('Insufficient budget for offline before-image')
                shutil.copy2(path,dest)
        manifest.append({'path':path.relative_to(ROOT).as_posix(),'before_path':dest.relative_to(ROOT).as_posix(),'before_sha256':sha(dest),'bytes':dest.stat().st_size})
    write(run/'before_manifest.json',manifest)
    original=socket.socket.connect
    def forbidden(*args,**kwargs):raise RuntimeError('Network forbidden during offline data rebuild')
    socket.socket.connect=forbidden
    stages=[('provider_standardization',market.standardize),('security_identity',market.identities),('security_calendar_grid',market.stock_gaps),
      ('official_suspension_adjudication',adjudication.certify_and_apply),('independent_basic_close_repairs',market_repairs.repair_daily_basic),
      ('canonical_security_observations',stock_identity_views.build),('coherent_factor_vintages',factor_repairs.build),('official_factor_action',factor_actions.build),
      ('factor_population_recheck',deep_market_checks.stock_adjustment_checks),('factor_adjudication',factor_actions.classify),('stock_numeric_recheck',reconcile.stock_numeric),
      ('security_code_amendment_verification',identity_amendment.verify),('basic_field_arithmetic',deep_market_checks.basic_arithmetic_checks),('primary_limit_rules',limit_rules.build),('field_quality_exceptions',market_quality.build),('official_constituent_replay',constituents.build),
      ('market_continuous_features',market_features.build),('macro_facts_and_quality',macro.build),('frozen_sample_asof_inputs',research_inputs.build),('secondary_market_coverage',source_coverage.build),('unified_catalogue',catalogue.build)]
    checkpoint=run/'stages.json';done=read(checkpoint) if checkpoint.exists() else []
    try:
        for name,fn in stages:
            if any(r['stage']==name and r['status']=='PASS' for r in done):continue
            started=time.monotonic();print('OFFLINE stage',name,flush=True);fn()
            done.append({'stage':name,'status':'PASS','seconds':time.monotonic()-started});write(checkpoint,done)
    finally:socket.socket.connect=original
    assert code_hashes=={p.relative_to(ROOT).as_posix():sha(p) for p in code_files}, 'Source changed during rebuild'
    compare(run)


def compare(run=None):
    run=run or AUDIT/'reproducibility';manifest=read(run/'before_manifest.json');c=db();results=[]
    for r in manifest:
        path=ROOT/r['path'];before=ROOT/r['before_path'] if 'before_path' in r else run/'before'/r['path'];after_hash=sha(path)
        status='BYTE_IDENTICAL';detail=None
        if after_hash!=r['before_sha256']:
            if path.suffix=='.json':
                status='LOGICALLY_IDENTICAL' if read(path)==read(before) else 'DIFFERENT'
            else:
                a='read_parquet('+qs(before)+')';b='read_parquet('+qs(path)+')'
                cols=c.execute('DESCRIBE SELECT * FROM '+a).df();new=c.execute('DESCRIBE SELECT * FROM '+b).df()
                if dict(zip(cols.column_name,cols.column_type))!=dict(zip(new.column_name,new.column_type)):status='SCHEMA_DIFFERENT'
                else:
                    # Ordering/compression differ without changing logical rows.
                    names=','.join('"'+x+'"' for x in cols.column_name)
                    difference=aligned_exact_rows(before,path,cols.column_name.tolist());method='key_aligned_all_fields_stream'
                    if difference is None:
                        method='unordered_exact_multiset'
                        difference=c.execute('SELECT count(*) FROM ((SELECT '+names+' FROM '+a+' EXCEPT ALL SELECT '+names+' FROM '+b+') UNION ALL (SELECT '+names+' FROM '+b+' EXCEPT ALL SELECT '+names+' FROM '+a+'))').fetchone()[0]
                    status='LOGICALLY_IDENTICAL' if difference==0 else 'DIFFERENT';detail={'exact_different_rows':difference,'method':method}
        results.append({**r,'after_sha256':after_hash,'status':status,'detail':detail})
        if len(results)%25==0:print('OFFLINE compared',len(results),'/',len(manifest),flush=True)
    c.close();write(run/'product_comparison.json',results)
    failures=[r['path'] for r in results if r['status'] not in ['BYTE_IDENTICAL','LOGICALLY_IDENTICAL']]
    result={'status':'FAIL' if failures else 'PASS','products':len(results),'network_disabled_during_rebuild':True,
      'external_database_required_for_rebuild':False,'source_inputs':'Retained local raw snapshots, immutable v3 macro parent and frozen v2 sample IDs; no re-download.',
      'stages':read(run/'stages.json'),'different_products':failures,'comparisons':(run/'product_comparison.json').relative_to(ROOT).as_posix(),
      'data_status':'Reproduction does not certify unresolved source completeness or first-vintage availability.'}
    write(run/'offline_rebuild_result.json',result)
    if run!=AUDIT/'reproducibility':write(AUDIT/'reproducibility/offline_rebuild_result.json',result)
    print('OFFLINE comparison',len(results),'products;',len(failures),'different',flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--run-name',default='final');rebuild(parser.parse_args().run_name)
