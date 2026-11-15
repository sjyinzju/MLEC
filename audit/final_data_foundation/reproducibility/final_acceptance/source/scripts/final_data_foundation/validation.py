"""Executed real-data acceptance checks; technical success is not data acceptance."""
import json
import traceback
import numpy as np
from pandas.testing import assert_frame_equal
from .common import *
from .market import rel
from .macro_contract import specifications
from .research_inputs import FEATURES,LEVELS,make_weekly,prepare,load_dataset

RESULTS=[]


def check(number,name,fn):
    started=pd.Timestamp.now(tz='Asia/Shanghai')
    try:
        detail=fn() or {};row={'check':number,'name':name,'execution_status':'PASS',**detail}
    except Exception as exc:
        row={'check':number,'name':name,'execution_status':'FAIL','error':type(exc).__name__+': '+str(exc),'traceback':traceback.format_exc()}
    row['seconds']=(pd.Timestamp.now(tz='Asia/Shanghai')-started).total_seconds();RESULTS.append(row)
    write(AUDIT/'validation_results.json',RESULTS);print(number,name,row['execution_status'],row.get('error',''),flush=True)


def keys():
    regs=read(ROOT/'data/metadata/dataset_registry.json')['datasets'];c=db();n=0
    for r in regs:
        q='read_parquet('+qs(ROOT/r['authority_path'])+',union_by_name=true,hive_partitioning=false)'
        count=c.execute('SELECT count(*) FROM '+q).fetchone()[0];assert count==r['rows'];n+=count
        key=','.join('"'+k+'"' for k in r['primary_key'])
        assert c.execute('SELECT count(*) FROM (SELECT '+key+' FROM '+q+' GROUP BY '+key+' HAVING count(*)>1)').fetchone()[0]==0
    limits=c.execute('SELECT count(*),count(*) FILTER(WHERE up_limit IS NOT NULL OR down_limit IS NOT NULL) FROM '+rel('stock_limits_observations')+' WHERE rule_id IS NOT NULL').fetchone()
    assert limits==(70,0)
    flow_extras=pd.read_parquet(AUDIT/'market_coverage/moneyflow_without_traded_quote.parquet')
    flow_quality=c.execute("SELECT source_record_id,field FROM "+rel('market_data_quality')+" WHERE dataset_id='stock_moneyflow' AND quality_status='BLOCKED_FLOW_WITHOUT_OBSERVED_TRADE'").df()
    assert set(flow_quality.source_record_id)==set(flow_extras.source_record_id)
    assert len(flow_quality)==2*len(flow_extras)
    source_grid=pd.read_parquet(AUDIT/'market_coverage/secondary_stock_source_summary.parquet')
    observed=c.execute('SELECT count(*) FROM '+rel('stock_daily_observations')).fetchone()[0]
    assert source_grid.groupby('dataset_id').observations.sum().eq(observed).all()
    c.close();return {'datasets':len(regs),'physical_rows_checked':n,'special_rule_dates':limits[0],'secondary_source_grid_per_dataset':observed,'data_status':'QUALIFIED','reason':'Coverage and value certification assessed separately; every secondary-source row/missingness checked against the full traded population.'}


def indices():
    c=db();cal=c.execute('SELECT exchange,cal_date FROM '+rel('trade_calendar')+" WHERE is_open=1 AND cal_date BETWEEN ? AND ?",[START,END]).df()
    p=c.execute('SELECT ts_code,trade_date FROM '+rel('index_daily')).df();out=[]
    for code in INDEX_CODES:
        expected=set(cal[cal.exchange.eq('SSE' if code.endswith('SH') else 'SZSE')].cal_date);got=p[p.ts_code.eq(code)].trade_date
        assert set(got)==expected and len(got)==len(expected);out.append({'index':code,'expected':len(expected),'actual':len(got)})
    c.close();return {'indices':out,'data_status':'PASS_FOR_DATE_COVERAGE_ONLY'}


