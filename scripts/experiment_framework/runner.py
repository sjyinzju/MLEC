import importlib.metadata
import joblib
import numpy as np
import pandas as pd
from .common import ROOT,digest,identity,read_json,save_frame,write_json,write_text
from .dataset import load_dataset,authority_hashes
from .models import select_model,logits,RiskModel
from .evaluation import probability_metrics,reliability,choose_threshold,event_evaluate,paired_compare,block_interval

def benchmark(config_path=ROOT/'config/experiments/development.json'):
    cfg=read_json(config_path)
    if cfg['stage']!='development' or cfg['final_evaluation_enabled']:raise ValueError('Final evaluation locked')
    registry=read_json(ROOT/'config/experiments/feature_sets.json')
    versions={n:importlib.metadata.version(n) for n in ['numpy','pandas','pyarrow','scikit-learn','joblib']}
    source_hashes={str(p.relative_to(ROOT)):digest(p) for base in ['scripts/experiment_framework','scripts/final_data_foundation','scripts/data_foundation_v3'] for p in sorted((ROOT/base).glob('*.py'))}
    data_hashes={quality:authority_hashes(quality) for quality in sorted({registry[f]['quality_version'] for f in cfg['feature_sets']})}
    run_id='dev-'+identity([cfg,read_json(ROOT/'data/metadata/dataset_registry.json'),registry,data_hashes,source_hashes,versions])[:16]
    modeldir=ROOT/'artifacts/models'/run_id;modeldir.mkdir(parents=True,exist_ok=True)
    predictions=[];selections=[];blocked=[];interpret=[]
    tasks=set()
    for feature in cfg['feature_sets']:
        if registry[feature]['status']!='eligible':
            blocked.append({'feature_set':feature,'reason':registry[feature]['reason']});continue
        sample_version=registry[feature]['sample_version']
        tasks.add((feature,sample_version));tasks.add(('M',sample_version))
    for feature,sample_version in sorted(tasks):
        for algorithm,grid in cfg['algorithms'].items():
            for fold in cfg['folds']:
                train=load_dataset(sample_version,feature,cfg['horizon'],fold,'train')
                valid=load_dataset(sample_version,feature,cfg['horizon'],fold,'validation')
                if train.y.empty or valid.y.empty:
                    blocked.append({'feature_set':feature,'sample_version':sample_version,'fold':fold,
                        'reason':'No eligible paired train/validation sample under the authoritative v5 mask'})
                    continue
                model,cal,selection,params=select_model(algorithm,grid,train,cfg['seed'])
                p=model.predict_proba(valid.X);pc=cal.predict_proba(logits(p))[:,1] if cal is not None else p.copy()
                name=f'{algorithm}__{feature}__{sample_version.replace(":","_")}__{fold}';path=modeldir/(name+'.joblib')
                model.save(path);joblib.dump(cal,modeldir/(name+'__calibration.joblib'))
                np.testing.assert_allclose(RiskModel.load(path).predict_proba(valid.X),p,rtol=0,atol=0)
                interpretation=model.interpretation();interpretation['model']=name;interpret.append(interpretation)
                selections.append({'model':name,'best_params':params,'inner_evidence':selection,'n_train':len(train.y),'n_validation':len(valid.y),'fit_cutoff':train.fold_metadata['fit_cutoff'],'model_hash':digest(path),'training_sample_ids':train.metadata.sample_id.tolist()})
                result=valid.metadata[['sample_id','asof_time']].copy()
                result=result.assign(run_id=run_id,algorithm_id=algorithm,feature_set_id=feature,sample_version=sample_version,horizon=cfg['horizon'],fold_id=fold,fit_cutoff=train.fold_metadata['fit_cutoff'],y_true=valid.y.to_numpy(),predicted_probability=p,calibrated_probability=pc,calibration_version='sigmoid-inner-oof-v1' if cal is not None else 'none',model_version='risk-model-v1',feature_version=train.hashes['feature'],protocol_hash=train.hashes['protocol'],seed=cfg['seed'])
                predictions.append(result);print(name,len(train.y),len(valid.y),flush=True)
    if not predictions:raise ValueError('No eligible development selections; inspect v5 sample masks')
    p=pd.concat(predictions,ignore_index=True)
    assert not p.duplicated(['algorithm_id','feature_set_id','sample_version','sample_id','fold_id','horizon']).any()
    predpath=ROOT/f'experiments/predictions/{run_id}.parquet'
    if predpath.exists():
        pd.testing.assert_frame_equal(pd.read_parquet(predpath),p,check_exact=True)
    save_frame(predpath,p)
    save_frame(ROOT/f'experiments/metrics/{run_id}_interpretation.parquet',pd.concat(interpret,ignore_index=True))
    write_json(ROOT/f'experiments/registry/{run_id}.json',{'run_id':run_id,'config':cfg,'config_hash':identity(cfg),'dependencies':versions,'source_hashes':source_hashes,'data_authority_hashes':data_hashes,'dataset_registry':read_json(ROOT/'data/metadata/dataset_registry.json'),'feature_registry':registry,'selection':selections,'blocked':blocked,'prediction_sha256':digest(predpath),'final_test_used':False})
    write_json(ROOT/'experiments/registry/latest.json',{'run_id':run_id})
    return evaluate(run_id)

