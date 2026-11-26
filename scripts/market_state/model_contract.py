"""Shared schemas and boundary validation; contains no predictive estimators."""
from dataclasses import dataclass, asdict
from typing import Protocol
import json
import numpy as np
import pandas as pd
from .common import KEY, CORE, OUT, MARKETS, digest, read

CONTRACT_VERSION = 'model-io-v1'
PROBABILITY_ATOL = 1e-8
ROUNDTRIP_RTOL = 1e-12
ROUNDTRIP_ATOL = 1e-24
DIMENSIONS = {'trend':['return'], 'volatility':['volatility'], 'downside':['drawdown'],
              'liquidity':['amihud','turnover'], 'structure':['breadth','correlation']}
BOUNDS = {'return':[-1,None], 'volatility':[0,None], 'drawdown':[0,1], 'amihud':[0,None],
          'turnover':[0,None], 'breadth':[0,1], 'correlation':[-1,1]}
IDENTITY = ['data_version','feature_version','target_version','dictionary_version','contract_version']
OUTPUT_CONTEXT_FIELDS = ['fold_id','fit_cutoff','model_id','information_set','preprocessing_version',
                         'target_adapter_version','model_version','quality']


def target_schema(get=read,*,dictionary=None):
    if dictionary is None:dictionary=json.loads((OUT/'state_dictionary/dictionary.json').read_text(encoding='utf8'))
    profiles=get('state_dictionary/profiles').sort_values('state_id')
    ids=profiles.state_id.astype(int).tolist()
    if ids!=list(range(len(dictionary['component_order']))):raise ValueError('Dictionary class order mismatch')
    fields=get('field_dictionary');fields=fields[fields.dataset_id.eq('future_window_outcomes')].set_index('field')
    return dict(contract_version=CONTRACT_VERSION,dictionary_version=dictionary['label_version'],class_ids=ids,
        class_semantics=profiles[['state_id','description']].to_dict('records'),dimensions=DIMENSIONS,
        columns=dict(classification=['future_state_id'],regression=CORE,probability=['future_state_prob_'+str(i) for i in ids]),
        continuous=[dict(field=c,unit=fields.loc[c,'unit'],definition=fields.loc[c,'definition'],
            dimension=next(d for d,v in DIMENSIONS.items() if c in v),bounds=BOUNDS[c]) for c in CORE],
        probability_role='auxiliary realized-label memberships, never predicted probabilities',
        decision_rule='argmax; ties choose first class in dictionary order',probability_atol=PROBABILITY_ATOL)


def unique_keys(keys):
    if list(keys.columns)!=KEY or keys.isna().any().any() or keys.duplicated().any():raise ValueError('Invalid or duplicate sample keys')
    if not keys.horizon.eq(20).all():raise ValueError('Expected horizon=20')
    if not keys.market_id.isin(MARKETS).all() or not pd.api.types.is_datetime64_any_dtype(keys.asof_date):raise ValueError('Invalid market/date key')


def key_hash(keys):
    unique_keys(keys)
    return digest(keys.to_dict('records'))


def truth_hash(y):
    return digest(dict(columns=list(y.columns),values=y.astype(float).to_numpy().tolist()))


