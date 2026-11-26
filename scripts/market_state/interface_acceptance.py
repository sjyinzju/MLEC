"""Full sealed-task interface acceptance. Transformations only; no estimators."""
from pathlib import Path
import json
import tempfile
import numpy as np
import pandas as pd
from .common import ROOT,OUT,REPORT,MARKETS,write
from .framework import DataStore,load_dataset,information_view,target_view
from .model_contract import (CONTRACT_VERSION,fit_inputs,restrict_inputs,transform_inputs,validate_pair,
    validate_probabilities,truth_hash,key_hash,ROUNDTRIP_ATOL,ROUNDTRIP_RTOL,prediction_schema)
from .target_adapters import fit_targets,TargetAdapter,evaluation_scale
from .preprocessing import FoldPreprocessor
from .release import assert_sealed_products,file_hash,code_hash
from .tasks import task_matrix
from .z_star_release import CORE_INFORMATION_SETS, ENHANCED, EXTENSION, validate_extension

DEST=REPORT/'model_io'

def render_contract_table(schema):
    """Generate documentation from the same schema used by adapters and validators."""
    rows=['| 指标 | 经济维度 | 原单位 |','|---|---|---|']
    rows += ['| '+r['field']+' | '+r['dimension']+' | '+r['unit']+' |' for r in schema['continuous']]
    p=ROOT/'docs/model_io_contract.md';text=p.read_text(encoding='utf8')
    start='<!-- generated-target-table:start -->';end='<!-- generated-target-table:end -->'
    a=text.index(start)+len(start);b=text.index(end,a)
    p.write_text(text[:a]+'\n'+'\n'.join(rows)+'\n'+text[b:],encoding='utf8')