def evaluate(run_id=None):
    run_id=run_id or read_json(ROOT/'experiments/registry/latest.json')['run_id']
    run=read_json(ROOT/f'experiments/registry/{run_id}.json');cfg=run['config']
    p=pd.read_parquet(ROOT/f'experiments/predictions/{run_id}.parquet')
    assert p.asof_time.dt.year.between(2020,2022).all()
    ep=pd.read_parquet(ROOT/'data/research_v2/risk_episodes.parquet')
    mapping=pd.read_parquet(ROOT/'data/research_v2/sample_to_event.parquet')
    summaries=[];events=[];reliabilities=[];thresholds={}
    for (algorithm,feature,sample_version),d in p.groupby(['algorithm_id','feature_set_id','sample_version']):
        d=d.sort_values('asof_time');score=probability_metrics(d.y_true,d.predicted_probability)
        score.update(algorithm=algorithm,feature_set=feature,sample_version=sample_version,calibrated_brier=probability_metrics(d.y_true,d.calibrated_probability)['brier'])
        interval=block_interval((d.y_true-d.predicted_probability)**2,d.asof_time,cfg['bootstrap_block_weeks'],cfg['bootstrap_repetitions'],cfg['seed'])
        score.update(brier_lower=interval['lower'],brier_upper=interval['upper'])
        threshold=choose_threshold(d,cfg['false_alarms_per_calendar_year']);thresholds[algorithm+'__'+feature+'__'+sample_version]=threshold
        event,evscore=event_evaluate(d,ep,mapping,threshold);score.update(evscore);summaries.append(score)
        event['algorithm']=algorithm;event['feature_set']=feature;event['sample_version']=sample_version;events.append(event)
        rel=reliability(d.y_true.to_numpy(),d.predicted_probability.to_numpy());rel['algorithm']=algorithm;rel['feature_set']=feature;rel['sample_version']=sample_version;reliabilities.append(rel)
    comparisons=[];ablations=[]
    for (algorithm,sample_version),group in p.groupby(['algorithm_id','sample_version']):
        for feature,z in group.groupby('feature_set_id'):
            if feature=='M':continue
            differences,ci=paired_compare(group[group.feature_set_id=='M'],z,block_weeks=cfg['bootstrap_block_weeks'],repetitions=cfg['bootstrap_repetitions'],seed=cfg['seed'])
            save_frame(ROOT/f'experiments/metrics/{run_id}_{algorithm}_{feature}_paired.parquet',differences)
            comparisons.append({'algorithm':algorithm,'feature_set':feature,'sample_version':sample_version,'delta_brier':ci})
            if feature.startswith('M_plus_Z_core_without_'):
                full=group[group.feature_set_id=='M_plus_Z_core']
                if len(full):
                    loss,interval=paired_compare(z,full,block_weeks=cfg['bootstrap_block_weeks'],repetitions=cfg['bootstrap_repetitions'],seed=cfg['seed'])
                    save_frame(ROOT/f'experiments/metrics/{run_id}_{algorithm}_{feature}_ablation.parquet',loss)
                    ablations.append({'algorithm':algorithm,'removed_group':feature.removeprefix('M_plus_Z_core_without_'),'sample_version':sample_version,**interval})
    write_json(ROOT/f'experiments/metrics/{run_id}.json',{'probability_and_events':summaries,'paired':comparisons,'ablations':ablations,'macro_comparison_status':'blocked' if not comparisons else 'development_only'})
    write_text(ROOT/'reports/benchmark/core_ablations.md','# Core leave-one-group-out results\n\n'+(pd.DataFrame(ablations).to_markdown(index=False) if ablations else 'No accepted ablation predictions.')+'\n\nSame core sample IDs, labels and folds. Difference = loss without the group minus loss with the full core; positive values favor retaining that group. These are development-only exploratory comparisons, not causal effects.\n')
    save_frame(ROOT/f'experiments/metrics/{run_id}_events.parquet',pd.concat(events,ignore_index=True))
    save_frame(ROOT/f'experiments/metrics/{run_id}_reliability.parquet',pd.concat(reliabilities,ignore_index=True))
    write_json(ROOT/'config/experiments/development_thresholds.json',{'run_id':run_id,'thresholds':thresholds,'selected_on':'development_2020_2022','locked_for_future':True})
    table=pd.DataFrame(summaries)[['algorithm','feature_set','sample_version','n','brier','log_loss','roc_auc','pr_auc','calibrated_brier','brier_lower','brier_upper','eligible_events','detected_events','lead_mean']].to_markdown(index=False)
    paired_table=pd.DataFrame([{'algorithm':r['algorithm'],'feature_set':r['feature_set'],'sample_version':r['sample_version'],**r['delta_brier']} for r in comparisons]).to_markdown(index=False) if comparisons else 'No eligible paired macro comparisons.'
    write_text(ROOT/'reports/benchmark/development_results.md','# Development results\n\nRun `'+run_id+'`. Genuine annual expanding-window OOF predictions; 2023+ not evaluated.\n\n'+table+'\n\n## Paired Brier improvement (M minus M+Z)\n\n'+paired_table+'\n\nCompare only identical sample versions. Positive differences favor macro inputs. These development comparisons do not establish final out-of-time incremental value; multiple feature-set comparisons are exploratory. Source timing and historical-reconstruction quality follow each registered v5 quality view; no complete original-vintage certification is claimed.\n')
    write_text(ROOT/'reports/benchmark/probability_evaluation.md','# Probability evaluation\n\n'+table+'\n\nPrimary metric: native probability Brier. Calibrated Brier is a separately reported diagnostic. 95% intervals use 8-calendar-week moving blocks, 500 replicates, seed 3059. Small event counts limit inference. PR-AUC is average precision. Reliability bins and per-sample probabilities are in experiments/.\n')
    write_text(ROOT/'reports/benchmark/event_warning_evaluation.md','# Event warning evaluation\n\n'+pd.DataFrame(summaries)[['algorithm','feature_set','sample_version','events','eligible_events','detected_events','threshold','annual_false_alarm_weeks','repeated_alarms','lead_mean','event_wilson_lower','event_wilson_upper']].to_markdown(index=False)+'\n\nThreshold maximizes true alarm weeks subject to at most 2 false alarm weeks in EACH development calendar year; ties prefer fewer false alarms then higher threshold. This operating point is selected on development and optimistic, not independent validation. Events are deduplicated; only scored pre-onset opportunities count. No-opportunity events remain in the event table. Lead is to frozen trigger, not crash beginning. Drawdown at alarm is recorded. Wilson intervals use unique events and are descriptive under dependence.\n')
    return {'run_id':run_id,'predictions':len(p),'summaries':summaries,'blocked':run['blocked']}