def validate_dataset(ds):
    unique_keys(ds.keys)
    n=len(ds.keys)
    components=[ds.X_market,ds.X_macro]
    if ds.X_interactions is not None:components.append(ds.X_interactions)
    for part in [ds.X,*components,ds.metadata]+([] if ds.y is None else [ds.y]):
        if len(part)!=n or not part.index.equals(ds.keys.index):raise ValueError('X/Y/metadata row alignment mismatch')
    if not ds.keys.equals(ds.metadata[KEY]):raise ValueError('Metadata keys mismatch')
    if list(ds.X.columns)!=ds.feature_names or ds.feature_names!=ds.feature_schema['columns'] or not ds.X.columns.is_unique:raise ValueError('Invalid feature order')
    if [c for part in components for c in part]!=list(ds.X):raise ValueError('Information set composition mismatch')
    if not pd.concat(components,axis=1).equals(ds.X):raise ValueError('Information set values mismatch')
    if any(not c.startswith(('market__','cross__','current_state')) for c in ds.X_market) or any(
            not c.startswith('macro__') for c in ds.X_macro) or (
            ds.X_interactions is not None and any(not c.startswith('interaction__') for c in ds.X_interactions)):
        raise ValueError('Forbidden target/future/metadata feature or misclassified input')
    if not ds.X.dtypes.astype(str).to_dict()==ds.feature_schema['dtypes']:raise ValueError('Input dtype mismatch')
    if any(not pd.api.types.is_numeric_dtype(t) for t in ds.X.dtypes):raise ValueError('Non-numeric raw feature')
    if np.isinf(ds.X.to_numpy(float)).any():raise ValueError('Infinite input')
    m=ds.metadata
    if not m.asof_time.eq(m.asof_date.dt.tz_localize('Asia/Shanghai')+pd.Timedelta(hours=18)).all():raise ValueError('Feature asof time mismatch')
    if ds.context['role']=='train' and (m.label_available_at.isna().any() or not m.label_available_at.le(m.fit_cutoff).all() or not m.asof_time.le(m.fit_cutoff).all()):raise ValueError('Immature training labels or future training input')
    if ds.context['role']=='prediction':
        if ds.y is not None or any(c.startswith(('label_','future_')) or c in ['eligible','continuous_valid','class_valid'] for c in m if c!='label_version'):raise ValueError('Prediction depends on future labels')
    elif ds.y is not None and ds.context['view']!='analysis':
        if ds.y.isna().any().any():raise ValueError('Incomplete supervised target')
    for name,value in ds.versions.items():
        equal=m[name].isna() if value is None else m[name].eq(value)
        if len(m) and not equal.all():raise ValueError('Dataset version mismatch: '+name)
    return ds


@dataclass(frozen=True)
class FitContext:
    market_id: str
    fold_id: str
    fit_cutoff: str
    information_set: str
    quality: str
    versions: dict
    training_keys_hash: str
    training_target_hash: str


def fit_context(ds):
    validate_dataset(ds)
    if ds.context['role']!='train' or ds.context['view']=='analysis' or not ds.versions['data_version']:raise ValueError('Fit requires formal training role')
    if not len(ds.X) or ds.context['market_id'] is None:raise ValueError('Fit requires one market and nonempty train rows')
    if ds.metadata.fit_cutoff.nunique()!=1:raise ValueError('Ambiguous fit cutoff')
    return FitContext(ds.context['market_id'],ds.context['fold_id'],str(ds.metadata.fit_cutoff.iloc[0]),
        ds.context['information_set'],ds.context['quality'],ds.versions.copy(),key_hash(ds.keys),truth_hash(ds.y))


def target_context(context):
    """Target identity excludes information set and quality by construction."""
    d=asdict(context);d.pop('information_set');d.pop('quality');return d


def fit_inputs(ds):
    from .preprocessing import FoldPreprocessor
    ctx=fit_context(ds)
    p=FoldPreprocessor().fit(ds.X)
    p.fit_context_=asdict(ctx)
    p.fit_context_.pop('training_target_hash')
    p.schema_['fit_context']=p.fit_context_
    p.refresh_schema_version()
    return p


def restrict_inputs(preprocessor, training_view):
    """Reuse exact univariate statistics across paired information sets."""
    ctx=asdict(fit_context(training_view));ctx.pop('training_target_hash')
    for name,value in preprocessor.fit_context_.items():
        if name!='information_set' and value!=ctx[name]:raise ValueError('Different training cohort for input restriction')
    p=preprocessor.subset(training_view.feature_names);p.fit_context_=ctx
    p.schema_['fit_context']=ctx;p.refresh_schema_version()
    return p


def training_partition(parent, keys, *,role,fit_cutoff):
    """Explicit internal time-validation subset of a formal outer TRAIN read only."""
    from dataclasses import replace
    fit_context(parent);unique_keys(keys)
    if role not in ['train','validation']:raise ValueError('Internal partition role must be train/validation')
    cut=pd.Timestamp(fit_cutoff)
    if cut.tzinfo is None or cut>parent.metadata.fit_cutoff.iloc[0]:raise ValueError('Invalid internal fit cutoff')
    positions=parent.keys.reset_index().merge(keys,on=KEY,validate='one_to_one')
    if len(positions)!=len(keys):raise ValueError('Internal rows outside outer training cohort')
    pos=positions['index'].sort_values().to_numpy()
    part=lambda table:table.iloc[pos].reset_index(drop=True)
    meta=part(parent.metadata);meta['fit_cutoff']=cut;meta['role']=role
    if role=='validation' and not meta.asof_time.gt(cut).all():raise ValueError('Internal validation must follow fit cutoff')
    result=replace(parent,keys=part(parent.keys),X=part(parent.X),X_market=part(parent.X_market),
        X_macro=part(parent.X_macro),X_interactions=None if parent.X_interactions is None else part(parent.X_interactions),
        y=part(parent.y),metadata=meta,context=dict(parent.context,role=role))
    return validate_dataset(result)