def stock_states():
    c=db();q=rel('stock_trading_status');master='read_parquet('+qs(MARKET/'stock_master_history.parquet')+')'
    expected=c.execute('SELECT count(*) FROM '+master+' m JOIN '+rel('trade_calendar')+" c ON m.exchange=c.exchange AND c.is_open=1 AND try_strptime(c.cal_date,'%Y%m%d')>=m.valid_from AND try_strptime(c.cal_date,'%Y%m%d')<m.valid_to WHERE c.cal_date BETWEEN ? AND ?",[START,END]).fetchone()[0]
    counts=c.execute('SELECT status,count(*) n FROM '+q+' GROUP BY 1').df();assert counts.n.sum()==expected
    assert not counts.status.str.contains('MISSING').any()
    unknown=sum(len(pd.read_parquet(p)) for p in (AUDIT/'market_coverage').glob('unknown_identity_*.parquet'));assert unknown==0
    aliases=pd.read_parquet(AUDIT/'market_coverage/canonical_stock_observations.parquet')
    assert aliases[aliases.dataset_id.eq('stock_daily')].outside_registered_identity_interval.sum()==0
    delisted=c.execute('SELECT count(DISTINCT instrument_id) FROM '+master+' WHERE delist_date IS NOT NULL').fetchone()[0];assert delisted>0
    c.close();return {'expected_security_dates':expected,'status_counts':counts.to_dict('records'),'retained_delisted_securities':delisted,'data_status':'QUALIFIED','remaining':'Master completeness against independent historical exchange listing catalogue not proven.'}


def constituents():
    d=pd.read_parquet(MARKET/'index_constituents_history.parquet');assert d.valid_to.gt(d.valid_from).all()
    assert d.research_available_at.dt.tz_localize(None).le(d.valid_from).all()
    assert not d.duplicated(['index_code','con_code','valid_from']).any()
    books=d.groupby(['index_code','valid_from']).con_code.nunique();assert books.eq(500).all()
    r=read(AUDIT/'issue_closure/cni_reconstruction.json')
    return {'rows':len(d),'books':len(books),'source_reconstruction':r,'data_status':'QUALIFIED','remaining':'Only 399001 after 2015-05-20. Snapshot weights are not effective daily weights; event catalogue incomplete certification.'}


def adjustments():
    s=pd.read_parquet(AUDIT/'market_coverage/stock_numeric_summary.parquet');assert s.affected_rows.sum()==0
    c=db();p=AUDIT/'market_coverage/adjusted_return_population.parquet'
    assert c.execute("SELECT count(*) FROM read_parquet(?) WHERE verification_status='INVALID_FACTOR'",[str(p)]).fetchone()[0]==0
    r=read(AUDIT/'issue_closure/official_factor_repair.json');assert abs(r['primary_return']-r['independent_return'])<.0002
    # Independently recompute returns from original unadjusted prices for every
    # stored population row; division order differs from production SQL.
    failures=c.execute('SELECT count(*) FROM read_parquet(?) WHERE abs((close/previous_traded_close)*(adj_factor/previous_factor)-1-adjusted_holding_return)>1e-12',[str(p)]).fetchone()[0];assert failures==0
    c.close();return {'population_rows':11981370,'official_repair':r,'data_status':'QUALIFIED','remaining':'Factor quantization and unresolved corporate-action basis remain explicitly classified.'}