def interface_preflight(*,data_root=None,receipt_dir=None,feature_extension=None):
    if data_root is not None and receipt_dir is None:
        raise ValueError('A separate receipt directory is required when using a relocated data root')
    store=DataStore(data_root,feature_extension=feature_extension)
    destination=Path(receipt_dir).resolve() if receipt_dir is not None else _receipt_directory(feature_extension)
    if destination.is_relative_to(store.root):raise ValueError('Receipt directory must be outside the sealed data')
    destination.mkdir(parents=True,exist_ok=True)
    seal_path=store.root/'release/seal.json'
    seal=json.loads(seal_path.read_text(encoding='utf8'))
    before=seal['products'];seal_hash=file_hash(seal_path);start_code_hash=code_hash()
    infos=CORE_INFORMATION_SETS if feature_extension else store.spec['sets']
    tasks=task_matrix(infos,store.get('time_splits')) if feature_extension else store.get('data_tasks')
    records=[];prediction_records=[];schema_records=[]
    schema=store.target_schema()
    write(destination/'target_schema.json',schema)
    if destination==DEST:render_contract_table(schema)
    write(destination/'output_schemas.json',{t:prediction_schema(t,schema) for t in ['classification','regression']})
    write(destination/'evaluation_scales.json',{m:evaluation_scale(market_id=m,store=store) for m in MARKETS})
    with tempfile.TemporaryDirectory(prefix='mlec-interface-') as tmp:
        tmp=Path(tmp)
        for (market,fold),group in tasks.groupby(['market_id','fold_id'],sort=False):
            data={}
            roles=group.role.unique()
            kwargs=dict(market_id=market,task='regression',fold_id=fold,store=store)
            for role in roles:
                d=load_dataset(**kwargs,information_set='M+Z',role=role)
                data[role,'regression']=d
                for task in ['classification','probability']:data[role,task]=target_view(d,task,store=store)
            full=data['train','regression'];pre=fit_inputs(full)
            adapters={task:fit_targets(data['train',task]) for task in ['classification','regression']}
            pre.save(tmp/'inputs');loaded=FoldPreprocessor.load(tmp/'inputs')
            np.testing.assert_array_equal(transform_inputs(pre,full),transform_inputs(loaded,full))
            for task,a in adapters.items():
                a.save(tmp/(task+'.json'));b=TargetAdapter.load(tmp/(task+'.json'),context=pre.fit_context_)
                np.testing.assert_array_equal(a.transform(data['train',task].y),b.transform(data['train',task].y))
            encoded={role:transform_inputs(pre,data[role,'regression']).to_numpy() for role in roles}
            positions={c:i for i,c in enumerate(pre.get_feature_names_out())}
            for task,adapter in adapters.items():
                for role in roles:
                    d=data[role,task];adapted=adapter.transform(d.y)
                    if task=='regression':
                        np.testing.assert_allclose(adapter.inverse_transform(adapted),d.y,rtol=ROUNDTRIP_RTOL,atol=ROUNDTRIP_ATOL)
                    else:np.testing.assert_array_equal(adapter.inverse_transform(adapted),d.y.future_state_id)
            if feature_extension:
                extended={role:load_dataset(**kwargs,information_set=ENHANCED,role=role) for role in roles}
                for role,d in extended.items():
                    validate_pair(data[role,'regression'],d)
                    pd.testing.assert_frame_equal(d.X_market,data[role,'regression'].X_market)
                extended_pre=fit_inputs(extended['train'])
                market_train=information_view(extended['train'],'M',store=store)
                market_view=restrict_inputs(extended_pre,market_train)
                pd.testing.assert_frame_equal(transform_inputs(market_view,market_train),
                    transform_inputs(restrict_inputs(pre,market_train),market_train))
                extended_pre.save(tmp/'inputs_z_star')
                np.testing.assert_array_equal(transform_inputs(extended_pre,extended['train']),
                    transform_inputs(FoldPreprocessor.load(tmp/'inputs_z_star'),extended['train']))
            for info in infos:
                train=extended['train'] if info==ENHANCED else information_view(full,info,store=store)
                p=extended_pre if info==ENHANCED else restrict_inputs(pre,train)
                # Target adapter identity cannot depend on selected X columns.
                assert adapters['regression'].adapter_version_==fit_targets(train).adapter_version_
                schema_records.append(dict(market_id=market,fold_id=fold,information_set=info,
                    raw_features=len(p.feature_names_in_),encoded_features=len(p.output_names_),
                    schema_version=p.schema_['schema_version'],training_keys_hash=p.fit_context_['training_keys_hash'],
                    regression_adapter_version=adapters['regression'].adapter_version_,
                    classification_adapter_version=adapters['classification'].adapter_version_))
                cols=[positions[c] for c in p.output_names_] if info!=ENHANCED else None
                for role in roles:
                    view=extended[role] if info==ENHANCED else information_view(data[role,'regression'],info,store=store)
                    validate_pair(data[role,'regression'],view)
                    transformed=transform_inputs(p,view)
                    if cols is not None:np.testing.assert_array_equal(transformed,encoded[role][:,cols])
                    for task in ['classification','regression','probability']:
                        if info==ENHANCED:
                            v=view if task=='regression' else target_view(view,task,store=store)
                        else:v=information_view(data[role,task],info,store=store)
                        validate_pair(data[role,task],v)
                        if task=='probability':validate_probabilities(v.y,v.target_schema['class_ids'])
                        records.append(dict(market_id=market,fold_id=fold,role=role,information_set=info,task=task,
                            rows=len(v.X),cohort_hash=key_hash(v.keys),truth_hash=truth_hash(v.y),
                            preprocessing_version=p.schema_['schema_version'],
                            target_adapter_version=adapters[task].adapter_version_ if task in adapters else 'AUXILIARY_NO_TRAINING_ADAPTER',
                            status='PASS' if len(v.X) else 'NO_MATURE_SCORE_ROWS'))
            if fold!='initial':
                pred=load_dataset(**kwargs,information_set='M+Z',role='prediction')
                original_get=store.get
                def without_truth(name):
                    if name in ['sample_manifest','supervised_targets']:raise AssertionError('Prediction opened future table')
                    return original_get(name)
                try:
                    store.get=without_truth
                    independent=load_dataset(market_id=market,information_set='M+Z',fold_id=fold,role='prediction',store=store)
                    pd.testing.assert_frame_equal(pred.X,independent.X);pd.testing.assert_frame_equal(pred.metadata,independent.metadata)
                    if feature_extension:
                        enhanced_pred=load_dataset(**kwargs,information_set=ENHANCED,role='prediction')
                        validate_pair(pred,enhanced_pred)
                        pd.testing.assert_frame_equal(pred.X_market,enhanced_pred.X_market)
                finally:store.get=original_get
                for info in infos:
                    if info==ENHANCED:
                        view=enhanced_pred;p=extended_pre
                    else:
                        view=information_view(pred,info,store=store)
                        p=restrict_inputs(pre,information_view(full,info,store=store))
                    transform_inputs(p,view)
                    prediction_records.append(dict(market_id=market,fold_id=fold,information_set=info,rows=len(view.X),
                        cohort_hash=key_hash(view.keys),future_tables_read=False,status='PASS'))
            if fold=='initial' and market=='000985.SH':
                write(destination/'example_input_schema.json',extended_pre.schema_ if feature_extension else pre.schema_)
            if fold.endswith('-12') or fold in ['initial','2026-11']:print('interface acceptance',market,fold,flush=True)
    result=pd.DataFrame(records);prediction=pd.DataFrame(prediction_records)
    assert len(result)==len(tasks)
    for column in ['cohort_hash','truth_hash']:
        assert result.groupby(['market_id','fold_id','role','task'])[column].nunique().eq(1).all()
    assert assert_sealed_products(data_root=store.root)==store.data_version and file_hash(seal_path)==seal_hash,'Underlying sealed research data changed'
    if feature_extension:
        assert validate_extension(store.root)==store.extension_manifest,'Z* sealed products changed'
    assert code_hash()==start_code_hash,'Interface code changed during acceptance; rerun with stable code'
    result.to_parquet(destination/'tasks.parquet',index=False)
    prediction.to_parquet(destination/'prediction_reads.parquet',index=False)
    pd.DataFrame(schema_records).to_parquet(destination/'schemas.parquet',index=False)
    manifest=store.get('sample_manifest')
    tail=manifest[manifest.history_valid&~manifest.continuous_valid].groupby('market_id').size().to_dict()
    summary=dict(passed=True,contract_version=CONTRACT_VERSION,data_version=store.data_version,
        versions={k:store.spec[k] for k in ['feature_version','target_version','label_version']},
        tasks=len(result),pass_tasks=int(result.status.eq('PASS').sum()),empty_score_tasks=int(result.status.eq('NO_MATURE_SCORE_ROWS').sum()),
        prediction_tasks=len(prediction),prediction_rows_with_repeated_information_sets=int(prediction.rows.sum()),
        unlabelled_tail_rows_per_market=tail,all_information_sets_paired=True,train_only_transforms=True,
        per_fold_transform_roundtrip=True,per_fold_artifact_roundtrip=True,immutable_products=len(before),
        original_products=before,original_seal_hash=seal_hash,original_data_code_hash=seal['code_hash'],
        interface_code_hash=code_hash(),supervised_models_run=0,
        information_sets=list(infos),feature_extension=store.extension_manifest,
        scope='All sealed folds and prediction dates for the listed information sets; no supervised fitting')
    write(destination/'acceptance.json',summary)
    print('INTERFACE ACCEPTED',len(result),len(prediction),flush=True)
    return summary