def transform_inputs(preprocessor, ds):
    _validate_input_context(preprocessor, ds)
    result=pd.DataFrame(preprocessor.transform(ds.X),columns=preprocessor.get_feature_names_out(),index=ds.keys.index)
    return validate_model_input(result,preprocessor.schema_,keys=ds.keys)


def _validate_input_context(preprocessor, ds):
    validate_dataset(ds)
    if not hasattr(preprocessor,'fit_context_'):raise ValueError('Use fit_inputs on formal train rows first')
    c=preprocessor.fit_context_
    for name in ['market_id','fold_id','information_set','quality','versions']:
        if c[name]!=ds.context[name]:raise ValueError('Input context mismatch: '+name)
    if len(ds.X) and not ds.metadata.fit_cutoff.astype(str).eq(c['fit_cutoff']).all():raise ValueError('Input fit cutoff mismatch')
    if ds.context['role']!='train' and len(ds.X) and not ds.metadata.asof_time.gt(pd.Timestamp(c['fit_cutoff'])).all():raise ValueError('Prediction before fit cutoff')


def validate_model_input(X,schema,*,keys):
    """Shared boundary for future estimator adapters after preprocessing."""
    unique_keys(keys)
    if not isinstance(X,pd.DataFrame) or not X.columns.is_unique or list(X.columns)!=schema['output_columns']:raise ValueError('Model input column order/schema mismatch')
    if len(X)!=len(keys) or not X.index.equals(keys.index):raise ValueError('Model input row mismatch')
    if any(str(t)!=schema['output_dtype'] for t in X.dtypes) or not np.isfinite(X.to_numpy()).all():raise ValueError('Model input dtype/values mismatch')
    return X


@dataclass(frozen=True)
class PredictionContext:
    keys: pd.DataFrame
    fold_id: str
    fit_cutoff: str
    model_id: str
    information_set: str
    versions: dict
    preprocessing_version: str
    target_adapter_version: str
    model_version: str
    quality: str


def prediction_context(ds, preprocessor, target_adapter, *,model_id,model_version,input_matrix=None):
    if ds.context['role'] not in ['validation','test','prediction']:raise ValueError('Prediction requires validation/test/prediction role')
    if input_matrix is None:
        transform_inputs(preprocessor,ds)
    else:
        _validate_input_context(preprocessor,ds)
        validate_model_input(input_matrix,preprocessor.schema_,keys=ds.keys)
    c=preprocessor.fit_context_
    target_adapter.check_context(c)
    if not model_id or not model_version:raise ValueError('Explicit model identity required')
    return PredictionContext(ds.keys.copy(),c['fold_id'],c['fit_cutoff'],model_id,c['information_set'],c['versions'].copy(),
        preprocessor.schema_['schema_version'],target_adapter.adapter_version_,model_version,c['quality'])


def validate_probabilities(probabilities, class_ids, n=None):
    p=np.asarray(probabilities,float)
    if p.ndim!=2 or p.shape[1]!=len(class_ids) or (n is not None and len(p)!=n):raise ValueError('Probability shape mismatch')
    if not np.isfinite(p).all() or (p<0).any() or (p>1).any() or not np.allclose(p.sum(axis=1),1,atol=PROBABILITY_ATOL,rtol=0):raise ValueError('Invalid probabilities')
    return p


def _output_base(ctx):
    unique_keys(ctx.keys)
    if ctx.versions.get('contract_version')!=CONTRACT_VERSION or any(not ctx.versions.get(v) for v in IDENTITY):raise ValueError('Invalid output version context')
    if any(not getattr(ctx,k) for k in ['model_id','model_version','preprocessing_version','target_adapter_version']):raise ValueError('Missing output component identity')
    result=ctx.keys.copy()
    for k,v in {**ctx.versions,**{k:getattr(ctx,k) for k in OUTPUT_CONTEXT_FIELDS}}.items():result[k]=v
    return result


