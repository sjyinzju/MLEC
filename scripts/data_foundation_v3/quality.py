"""Period-level certification, source reconciliation, and immutable evidence index."""
import itertools
import json
from collections import Counter
import numpy as np
import pandas as pd
from .common import ROOT,RAW,STANDARD,METADATA,AUDIT,CONFIG,read_json,write_json,save_frame,digest,now
from .requirements import specifications
from .scopes import TSF_BASE,TSF_REGIMES

STATUSES={'NOT_COLLECTED','SOURCE_UNREACHABLE','PARSING_FAILED','SEMANTIC_ERROR','VALUE_CONFLICT','RELEASE_UNVERIFIED','VINTAGE_UNVERIFIED','STRUCTURAL_NA','SOURCE_DISCONTINUED','VERIFIED_UNAVAILABLE','ACCEPTED'}
ACCEPTED=['strict_pit_eligible','conservative_release_reconstructed']

def structural(sid,day):
    concept=sid.split('__scope_')[0]
    if concept in TSF_BASE:
        scope=sid.split('__scope_')[1] if '__scope_' in sid else '201912'
        regime=next((r for r in TSF_REGIMES if r[0]==scope),None)
        if regime and not pd.Timestamp(regime[1])<=day<=pd.Timestamp(regime[2]):return 'Outside this explicitly separated TSF statistical definition; see the other scope series'
        sid=concept
    if sid in ['industrial_va_yoy','retail_sales_yoy'] and day.month in [1,2]:return 'Official January-February combined statistics, no independent monthly value'
    if sid in ['industrial_va_ytd_yoy','retail_sales_ytd_yoy','fai_ytd_yoy'] and day.month==1:return 'No separate January release under combined January-February survey'
    if sid=='m1_new_yoy' and day<pd.Timestamp('2025-01-01'):return 'New M1 definition starts January 2025'
    if sid=='m1_yoy' and day>=pd.Timestamp('2025-01-01'):return 'Old M1 definition ends December 2024; never splice new definition'
    if sid=='lpr_1y' and day<pd.Timestamp('2019-08-01'):return 'New LPR mechanism begins 2019-08-20'
    if sid=='dr007' and day<pd.Timestamp('2014-12-15'):return 'DR deposit-institution series not introduced before 2014-12-15'
    if sid in ['tsf_stock','tsf_stock_yoy'] and (day<pd.Timestamp('2014-12-01') or (day.year==2015 and day.month%3)):
        return 'Stock first published for 2014 year end; 2015 quarterly publication, monthly from 2016; retrospective compiled values remain separate'
    # GAC releases January and February together, but its later monthly tables
    # can contain separate months. A combined press release does NOT establish
    # structural absence of monthly trade values. Uncollected months stay gaps.
    return None

