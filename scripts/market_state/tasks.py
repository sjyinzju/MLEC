"""Expand and execute data-only batch acceptance. No model specifications."""
import numpy as np
import pandas as pd
from .common import *
from .framework import DataStore,load_dataset,preprocessing
from .release import code_hash

def expand():
    spec=json.loads((OUT/'feature_sets.json').read_text(encoding='utf8'))
    plans=read('time_splits');rows=[]
    roles=[('initial','train')]
    for r in plans.itertuples():roles += [(r.fold_id,'train'),(r.fold_id,r.period)]
    for market in MARKETS:
        for fold,role in roles:
            for info in spec['sets']:
                for target in ['classification','probability','regression']:
                    rows.append(dict(market_id=market,fold_id=fold,role=role,information_set=info,task=target))
    tasks=pd.DataFrame(rows);frame('data_tasks',tasks)
    write(OUT/'data_task_config.json',dict(version='data-tasks-v1',markets=list(MARKETS),information_sets=list(spec['sets']),
        targets=['classification','probability','regression'],schedule='monthly train/validation-or-test plus initial mature train',
        models=None,run='python -m scripts.market_state.run preflight',task_count=len(tasks)))
    return tasks

def preflight():
    tasks=expand();store=DataStore();results=[];preprocessing_audit=[]
    target_table=store.get('supervised_targets').set_index(KEY)
    full_columns=store.spec['by_market'];sets=store.spec['sets']
    for (market,fold),group in tasks.groupby(['market_id','fold_id'],sort=False):
        train=load_dataset(market_id=market,information_set='M+Z',fold_id=fold,role='train',store=store)
        roles=group.role.unique();data={'train':train}
        for role in roles:
            if role!='train':data[role]=load_dataset(market_id=market,information_set='M+Z',fold_id=fold,role=role,store=store)
        target_views={}
        for role,ds in data.items():
            idx=pd.MultiIndex.from_frame(ds.metadata[KEY]);truth=target_table.reindex(idx)
            target_views[role]={'classification':truth[['future_state_id']],
                'probability':truth[[c for c in truth if c.startswith('future_state_prob_')]],'regression':truth[CORE]}
            assert len(ds.X)==len(ds.metadata)==len(truth)
            assert not ds.metadata[KEY].duplicated().any()
        cohort_hash={role:digest(ds.metadata[KEY+['label_version']].to_dict('records')) for role,ds in data.items()}
        target_hash={(role,task):digest(y.to_numpy().tolist()) for role,targets in target_views.items() for task,y in targets.items()}
        train_preprocessor=preprocessing();assert not hasattr(train_preprocessor,'median_')
        train_preprocessor.fit(train.X)
        transformed_full={role:train_preprocessor.transform(ds.X) for role,ds in data.items()}
        output_positions={c:i for i,c in enumerate(train_preprocessor.get_feature_names_out())}
        for info in sets:
            cols=full_columns[market][info];assert len(cols)==len(set(cols))
            assert not any(c.startswith('future') or 'label_' in c for c in cols)
            assert not any(c.startswith('cross__'+market.replace('.','_')+'__') for c in cols)
            pre=train_preprocessor.subset(cols)
            preprocessing_audit.append(dict(market_id=market,fold_id=fold,information_set=info,train_rows=len(train.X),
                all_empty_columns=json.dumps(pre.all_empty_),constant_value_columns=json.dumps(pre.constant_),
                train_category_counts=json.dumps({k:len(v) for k,v in pre.categories_.items()}),output_features=len(pre.get_feature_names_out())))
            for role,ds in data.items():
                positions=[output_positions[c] for c in pre.get_feature_names_out()]
                # Every row is transformed above. Univariate subset restriction
                # is exact; additionally run the public subset transform on a
                # sentinel and compare its encoding to the full transform.
                sentinel=pre.transform(ds.X[cols].iloc[:1])
                np.testing.assert_array_equal(sentinel,transformed_full[role][:1,positions])
                for task,y in target_views[role].items():
                    assert len(y)==len(ds.X) and not y.isna().any().any()
                    if task=='probability' and len(y):assert np.allclose(y.sum(axis=1),1)
                    results.append(dict(market_id=market,fold_id=fold,role=role,information_set=info,task=task,
                        rows=len(y),input_features=len(cols),encoded_features=len(positions),
                        cohort_hash=cohort_hash[role],target_hash=target_hash[(role,task)],
                        label_version=store.spec['label_version'],target_version=store.spec['target_version'],feature_version=store.spec['feature_version'],
                        status='PASS' if len(y) else 'NO_MATURE_SCORE_ROWS'))
        if fold.endswith('-12') or fold=='initial':print('batch preflight',market,fold,flush=True)
    result=pd.DataFrame(results);assert len(result)==len(tasks)
    assert result.groupby(['market_id','fold_id','role','task']).cohort_hash.nunique().eq(1).all()
    assert result.groupby(['market_id','fold_id','role','task']).target_hash.nunique().eq(1).all()
    frame('release/data_preflight',result);frame('release/preprocessing_audit',pd.DataFrame(preprocessing_audit))
    write(REPORT/'batch_preflight.json',dict(tasks=len(result),pass_tasks=int(result.status.eq('PASS').sum()),
        no_mature_score_tasks=int(result.status.eq('NO_MATURE_SCORE_ROWS').sum()),failed=0,
        all_sets_share_rows_and_targets=True,unfitted_factory_then_train_only_preprocessing=True,supervised_models_run=0,
        target_version=store.spec['target_version'],feature_version=store.spec['feature_version'],
        calculation_code_hash=code_hash()))
    return result