def classification_output(ctx, predicted_state_ids, probabilities, schema):
    if schema['dictionary_version']!=ctx.versions['dictionary_version']:raise ValueError('Output dictionary version mismatch')
    result=_output_base(ctx);ids=schema['class_ids'];p=validate_probabilities(probabilities,ids,len(result))
    y=np.asarray(predicted_state_ids)
    if y.shape!=(len(result),) or not set(y)<=set(ids):raise ValueError('Invalid predicted class IDs')
    if not np.array_equal(y,np.asarray(ids)[p.argmax(axis=1)]):raise ValueError('Class disagrees with probability argmax decision')
    result['predicted_state_id']=y
    for j,c in enumerate(ids):result['predicted_state_prob_'+str(c)]=p[:,j]
    return result


def regression_output(ctx, original_values, schema):
    if schema['dictionary_version']!=ctx.versions['dictionary_version']:raise ValueError('Output dictionary version mismatch')
    names=['predicted_'+c for c in CORE]
    if not isinstance(original_values,pd.DataFrame) or list(original_values.columns)!=CORE:raise ValueError('Named original-unit seven-target order required')
    a=original_values.to_numpy(float);result=_output_base(ctx)
    if a.shape!=(len(result),len(CORE)) or not np.isfinite(a).all():raise ValueError('Invalid regression output')
    for j,c in enumerate(names):result[c]=a[:,j]
    violations=[]
    for row in a:
        violations.append(json.dumps([c for c,v in zip(CORE,row) if (BOUNDS[c][0] is not None and v<BOUNDS[c][0]) or (BOUNDS[c][1] is not None and v>BOUNDS[c][1])]))
    result['economic_bound_violations']=pd.Series(violations,index=result.index,dtype='str')
    result['output_units']='original'
    return result


def validate_output(result, ctx, *,task, schema):
    """Also validates externally assembled output, including exact row and identity order."""
    expected=_output_base(ctx)
    if not result.columns.is_unique:raise ValueError('Duplicate output column')
    columns=(['predicted_state_id']+['predicted_state_prob_'+str(c) for c in schema['class_ids']] if task=='classification'
        else ['predicted_'+c for c in CORE]+['economic_bound_violations','output_units'])
    if list(result.columns)!=list(expected.columns)+columns:raise ValueError('Output columns/order mismatch')
    for c in expected:
        if c not in result or not result[c].reset_index(drop=True).equals(expected[c].reset_index(drop=True)):raise ValueError('Output identity/row mismatch: '+c)
    if task=='classification':classification_output(ctx,result.predicted_state_id,result[['predicted_state_prob_'+str(c) for c in schema['class_ids']]],schema)
    elif task=='regression':
        v=result[['predicted_'+c for c in CORE]].rename(columns={'predicted_'+c:c for c in CORE})
        rebuilt=regression_output(ctx,v,schema)
        if not result.output_units.eq('original').all() or not result.economic_bound_violations.equals(rebuilt.economic_bound_violations):raise ValueError('Regression unit/bound annotation mismatch')
    else:raise ValueError('Only two primary prediction tasks')
    return result


def validate_pair(left,right):
    """Information sets may differ; all cohorts, truth and cutoffs must agree."""
    if not left.keys.equals(right.keys):raise ValueError('Unpaired keys')
    if (left.y is None)!=(right.y is None) or (left.y is not None and not left.y.equals(right.y)):
        raise ValueError('Unpaired y')
    for name in ['versions','market_id','fold_id','role']:
        if left.context[name]!=right.context[name]:raise ValueError('Unpaired '+name)
    if not left.metadata.fit_cutoff.equals(right.metadata.fit_cutoff):raise ValueError('Unpaired cutoff')


@dataclass(frozen=True)
class EvaluationContext:
    prediction: PredictionContext
    task: str
    fixed_scale: dict = None