def _receipt_directory(feature_extension):
    return DEST/EXTENSION if feature_extension==EXTENSION else DEST


def assert_interface_accepted(*,data_root=None,receipt_dir=None,feature_extension=None):
    if feature_extension not in (None,EXTENSION):raise ValueError('Unknown feature extension: '+feature_extension)
    destination=Path(receipt_dir) if receipt_dir is not None else _receipt_directory(feature_extension)
    record=json.loads((destination/'acceptance.json').read_text(encoding='utf8'))
    if not record['passed'] or record['contract_version']!=CONTRACT_VERSION or record['data_version']!=assert_sealed_products(data_root=data_root):raise RuntimeError('Interface acceptance identity mismatch')
    if record['interface_code_hash']!=code_hash():raise RuntimeError('Interface code changed; rerun interface-preflight and tests')
    root=Path(data_root) if data_root is not None else OUT
    if record['original_seal_hash']!=file_hash(root/'release/seal.json'):raise RuntimeError('Original data seal changed')
    if feature_extension:
        extension=validate_extension(root)
        if (record.get('feature_extension')!=extension
                or record['versions']['feature_version']!=extension['feature_version']
                or not set(CORE_INFORMATION_SETS)<=set(record.get('information_sets',()))):
            raise RuntimeError('Z* interface acceptance identity mismatch')
    elif record.get('feature_extension'):
        raise RuntimeError('Base interface acceptance cannot use an extension receipt')
    tests=json.loads((DEST/'test_results.json').read_text(encoding='utf8'))
    if tests['exit_code']!=0 or tests['interface_code_hash']!=record['interface_code_hash']:raise RuntimeError('Tests are missing or stale for this interface')
    return record
