"""Training-only label transforms and shared GMM. No predictive models."""
import joblib
import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture
from sklearn.metrics import adjusted_rand_score
from threadpoolctl import threadpool_limits
from .common import *

CONFIG=dict(k=list(range(1,9)),covariance=['spherical','diag','tied','full'],seed=3060,
    n_init=3,bootstrap_repetitions=12,block_weeks=8,
    selection='sum of ascending BIC rank, descending forward-time validation likelihood rank, descending bootstrap ARI rank; ties prefer smaller K then BIC',
    train_end='2019-12-31T18:00:00+08:00',cv_years=[2017,2018,2019])

def training_rows(outcomes):
    f=outcomes[outcomes.asof_date.between('2015-01-01','2019-12-31') & outcomes.measurement_valid & outcomes.label_available_at.le(clock('2019-12-31'))].copy()
    # Same complete dates per market => EXACT market equality, no sample weights approximation.
    common=f.groupby('asof_date').market_id.nunique();common=common[common.eq(4)].index
    return f[f.asof_date.isin(common)].sort_values(['asof_date','market_id']).reset_index(drop=True)

def fit_transform(f):
    x=f[CORE].to_numpy(float).copy();unit=np.ones(7)
    for j in [1,2,3]:
        positive=x[:,j][x[:,j]>0];unit[j]=np.median(positive) if len(positive) else 1
        x[:,j]=np.log1p(x[:,j]/unit[j])
    center=np.median(x,axis=0);scale=np.quantile(x,.75,axis=0)-np.quantile(x,.25,axis=0);scale[scale==0]=1
    return dict(unit=unit.tolist(),center=center.tolist(),scale=scale.tolist(),dimension_divisor=[1,1,1,2**.5,2**.5,2**.5,2**.5],columns=CORE)

def transform(f,params):
    x=f[CORE].to_numpy(float).copy()
    for j in [1,2,3]:x[:,j]=np.log1p(x[:,j]/params['unit'][j])
    return (x-params['center'])/params['scale']/params['dimension_divisor']

def model(k,cov,seed=3060):
    return GaussianMixture(n_components=k,covariance_type=cov,n_init=CONFIG['n_init'],random_state=seed,reg_covar=1e-5,max_iter=500)

def fit_dictionary(outcomes):
    old_path=OUT/'state_dictionary/dictionary.json'
    prior=json.loads(old_path.read_text(encoding='utf8')) if old_path.exists() else {}
    train=training_rows(outcomes)
    if train.empty:raise ValueError('No complete equal-market training windows')
    params=fit_transform(train);x=transform(train,params);dates=sorted(train.asof_date.unique());rng=np.random.default_rng(CONFIG['seed'])
    boot_indices=[]
    for rep in range(CONFIG['bootstrap_repetitions']):
        starts=rng.integers(0,len(dates)-CONFIG['block_weeks']+1,size=int(np.ceil(len(dates)/CONFIG['block_weeks'])))
        sampled=[d for s in starts for d in dates[s:s+CONFIG['block_weeks']]][:len(dates)]
        groups={d:train.index[train.asof_date.eq(d)].tolist() for d in dates}
        boot_indices.append([i for d in sampled for i in groups[d]])
    cv=[]
    for year in CONFIG['cv_years']:
        a=train[train.label_available_at.lt(clock(f'{year}-01-01'))]
        b=train[train.asof_date.dt.year.eq(year)]
        p=fit_transform(a);cv.append((transform(a,p),transform(b,p)))
    rows=[];models={}
    with threadpool_limits(limits=1):
        for cov in CONFIG['covariance']:
            for k in CONFIG['k']:
                g=model(k,cov).fit(x);base=g.predict(x);scores=[];ari=[];converged=[g.converged_]
                for a,b in cv:
                    m=model(k,cov).fit(a);scores.append(m.score(b));converged.append(m.converged_)
                for rep,idx in enumerate(boot_indices):
                    boot=train.iloc[idx];bp=fit_transform(boot)
                    m=model(k,cov,CONFIG['seed']+rep+1).fit(transform(boot,bp))
                    ari.append(adjusted_rand_score(base,m.predict(transform(train,bp))));converged.append(m.converged_)
                rows.append(dict(k=k,covariance=cov,bic=g.bic(x),cv_likelihood=np.mean(scores),cv_year_likelihoods=json.dumps(scores),
                    stability_ari=np.mean(ari),stability_ari_min=min(ari),bootstrap_ari=json.dumps(ari),all_converged=all(converged)))
                models[(k,cov)]=g
            print('dictionary candidates',cov,flush=True)
    scores=pd.DataFrame(rows)
    scores['rank_sum']=scores.bic.rank()+scores.cv_likelihood.rank(ascending=False)+scores.stability_ari.rank(ascending=False)
    selected=scores[scores.all_converged].sort_values(['rank_sum','k','bic']).iloc[0]
    g=models[(int(selected.k),selected.covariance)]
    raw=train.assign(raw=g.predict(x)).groupby('raw')[CORE].mean()
    order=raw.sort_values(['return','volatility']).index.tolist()
    version=digest(dict(config=CONFIG,params=params,training=train[KEY+CORE].to_dict('records'),means=g.means_.tolist(),order=order))[:20]
    artifact=dict(gmm=g,transform=params,order=order,label_version=version,protocol=VERSION,selection=CONFIG)
    folder=OUT/'state_dictionary';folder.mkdir(parents=True,exist_ok=True)
    joblib.dump(artifact,folder/'dictionary.joblib')
    write(folder/'dictionary.json',dict(label_version=version,protocol=VERSION,config=CONFIG,transform=params,component_order=order,
        selected=selected.to_dict(),training_rows=len(train),market_counts=train.market_id.value_counts().to_dict(),
        max_label_available_at=train.label_available_at.max(),means=g.means_.tolist(),covariances=g.covariances_.tolist(),weights=g.weights_.tolist(),
        training_fingerprint=digest(train[KEY+CORE].to_dict('records')),
        fit_event=dict(previous_label_version=prior.get('label_version'),
            training_input_changed=prior.get('training_fingerprint')!=digest(train[KEY+CORE].to_dict('records')),
            reason='Recompute all original BIC/time-block/stability candidates when initial core input fingerprint changes')))
    frame('state_dictionary/candidates',scores);frame('state_dictionary/training_keys',train[KEY+['label_available_at']])
    update_profiles(outcomes,artifact)
    return artifact