def evaluation_pairs(predictions, truth, ctx, *,task, schema):
    """Attach truth only AFTER prediction. No metrics or model fitting here."""
    validate_output(predictions,ctx,task=task,schema=schema);validate_dataset(truth)
    if truth.y is None or truth.context['role'] not in ['validation','test']:raise ValueError('Scoring requires mature held-out truth')
    if list(truth.y)!=schema['columns'][task]:raise ValueError('Evaluation target task mismatch')
    if truth.versions!=ctx.versions or truth.context['fold_id']!=ctx.fold_id or (len(ctx.keys) and truth.context['market_id']!=ctx.keys.market_id.iloc[0]):raise ValueError('Evaluation identity mismatch')
    if truth.context['quality']!=ctx.quality or truth.context['information_set']!=ctx.information_set:raise ValueError('Evaluation input context mismatch')
    if not truth.metadata.fit_cutoff.astype(str).eq(ctx.fit_cutoff).all():raise ValueError('Evaluation cutoff mismatch')
    if key_hash(truth.keys)!=key_hash(ctx.keys):raise ValueError('Evaluation rows mismatch')
    return predictions.merge(pd.concat([truth.keys,truth.y],axis=1),on=KEY,validate='one_to_one')


def prepare_evaluation(predictions,truth,context):
    """Checked scoring handoff; callers can then use common evaluation utilities."""
    if context.task=='regression':
        s=context.fixed_scale
        if not s or s['source_fold']!='initial' or s['versions']!=truth.versions or s['market_id']!=truth.context['market_id'] or s['columns']!=CORE:raise ValueError('Fixed initial evaluation scale required')
    return evaluation_pairs(predictions,truth,context.prediction,task=context.task,schema=truth.target_schema)


@dataclass(frozen=True)
class ModelCapabilities:
    family: str
    task: str
    multioutput: str  # native or per_target wrapper for regression
    container: str = 'named_numeric_frame'
    missing_class_policy: str = 'must_declare_before_fit'
    probability_calibration: str = 'none_or_time_ordered_training_only'


class ModelAdapter(Protocol):
    """Future implementation boundary. predict NEVER accepts y_true."""
    capabilities: ModelCapabilities
    def fit(self, X_train, y_train, fit_context: FitContext): ...
    def predict(self, X_predict, prediction_context: PredictionContext): ...


class Evaluator(Protocol):
    def evaluate(self, predictions, y_true, evaluation_context): ...


PACKAGE_COMPONENTS = ['input_preprocessor','target_adapter','estimator','calibrator_optional',
                      'input_schema','output_schema','versions','fit_context','capabilities']


def prediction_schema(task,schema):
    common=KEY+IDENTITY+OUTPUT_CONTEXT_FIELDS
    if task=='classification':
        outputs=['predicted_state_id']+['predicted_state_prob_'+str(c) for c in schema['class_ids']]
    elif task=='regression':outputs=['predicted_'+c for c in CORE]+['economic_bound_violations','output_units']
    else:raise ValueError('Only two primary prediction tasks')
    return dict(contract_version=CONTRACT_VERSION,task=task,columns=common+outputs,
        class_ids=schema['class_ids'],continuous=schema['continuous'],probability_atol=PROBABILITY_ATOL,
        decision_rule=schema['decision_rule'],regression_units='original',economic_bound_policy='record_without_clipping')


def package_manifest(preprocessor,target_adapter,capabilities,*,model_version):
    """Manifest template only; this round never constructs a trained model package."""
    target_adapter.check_context(preprocessor.fit_context_)
    if capabilities.family not in ['Elastic Net','RBF-SVM','Random Forest','CatBoost']:raise ValueError('Unknown planned family')
    if capabilities.task not in ['classification','regression'] or capabilities.multioutput not in ['native','per_target','not_applicable']:raise ValueError('Invalid model capabilities')
    actual='classification' if 'research_to_internal' in target_adapter.parameters_ else 'regression'
    if actual!=capabilities.task:raise ValueError('Package target task mismatch')
    return dict(contract_version=CONTRACT_VERSION,components=PACKAGE_COMPONENTS,model_version=model_version,
        capabilities=asdict(capabilities),fit_context=preprocessor.fit_context_,input_schema=preprocessor.schema_,
        target_schema=target_adapter.schema_,output_schema=prediction_schema(capabilities.task,target_adapter.schema_),
        target_adapter_version=target_adapter.adapter_version_,estimator_created=False)