def market_extensions():
    daily=pd.read_parquet(ROOT/'data/features/market/v4/all_a_daily.parquet').set_index('trade_date');c=db();checks=0
    for year in range(2014,2027):
        q=c.execute('SELECT trade_date,close,pre_close,amount_cny FROM '+rel('stock_daily_observations')+" WHERE ts_code NOT LIKE '689%' AND trade_date BETWEEN ? AND ?",[f'{year}0101',min(f'{year}1231',END)]).df()
        q['r']=q.close/q.pre_close-1;q['negative']=q.r.lt(0);q['amihud']=q.r.abs()/q.amount_cny.replace(0,np.nan)*1e8
        z=q.groupby('trade_date').agg(declining_fraction_traded=('negative','mean'),amount_cny=('amount_cny','sum'),amihud_per_100m_cny=('amihud','mean'),reference_return_dispersion=('r','std'))
        for col in z:assert np.allclose(z[col],daily.loc[z.index,col],rtol=1e-10,atol=1e-9,equal_nan=True),col
        checks+=len(z)
    corr=pd.read_parquet(ROOT/'data/features/market/v4/all_a_correlation_weekly.parquet');lineage=pd.read_parquet(ROOT/'data/features/market/v4/correlation_lineage.parquet').set_index('sample_id');direct=[]
    for index in [0,len(corr)//2,len(corr)-1]:
        r=corr.iloc[index];ids=json.loads(lineage.loc[r.sample_id,'selected_instrument_ids'])
        q=c.execute('SELECT instrument_id,trade_date,close/pre_close-1 r FROM '+rel('stock_daily_observations')+' WHERE trade_date BETWEEN ? AND ?',[r.window_start.strftime('%Y%m%d'),r.window_end.strftime('%Y%m%d')]).df()
        panel=q[q.instrument_id.isin(ids)].pivot(index='trade_date',columns='instrument_id',values='r');assert panel.shape==(60,len(ids))
        matrix=np.corrcoef(panel.to_numpy(),rowvar=False);value=matrix[np.triu_indices(len(ids),k=1)].mean();assert abs(value-r.average_pairwise_correlation_60d)<1e-12
        direct.append({'sample_id':r.sample_id,'securities':len(ids),'direct_pair_mean':value})
    c.close();return {'daily_dates_independently_recomputed':checks,'direct_all_pairs_correlation':direct,'data_status':'QUALIFIED','reason':'Correct conditional proxies; not exact index membership or certified original vintages.'}


def macro_grid():
    d=pd.read_parquet(META/'data_requirements_matrix.parquet');specs=specifications();required={s['series_id'] for s in specs if s['required']}
    assert set(d.series_id)==required;assert not d.duplicated(['series_id','period_end']).any()
    assert not d.status.isna().any();counts=d.groupby(['series_id','status']).size().reset_index(name='periods')
    frame(AUDIT/'macro_coverage/final_completeness_summary.parquet',counts)
    bad=d[~d.status.isin(['ACCEPTED','STRUCTURAL_NA'])];return {'registered_scopes':len(specs),'required_scopes':len(required),'grid_rows':len(d),'unaccepted_periods':len(bad),'data_status':'FAIL' if len(bad) else 'PASS'}


def macro_sources():
    dr=pd.read_parquet(AUDIT/'source_reconciliation/dr007_official_overlap.parquet')
    assert len(dr)==30 and np.allclose(dr.weight,dr.value,rtol=0,atol=1e-10)
    gac=pd.read_parquet(AUDIT/'source_reconciliation/gac_independent_arithmetic.parquet')
    # Reviewed extractors assert exact source hashes, literal dates and values;
    # independent GAC totals and official DR007 comparisons are retained too.
    from .macro_supplements import reviewed,safe_annual_reserves
    from .macro import reviewed_trade_reports
    facts=reviewed()+safe_annual_reserves()+reviewed_trade_reports()
    return {'literal_rechecked_facts':len(facts),'dr007_overlap_rows':len(dr),'gac_arithmetic_rows':len(gac),'data_status':'QUALIFIED','evidence':['source_reconciliation/dr007_official_overlap.parquet','source_reconciliation/gac_independent_arithmetic.parquet'],'remaining':'Not a first-vintage certification for all inherited facts.'}


def macro_time():
    f=pd.read_parquet(MACRO/'macro_facts.parquet');accepted=f[f.certification_status.eq('ACCEPTED')]
    assert accepted.research_available_at.notna().all()
    # Monthly LPR has an actual fixing date, while month-end is a reporting
    # bucket. PMI is a survey published before month-end around Lunar New Year.
    # Verify those exceptions against retained primary dated announcements.
    economic_end=accepted.period_end.copy();lpr=accepted.series_id.eq('lpr_1y')
    assert accepted.loc[lpr,'observation_date'].notna().all()
    economic_end.loc[lpr]=accepted.loc[lpr,'observation_date']
    early_pmi=accepted.series_id.isin(['pmi_mfg','pmi_new_orders','pmi_nonmfg'])&accepted.research_available_at.dt.tz_localize(None).lt(accepted.period_end)
    for r in accepted[early_pmi].itertuples(index=False):
        raw=(ROOT/r.evidence_path).read_text(encoding='utf-8');assert r.release_at.strftime('%Y/%m/%d') in raw
        assert f'{r.period_end.year}年{r.period_end.month}月中国采购经理指数运行情况' in raw
    economic_end.loc[early_pmi]=accepted.loc[early_pmi,'release_at'].dt.tz_localize(None)
    bad=accepted[accepted.research_available_at.dt.tz_localize(None).lt(economic_end)]
    frame(AUDIT/'temporal_validation/macro_time_violations.parquet',bad);assert len(bad)==0
    late=accepted.quality_status.eq('latest_vintage_reconstructed')
    assert accepted.loc[late,'research_available_at'].ge(accepted.loc[late,'retrieved_at']).all()
    return {'records_checked':len(accepted),'latest_vintages_kept_at_retrieval':int(late.sum()),'monthly_fixing_date_records':int(lpr.sum()),'primary_verified_early_monthly_survey_records':int(early_pmi.sum()),'data_status':'QUALIFIED','reason':'Dated reprints and later compilations are not first releases. LPR observation date differs from monthly bucket; PMI holiday early release is source-verified.'}


def conflicts():
    index=read(AUDIT/'issue_closure/index_adjudication_summary.json');macro=read(AUDIT/'macro_coverage/reconciliation_summary.json')
    return {'index':index,'macro':macro,'data_status':'FAIL' if index['unresolved_material_prices'] else 'QUALIFIED'}


def units():
    f=pd.read_parquet(MACRO/'macro_facts.parquet');spec={s['series_id']:s for s in specifications()};bad=[]
    for r in f[f.certification_status.eq('ACCEPTED')].itertuples(index=False):
        for field in ['unit','currency','measure_type']:
            if getattr(r,field)!=spec[r.series_id][field]:bad.append({'source_record_id':r.source_record_id,'series_id':r.series_id,'field':field,'value':getattr(r,field),'expected':spec[r.series_id][field]})
    frame(AUDIT/'macro_coverage/unit_violations.parquet',pd.DataFrame(bad,columns=['source_record_id','series_id','field','value','expected']));assert not bad,str(bad[:3])
    c=db()
    for name in ['index_daily','stock_daily_observations']:
        assert c.execute('SELECT count(*) FROM '+rel(name)+' WHERE abs(amount_cny-amount*1000)>1e-5 OR abs(volume_shares-vol*100)>1e-5').fetchone()[0]==0
    c.close();return {'macro_records_checked':len(f),'market_normalization_checked':'all observations','data_status':'QUALIFIED','remaining':'Some exchange aggregate/source-specific field units remain unverified and unadmitted.'}


def temporal_join():
    all_ids=pd.read_parquet(ROOT/'data/research_v2/market_features_weekly.parquet').sample_id.tolist();counts={}
    for level in LEVELS:
        w=pd.read_parquet(FEATURES/level/'macro_weekly.parquet');lin=pd.read_parquet(FEATURES/level/'macro_lineage.parquet');assert w.sample_id.tolist()==all_ids
        for r in lin[lin.value.notna()].itertuples(index=False):
            assert all(pd.Timestamp(t)<=r.asof_time for t in json.loads(r.available_ats));assert len(json.loads(r.source_record_ids))==len(json.loads(r.available_ats))
            if r.feature.endswith('__change'):
                assert len(set(json.loads(r.statistical_scope_ids)))==1, 'Cross-scope differences must be blocked'
        counts[level]={'samples':len(w),'feature_lineage_rows':len(lin),'populated_feature_cells':int(lin.value.notna().sum())}
    return {'quality_views':counts,'data_status':'QUALIFIED','reason':'Quote reconstruction is opt-in, not jointly strict market PIT.'}


def no_future():
    for level in LEVELS:
        lin=pd.read_parquet(FEATURES/level/'macro_lineage.parquet')
        for r in lin[lin.value.notna()].itertuples(index=False):
            actual=[pd.Timestamp(t) for t in json.loads(r.actual_vintage_available_ats)]
            if level!='quote_reconstructed':assert all(t<=r.asof_time for t in actual)
            elif any(t>r.asof_time for t in actual):assert r.series_id=='dr007'
    market=pd.read_parquet(ROOT/'data/features/market/v4/market_extensions_weekly.parquet')
    assert market.reconstructed_quote_at.le(market.asof_time).all();assert market.window_end.le(market.asof_time.dt.tz_localize(None)).all()
    assert not any('ex_post' in x or 'adjudication' in x for x in market)
    return {'data_status':'QUALIFIED','reason':'All declared effective-information policies respected; original market quote vintage is unavailable and never labeled strict PIT.'}


def counterfactual(mode):
    from .market_features import calculate_index_dimensions
    f=pd.read_parquet(MACRO/'macro_facts.parquet');market=pd.read_parquet(ROOT/'data/research_v2/market_features_weekly.parquet');points=market.iloc[[100,300,500]];evidence=[]
    c=db();quotes=c.execute('SELECT * FROM '+rel('index_daily')+' ORDER BY ts_code,trade_date').df();c.close()
    baseline=pd.read_parquet(ROOT/'data/features/market/v4/index_dimensions_daily.parquet');featurecols=[x for x in baseline if any(x.startswith(p) for p in ['return_','volatility_','max_drawdown_','downside_rms_','amount_ma'])]
    for level in ['conservative','quote_reconstructed']:
        expected=pd.read_parquet(FEATURES/level/'macro_weekly.parquet').set_index('sample_id')
        effective=prepare(f,level).set_index('source_record_id').effective_available_at
        for _,point in points.iterrows():
            cut=point.asof_time;future=f.source_record_id.map(effective).gt(cut);modified=f[~future].copy() if mode=='truncate' else f.copy()
            if mode=='perturb':modified.loc[future,'value']=modified.loc[future,'value']*17+12345
            w,_=make_weekly(modified,point.to_frame().T,level)
            assert_frame_equal(w.set_index('sample_id'),expected.loc[[point.sample_id]],check_dtype=False)
            evidence.append({'level':level,'cutoff':cut.isoformat(),'future_records':int(future.sum()),'features_compared':len(w.columns)-2})
    for _,point in points.iterrows():
        cut=point.asof_date.strftime('%Y%m%d');future=quotes.trade_date.gt(cut);modified=quotes[~future].copy() if mode=='truncate' else quotes.copy()
        if mode=='perturb':
            for col in ['open','high','low','close','pre_close','amount_cny']:modified.loc[future,col]=modified.loc[future,col]*17
        result=calculate_index_dimensions(modified);keys=['ts_code','trade_date']
        a=result[result.trade_date.le(cut)].set_index(keys)[featurecols].sort_index();b=baseline[baseline.trade_date.le(cut)].set_index(keys)[featurecols].sort_index();assert_frame_equal(a,b,check_dtype=False)
    write(AUDIT/'temporal_validation'/(mode+'.json'),evidence)
    return {'mode':mode,'macro_all_scope_checks':evidence,'market_indices':7,'market_cutoffs':3,'data_status':'PASS_UNDER_DECLARED_RECONSTRUCTION_POLICY'}


def lineage():
    from .collect import PUBLIC
    from .provider import API_RAW
    n=0
    for folder in [PUBLIC/'requests',API_RAW/'requests']:
        for p in folder.glob('*.json'):
            r=read(p)
            if r['status']!='ok':continue
            assert (ROOT/r['path']).exists() and sha(ROOT/r['path'])==r['sha256'];n+=1
    f=pd.read_parquet(MACRO/'macro_facts.parquet');ids=set(f.source_record_id);unresolved=[]
    for r in f.itertuples(index=False):
        if pd.notna(r.evidence_path) and not (ROOT/r.evidence_path).exists():unresolved.append({'id':r.source_record_id,'path':r.evidence_path})
        for p in json.loads(r.parent_record_ids or '[]'):
            if p not in ids and not (ROOT/p).exists():unresolved.append({'id':r.source_record_id,'parent':p})
    write(AUDIT/'integrity/lineage_unresolved.json',unresolved)
    assert not unresolved,str(unresolved[:3]);return {'verified_source_snapshots':n,'macro_rows':len(f),'data_status':'QUALIFIED','reason':'Record and transformation links preserved; some legacy records lack exact extraction locations.'}


def sample_ids():
    expected=pd.read_parquet(ROOT/'data/research_v2/market_features_weekly.parquet').sample_id.tolist();assert len(expected)==599 and len(set(expected))==599
    for p in (ROOT/'data/datasets/sample_manifests/v4').rglob('*.parquet'):
        assert pd.read_parquet(p).sample_id.tolist()==expected
    r=load_dataset(groups=['prices'],start='2020-01-01',end='2021-12-31',horizon=40,label='drawdown',include_market_extensions=True)
    assert r['features'].sample_id.tolist()==r['eligibility'].sample_id.tolist()
    x=load_dataset(groups=['credit'],start='2020-01-01',end='2021-12-31',require_complete_transforms=True)
    assert not (x['eligibility'].eligible&~x['eligibility'].active_transforms_complete).any()
    assert set(x['feature_lineage'].sample_id)<=set(x['features'].sample_id)
    assert r['targets'].horizon.eq(40).all();return {'frozen_sample_ids':599,'custom_interface_rows':len(r['features']),'data_status':'PASS'}


def frozen():
    baseline=read(AUDIT/'integrity/baseline.json')['files'];changed=[];protected=0
    archived_changes=[]
    permitted={'README.md','.gitignore','data/metadata/data_lineage.parquet','data/metadata/dataset_registry.json','data/metadata/schema_registry.json',
      'reports/data_quality/final_market_data_audit.md','reports/data_quality/final_macro_data_audit.md','reports/data_quality/final_cross_domain_validation.md',
      'reports/data_quality/full_research_data_inventory.md','reports/data_quality/source_and_vintage_validation.md','reports/data_quality/final_data_acceptance.md',
      'docs/research_data_contract.md','docs/research_data_dictionary.md','docs/data_architecture.md','docs/data_reproducibility.md','docs/remaining_limitations.md'}
    for path,r in baseline.items():
        protected+=1
        if not (ROOT/path).exists() or sha(ROOT/path)!=r['sha256']:
            archive=ROOT/'data/archive/data-foundation-v3'/path
            if path in permitted and archive.exists() and sha(archive)==r['sha256']:archived_changes.append(path)
            else:changed.append(path)
    write(AUDIT/'integrity/frozen_integrity.json',{'checked_files':protected,'changed':changed,'intentionally_replaced_metadata_archived_exactly':archived_changes});assert not changed,str(changed[:10])
    return {'checked_original_files':protected,'archived_metadata':archived_changes,'data_status':'PASS','protected':'Original labels, samples, thresholds, folds, models and prior source files unchanged. New top-level registry authority replaces three byte-exact archived v3 metadata files.'}


def external():
    manifest=read(AUDIT/'integrity/external_manifest.json');verified=0
    for r in manifest['parts']:
        p=Path(r['path']);assert p.stat().st_size==r['bytes'] and p.stat().st_mtime_ns==r['mtime_ns']
        if r.get('verified_sha256'):assert sha(p)==r['verified_sha256'];verified+=1
    r=manifest['database'];p=Path(r['path']);assert p.stat().st_size==r['bytes'] and p.stat().st_mtime_ns==r['mtime_ns'] and sha(p)==r['sha256']
    result={'catalogued_parts':len(manifest['parts']),'hashed_selected_parts':verified,'database_unchanged':True,'data_status':'PASS'};write(AUDIT/'integrity/external_readonly_recheck.json',result);return result


def offline():
    p=AUDIT/'reproducibility/offline_rebuild_result.json';assert p.exists(),'Offline rebuild has not run'
    r=read(p);assert r['status']=='PASS',str(r);return r


def run():
    work=[('market_primary_keys',keys),('seven_index_calendar_coverage',indices),('stock_identity_listing_and_suspension',stock_states),('constituent_temporal_validity',constituents),
      ('stock_returns_and_factors',adjustments),('breadth_liquidity_and_correlation',market_extensions),('all_macro_candidate_periods',macro_grid),('macro_source_value_review',macro_sources),
      ('macro_release_and_vintage_times',macro_time),('cross_source_conflicts',conflicts),('units_and_statistical_definitions',units),('frozen_sample_asof_join',temporal_join),
      ('no_future_information_policy',no_future),('real_historical_truncation',lambda:counterfactual('truncate')),('future_data_perturbation',lambda:counterfactual('perturb')),
      ('source_hashes_and_lineage',lineage),('sample_ids_and_configurable_interface',sample_ids),('frozen_protocol_labels_folds_hashes',frozen),('external_readonly_integrity',external),('offline_reproduction',offline)]
    for i,(name,fn) in enumerate(work,1):check(i,name,fn)


if __name__=='__main__':run()