def completeness(f=None):
    f=f if f is not None else pd.read_parquet(STANDARD/'macro_facts.parquet')
    calendar=pd.read_parquet(ROOT/'data/metadata/market/sse_calendar.parquet');days=pd.to_datetime(calendar.loc[calendar.is_open.eq(1),'date'])
    days=days[(days>='2014-01-01')&(days<='2026-09-22')]
    groups={(sid,pd.Timestamp(period)):g for (sid,period),g in f.groupby(['series_id','period_end'])};rows=[]
    for spec in specifications():
        if not spec.get('required',True):continue
        sid=spec['series_id'];freq=spec['frequency'];grid=days if freq=='D' else pd.date_range('2014-01-01','2026-09-30',freq='QE' if freq=='Q' else 'ME')
        for day in grid:
            g=groups.get((sid,day));reason=structural(sid,day);status='STRUCTURAL_NA' if reason else None
            concept=sid.split('__scope_')[0]
            if concept in TSF_BASE:
                uncertain=groups.get((concept+'__scope_unverified',day))
                if uncertain is not None:g=pd.concat([g,uncertain],ignore_index=True) if g is not None else uncertain
            good=g[g.quality_status.isin(ACCEPTED)&g.certification_status.ne('VALUE_CONFLICT')] if g is not None else f.iloc[:0]
            strict=good[good.quality_status.eq('strict_pit_eligible')]
            if not status:
                if len(good):status='ACCEPTED';reason='Historical announcement or explicitly qualified quote/reprint evidence retained'
                elif g is not None and g.certification_status.eq('VALUE_CONFLICT').any():status='VALUE_CONFLICT';reason='Same-time certified values conflict; quarantined'
                elif g is not None and g.quality_status.eq('blocked').all():status='SEMANTIC_ERROR';reason='Candidate definition/field does not establish this required measure'
                elif g is not None:status='VINTAGE_UNVERIFIED';reason='Numeric history retained, but first-release/revision history is not certified; no backdating'
                elif sid in ['dr007','cgb_1y','cgb_10y','term_spread_10y_1y']:status='SOURCE_UNREACHABLE';reason='Public archive request/navigation attempted; full requested older history not returned; see source attempt ledger'
                else:status='NOT_COLLECTED';reason='No certified value or candidate for required period; further targeted source collection remains necessary'
            rows.append({'series_id':sid,'period_end':day,'frequency':freq,'status':status,'reason':reason,'candidate_rows':0 if g is None else len(g),'accepted_rows':len(good),'strict_rows':len(strict),
              'record_ids':json.dumps([] if g is None else sorted(g.source_record_id.tolist())),
              'earliest_accepted_available_at':good.research_available_at.min() if len(good) else pd.NaT,
              'source_priority':spec['source_priority'],'search_evidence':'audit/data_foundation_v3/source_manifest.json',
              'required_window':'prehistory_2014' if day.year<2015 else 'initial_2015_2019' if day.year<2020 else 'development_2020_2022' if day.year<2023 else 'reserved_2023_plus',
              'strict_status':'ACCEPTED' if len(strict) else ('STRUCTURAL_NA' if status=='STRUCTURAL_NA' else 'VINTAGE_UNVERIFIED' if len(good) else status)})
    matrix=pd.DataFrame(rows);save_frame(AUDIT/'missing_periods.parquet',matrix)
    matrix.to_csv(AUDIT/'missing_periods.csv',index=False,encoding='utf-8-sig')
    save_frame(METADATA/'data_requirements_matrix.parquet',matrix)
    summary=matrix.groupby(['series_id','status']).size().unstack(fill_value=0).reset_index()
    summary.to_csv(AUDIT/'completeness_summary.csv',index=False,encoding='utf-8-sig')
    issues=matrix[~matrix.status.isin(['ACCEPTED','STRUCTURAL_NA'])].groupby(['series_id','status','reason']).agg(periods=('period_end','count'),start=('period_end','min'),end=('period_end','max')).reset_index()
    write_json(AUDIT/'unresolved_issues.json',issues.to_dict('records'))
    return matrix,summary

def reconcile(f=None):
    f=f.copy() if f is not None else pd.read_parquet(STANDARD/'macro_facts.parquet')
    pairs=[];conflicts=set()
    for (sid,period),g in f.groupby(['series_id','period_end']):
        # One record per concrete source/vintage/value, no suppression of versions.
        g=g.drop_duplicates(['source_id','vintage_id','value','quality_status'])
        for a,b in itertools.combinations(g.to_dict('records'),2):
            diff=abs(a['value']-b['value']);same_definition=a['unit']==b['unit'] and a['currency']==b['currency'] and a['measure_type']==b['measure_type']
            quantum=max([v for v in [a.get('reported_quantum',0),b.get('reported_quantum',0)] if pd.notna(v)]+[0])
            tolerance=max(quantum/2,0.05 if a['unit'] in ['%','index','percentage_points'] else 0.00005 if a['unit']=='CNY/USD' else 0.005)
            if not same_definition or 'blocked' in [a['quality_status'],b['quality_status']]:status='SEMANTIC_ERROR'
            elif diff<1e-10:status='EXACT_MATCH'
            elif diff<=tolerance+1e-10:status='ROUNDING_ONLY'
            elif a['quality_status']=='strict_pit_eligible' and b['quality_status']=='strict_pit_eligible' and a['research_available_at']!=b['research_available_at']:status='DATED_PUBLICATION_VERSION_DIFFERENCE'
            else:status='VALUE_CONFLICT'
            if status=='VALUE_CONFLICT' and a['quality_status'] in ACCEPTED and b['quality_status'] in ACCEPTED and a['research_available_at']==b['research_available_at']:
                conflicts.update([a['source_record_id'],b['source_record_id']])
            pairs.append({'series_id':sid,'period_end':period,'left_record_id':a['source_record_id'],'right_record_id':b['source_record_id'],'left_value':a['value'],'right_value':b['value'],'absolute_difference':diff,'classification':status,'rounding_tolerance':tolerance,
              'left_available_at':a['research_available_at'],'right_available_at':b['research_available_at'],
              'interpretation':'Later dated publication is retained at its actual availability; no inferred original release' if status=='DATED_PUBLICATION_VERSION_DIFFERENCE' else 'A latest archive disagreement is not automatically called a revision; both records are retained'})
    d=pd.DataFrame(pairs);save_frame(AUDIT/'source_reconciliation.parquet',d)
    d.to_csv(AUDIT/'source_reconciliation.csv',index=False,encoding='utf-8-sig')
    if conflicts:
        f.loc[f.source_record_id.isin(conflicts),'certification_status']='VALUE_CONFLICT'
        save_frame(STANDARD/'macro_facts.parquet',f)
    write_json(AUDIT/'reconciliation_summary.json',{'counts':dict(Counter(d.classification)),'same_time_certified_conflict_ids':sorted(conflicts),'warning':'Different source values are never silently overwritten or automatically declared genuine revisions'})
    return d

