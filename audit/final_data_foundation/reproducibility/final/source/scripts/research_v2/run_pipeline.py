"""Unified offline entry point; no model fitting, financial downloads, or source writes."""
import os
for var in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']:
    os.environ[var]='1'
os.environ['PYTHONDONTWRITEBYTECODE']='1'
import argparse
import sys
from pathlib import Path
import pandas as pd
from common import *
from core import *

def code_signature(names):return objhash({n:filehash(Path(__file__).parent/n) for n in names})
def checkpoint_valid(name,signature):
    path=AUDIT/f'checkpoint_{name}.json'
    if not path.exists():return False
    checkpoint=readjson(path)
    return checkpoint['signature']==signature and all(Path(p).exists() and filehash(p)==h for p,h in checkpoint['outputs'].items())
def checkpoint(name,signature,paths):
    jsonwrite(AUDIT/f'checkpoint_{name}.json',{'signature':signature,'outputs':{str(p):filehash(p) for p in paths},'completed_at':pd.Timestamp.now(tz=TZ).isoformat()})

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage',choices=['core','extensions','validate','reports','all'],default='all');ap.add_argument('--force',action='store_true');args=ap.parse_args()
    budget();cfg=freeze();sv=readjson(AUDIT/'source_version.json')
    signature=objhash([cfg,sv,code_signature(['common.py','core.py','run_pipeline.py'])])
    core_outputs=[DATA/f'{x}.parquet' for x in ['market_daily_clean','market_observations_daily','state_labels_daily','risk_episodes','market_features_weekly','future_outcomes_weekly','prediction_targets_weekly','sample_to_event','fold_membership']]+[CONFIG/'thresholds.json',CONFIG/'feature_whitelist.json',CONFIG/'time_splits.json',AUDIT/'fold_manifest.parquet',AUDIT/'sse_calendar.parquet']
    if args.stage not in ['all','core'] and not checkpoint_valid('core',signature):
        raise RuntimeError('Core checkpoint missing or stale. Run --stage core or --stage all first; dependent stages cannot read partially replaced outputs.')
    if args.stage in ['core','all']:
        if not args.force and checkpoint_valid('core',signature):log('core_checkpoint_reused')
        else:
            log('core_start',budget=budget());clean,cal=read_index();obs=observations(clean)
            saveframe(DATA/'market_observations_daily.parquet',obs)
            thr=thresholds(obs);jsonwrite(CONFIG/'thresholds.json',thr)
            state,ep=all_events(obs,states(obs,thr))
            features,outcomes,targets,mapping=build_weekly(obs,state,ep,cal,thr)
            ep=event_opportunities(ep,features,targets,mapping,obs.date)
            plan,membership=temporal_folds(features,targets,cal)
            for name,df in [('state_labels_daily',state),('risk_episodes',ep),('market_features_weekly',features),('future_outcomes_weekly',outcomes),('prediction_targets_weekly',targets),('sample_to_event',mapping),('fold_membership',membership)]:saveframe(DATA/f'{name}.parquet',df)
            saveframe(AUDIT/'fold_manifest.parquet',plan);whitelist()
            jsonwrite(CONFIG/'time_splits.json',{'initial_reference_train':['2015-01-01','2019-12-31'],'development':['2020-01-01','2022-12-31'],'heldout':['2023-01-01','local_latest_complete_week'],'fold_manifest':'audit/research_v2/fold_manifest.parquet','cutoff_rule':PROTOCOL['final_update'],'no_internal_reference_period_evaluation':True})
            checkpoint('core',signature,core_outputs)
            log('core_complete',daily=len(obs),weekly_candidates=len(features),thresholds=thr)
    if args.stage in ['extensions','all']:
        from extensions import run_extensions
        ext_paths=[DATA/'stock_market_proxies_daily.parquet',AUDIT/'stock_certification_daily.parquet',AUDIT/'dimension_availability.json',AUDIT/'stock_scope_certification.json',CONFIG/'proxy_thresholds.json']+[DATA/f'stock_proxy_inputs/{year}.parquet' for year in range(2015,2027)]
        ext_sig=objhash([sv,code_signature(['common.py','extensions.py']),PROTOCOL,[str(p) for p in ext_paths]])
        if not args.force and checkpoint_valid('extensions',ext_sig):log('extensions_checkpoint_reused')
        else:run_extensions();checkpoint('extensions',ext_sig,ext_paths)
        # Never invalidate the cached core feature artifact: optional extensions have their own joined file.
        f=pd.read_parquet(DATA/'market_features_weekly.parquet');proxy=pd.read_parquet(DATA/'stock_market_proxies_daily.parquet')
        joined=f.merge(proxy.rename(columns={'date':'asof_date'}),on='asof_date',how='left',validate='one_to_one')
        for col in OPTIONAL_FEATURES:joined['missing__'+col]=joined[col].isna()
        saveframe(DATA/'market_features_weekly_with_proxies.parquet',joined)
        obs=pd.read_parquet(DATA/'market_observations_daily.parquet')
        state=pd.read_parquet(DATA/'state_labels_daily.parquet')
        ref=obs.loc[obs.date.le('2019-12-31'),'amount_ratio_5_20'].dropna()
        activity_q=float(np.quantile(ref,PROTOCOL['activity_low_quantile'],method='linear'))
        dims=state[['date','V','D','state_id','raw_stress','valid_state','threshold_version']].merge(proxy[['date','high_down_fraction_proxy','high_mean_corr_60d_proxy','high_amihud_20d_proxy']],on='date',validate='one_to_one')
        dims['low_activity']=(obs.amount_ratio_5_20<activity_q).where(obs.amount_ratio_5_20.notna()).astype('Int8')
        dims['trend_60d_continuous']=obs.ret_60d
        dims['activity_label_meaning']='low trading activity, not liquidity crisis'
        dims['proxy_label_status']='observed stock sample PROXY; excluded from main stress'
        saveframe(DATA/'dimension_labels_daily.parquet',dims)
        jsonwrite(CONFIG/'dimension_label_specs.json',{'volatility':'V: vol_20d>frozen qV','downside':'D: mdd_20d>frozen qD','trend':'ret_60d continuous; no bull/bear/sideways classes','activity':{'quantile':PROTOCOL['activity_low_quantile'],'threshold':activity_q,'reference_n':len(ref),'operator':'<','meaning':'low activity, not liquidity crisis'},'structure_liquidity':'separate high proxy flags based on reference q80; not main pressure','missing_label':'NA, never no risk'})
    if args.stage in ['validate','all']:
        from validation import run_validation
        run_validation()
    if args.stage in ['reports','all']:
        from reports import build_reports
        build_reports()
    st=(SOURCE/'quant.duckdb').stat();original=readjson(AUDIT/'source_manifest.json')['database_stat']
    assert st.st_size==original['bytes'] and st.st_mtime_ns==original['mtime_ns'],'Source registry changed during run'
    jsonwrite(AUDIT/'output_hashes.json',{str(p.relative_to(BASE)):filehash(p) for root in [DATA,CONFIG] for p in root.rglob('*') if p.is_file()})
    log('run_complete',selected_stage=args.stage,source_registry_unchanged=True,budget=budget())

if __name__=='__main__':
    try:main()
    except Exception as e:
        log('FAILED',error=repr(e));raise