def update_profiles(outcomes,artifact):
    train=training_rows(outcomes)
    tagged=apply_dictionary(train,artifact,'future');profile=train.copy();profile['state_id']=tagged.future_state_id
    fields=CORE+['downside_semivol','worst_daily_return','worst_cumulative_return','quote_coverage','suspension_fraction']
    profiles=profile.groupby('state_id')[fields].mean().reset_index();profiles['n']=profile.groupby('state_id').size().values
    profiles['description']=profiles.apply(lambda r: ('收益均值接近零' if abs(r['return'])<.01 else '上涨' if r['return']>0 else '下跌')+
        f"（20日平均收益{r['return']:+.2%}）；"+('较高波动' if r.volatility>train.volatility.median() else '较低波动')+'；'+('负收益股票过半' if r.breadth>.5 else '负收益股票未过半'),axis=1)
    profiles['risk_downside']=profiles.drawdown.gt(train.drawdown.median())&profiles['return'].lt(0)
    profiles['risk_liquidity']=profiles.amihud.gt(train.amihud.median())&profiles.turnover.lt(train.turnover.median())
    profiles['risk_broad_decline']=profiles.breadth.gt(.5)&profiles['return'].lt(0)
    profiles['label_version']=artifact['label_version'];frame('state_dictionary/profiles',profiles)

def ensure_dictionary(outcomes,force=False):
    folder=OUT/'state_dictionary';meta=json.loads((folder/'dictionary.json').read_text(encoding='utf8')) if (folder/'dictionary.json').exists() else {}
    train=training_rows(outcomes);fingerprint=digest(train[KEY+CORE].to_dict('records'))
    if not force and meta.get('training_fingerprint')==fingerprint:
        a=joblib.load(folder/'dictionary.joblib')
        if a['transform']!=fit_transform(train):raise ValueError('Dictionary transform mismatch')
        update_profiles(outcomes,a)
        meta['reuse_verification']=dict(training_fingerprint=fingerprint,core_input_unchanged=True,
            description_only_neutral_mean_tolerance=.01,auxiliary_profiles_recomputed=True)
        write(folder/'dictionary.json',meta)
        print('reused fixed dictionary; identical initial training core inputs',flush=True);return a
    return fit_dictionary(outcomes)

def apply_dictionary(f,artifact,prefix):
    f=f.copy();k=artifact['gmm'].n_components;valid=f[CORE].notna().all(axis=1)
    probs=np.full((len(f),k),np.nan)
    if valid.any():probs[valid]=artifact['gmm'].predict_proba(transform(f.loc[valid],artifact['transform']))[:,artifact['order']]
    ids=pd.Series(pd.NA,index=f.index,dtype='Int64');ids.loc[valid]=probs[valid].argmax(axis=1)
    f[prefix+'_state_id']=ids
    for j in range(k):f[f'{prefix}_state_prob_{j}']=probs[:,j]
    f[prefix+'_state_entropy']=-np.sum(np.where(probs>0,probs*np.log(np.maximum(probs,1e-300)),0),axis=1)
    f.loc[~valid,prefix+'_state_entropy']=np.nan
    f[prefix+'_state_max_membership']=np.max(probs,axis=1)
    f['label_version']=artifact['label_version'];return f