def register():
    f=pd.read_parquet(STANDARD/'macro_facts.parquet');raw=[]
    catalog=pd.DataFrame(specifications())
    coverage=f.groupby('series_id').agg(observed_start=('period_end','min'),observed_end=('period_end','max'),source_versions=('value','size')).reset_index()
    save_frame(METADATA/'series_catalog.parquet',catalog.merge(coverage,on='series_id',how='left',validate='one_to_one'))
    for path,g in f.groupby('evidence_path'):
        p=ROOT/path
        raw.append({'path':path,'exists':p.exists(),'sha256':digest(p) if p.exists() else None,'bytes':p.stat().st_size if p.exists() else None,'record_count':len(g),'source_urls':sorted(g.source_url.unique()),'retrieved_at':str(g.retrieved_at.min())})
    requests=[read_json(p) for p in sorted((RAW/'requests').glob('*.json'))]
    dependencies=[]
    for p in sorted((ROOT/'data/raw/macro').rglob('*')):
        if not p.is_file() or p.suffix in ['.zip','.pyc'] or '__pycache__' in p.parts:continue
        dependencies.append({'path':p.relative_to(ROOT).as_posix(),'sha256':digest(p),'bytes':p.stat().st_size})
    pinned=METADATA/'legacy_retrieval_times.json'
    dependencies.append({'path':pinned.relative_to(ROOT).as_posix(),'sha256':digest(pinned),'bytes':pinned.stat().st_size})
    write_json(AUDIT/'source_manifest.json',{'created_at':now(),'research_evidence_files':raw,'offline_input_files':dependencies,'requests':requests,'source_registry':'data/metadata/foundation_v3/sources.parquet','cache_policy':'All raw objects retained locally; large HTML/PDF caches may be ignored by Git; offline reconstruction requires the exact listed objects and hashes; retrieval timestamps pinned in data/metadata/foundation_v3/legacy_retrieval_times.json'})
    sources=f.groupby(['source_id','source_url','source_name','source_class'],dropna=False).agg(rows=('value','size'),first_observation=('period_end','min'),last_observation=('period_end','max')).reset_index();save_frame(METADATA/'sources.parquet',sources)
    rows=[]
    for folder in [STANDARD,METADATA]:
        for p in sorted(folder.rglob('*.parquet')):
            d=pd.read_parquet(p);rel=p.relative_to(ROOT).as_posix()
            key=['source_record_id'] if p.name in ['macro_facts.parquet','macro_vintages.parquet','macro_release_events.parquet'] else ['sample_id','feature'] if p.name=='macro_lineage.parquet' else ['sample_id','horizon'] if p.name in ['sample_eligibility.parquet','prediction_targets_weekly.parquet'] else ['sample_id'] if 'weekly' in p.name or p.name=='features.parquet' else ['series_id','period_end'] if p.name=='data_requirements_matrix.parquet' else ['series_id'] if p.name=='series_catalog.parquet' else ['source_id','source_url','source_name','source_class'] if p.name=='sources.parquet' else []
            if not key:
                candidates=[['fold_id','sample_id','horizon','role'],['sample_id','horizon','episode_id'],['episode_id'],['fold_id'],['date'],['cal_date']]
                key=next((cols for cols in candidates if set(cols)<=set(d) and not d.duplicated(cols).any()),[])
            if key and d.duplicated(key).any():raise ValueError('Registry duplicate primary key: '+rel)
            rows.append({'dataset_id':rel.removesuffix('.parquet').replace('/','.'),'version':'data-foundation-v3.0.0','path':rel,'rows':len(d),'sha256':digest(p),'schema':{c:str(t) for c,t in d.dtypes.items()},'primary_key':key,'created_at':now(),
              'generator':'source-standardization-library','upstream':'See source_manifest and migration_manifest; research consumer is scripts.market_state',
              'coverage':{c:[str(d[c].min()),str(d[c].max())] for c in ['asof_time','period_end'] if c in d},
              'quality':'quality dimension in rows or dataset manifest; never assumes all strict PIT','historical_pit':'mixed; quote archive/reprint levels explicitly qualified','limitations':'See data_requirements_matrix and remaining_data_limitations.md','research_tasks':'future configurable information groups and data-quality comparisons; no model run'})
    write_json(METADATA/'dataset_registry.json',rows)
    return rows
