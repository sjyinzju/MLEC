"""Refresh compact delivery metadata from the validated authoritative data.

No downloads, model fitting, original-response retention or per-row audit copies.
Run practical_validate first. Filesystem cleanup is a separate explicit action.
"""
from .common import *
from .catalogue import unit_definition
from .macro_contract import specifications

DELIVERY_VERSION='practical-research-data-v5'
METADATA=ROOT/'data/metadata'


def sources(registry):
    path=METADATA/'source_registry.parquet';old=pd.read_parquet(path)
    if 'status' in old:old=old[old.status.isin(['ok','CATALOGUED','ACCEPTED'])]
    old=old.rename(columns={'evidence_path':'legacy_evidence_path'})
    columns=['source_id','source_kind','source_name','url','endpoint','legacy_evidence_path','sha256']
    rows=old.reindex(columns=columns).to_dict('records')
    for r in registry['datasets']:
        url=r.get('source_definition')
        if url:rows.append(dict(source_id=r['dataset_id'],source_kind='provider_definition',url=url))
    f=pd.read_parquet(MACRO/'macro_facts.parquet')
    for r in f[['source_name','source_url']].dropna(subset=['source_url']).drop_duplicates().itertuples(index=False):
        rows.append(dict(source_id='url:'+hashlib.sha256(r.source_url.encode()).hexdigest()[:24],
            source_name=r.source_name,source_kind='macro_publication',url=r.source_url))
    rows.append(dict(source_id='szse:official_daily_statistics',source_kind='official_exchange_report',
        url='http://www.szse.cn/api/report/ShowReport/data',source_name='深圳证券交易所市场总貌历史日报'))
    out=pd.DataFrame(rows).reindex(columns=columns).drop_duplicates()
    out['retention']='Source reference only. Legacy evidence paths identify deleted original objects; no offline snapshot is promised.'
    frame(path,out)
    edges=[dict(child=r['authority_path'],parent=r.get('source_definition') or 'source_registry',
        edge_type='source_definition',evidence='data/metadata/source_registry.parquet') for r in registry['datasets']]
    for r in f[f.parent_record_ids.notna()&f.parent_record_ids.ne('[]')].itertuples(index=False):
        for parent in json.loads(r.parent_record_ids):
            edges.append(dict(child=r.source_record_id,parent=parent,edge_type='derived_numeric_parent',
                evidence='data/standardized/macro/v4/macro_facts.parquet'))
    frame(METADATA/'data_lineage.parquet',pd.DataFrame(edges).drop_duplicates())


def build():
    validation=read(METADATA/'final_validation.json');assert validation['technical_checks_passed']
    registry=read(METADATA/'dataset_registry.json');stats={r['dataset_id']:r for r in validation['tables']}
    dictionary=pd.read_parquet(METADATA/'field_dictionary.parquet').set_index(['dataset_id','field'])
    fields=[];schemas={};quality=[]
    reasons={
        'index_daily':('UNRESOLVED_REQUIRED_DATA','Seven complete date grids; two CSI1000 dates have unresolved source price conflicts. Exclude dependent price windows.'),
        'stock_daily_basic':('UNRESOLVED_REQUIRED_DATA','13936 PB and 16 free-turnover values missing; 2840 share-basis field exceptions. PE/PE_TTM source nulls are undefined-or-unavailable, not all independently proven structural.'),
        'stock_adjustment':('DATA READY','All observed quote dates have positive factors; official action boundaries repaired. Outside-identity provider rows are excluded using market_data_quality. Historical reconstruction, not original-vintage certification.'),
        'stock_moneyflow':('UNAVAILABLE_OPTIONAL_DATA','2558 observed trading dates still absent after bounded targeted sourcing; 82 off-quote rows excluded by field quality. Order-size proxy, not investor cash accounting.'),
        'exchange_activity_sz':('UNRESOLVED_REQUIRED_DATA','Monetary stock totals cover 3095 dates; 2014 volume and ChiNext share quantities remain absent. Six stock-category units verified; nonstock units not certified.'),
        'index_constituents_history':('QUALIFIED','38 announcement events support SZSE Component Index intervals only; use monthly_snapshot for all seven indices, never current-membership backfill.'),
        'index_weights_history':('QUALIFIED','Seven indices each have 140 monthly snapshots from 2015-01 to 2026-08. Weights are snapshot percentages, not exact daily weights. No 2014 snapshot reconstruction.'),
        'macro_facts':('UNRESOLVED_REQUIRED_DATA','Same-definition CGB 2014 quotes and 40 CNY trade periods unresolved; valid historical reconstructions remain usable independently.'),
        'stock_dividend_events':('QUALIFIED','393 source events lack announcement dates, including proposals and historical implemented events. Source-record ID is the non-null key; absent announcement time is not historical availability. Use actual event implementation dates for action analysis.'),
    }
    for r in registry['datasets']:
        s=stats[r['dataset_id']];status,reason=reasons.get(r['dataset_id'],('QUALIFIED','Validated schema/key and full-table field counts; historical reconstruction with declared source/field limitations.'))
        r['required_fields']=list(dict.fromkeys(r['required_fields']+r['primary_key']))
        if r['dataset_id'] in ['macro_vintages','macro_release_events','macro_quality']:status,reason=reasons['macro_facts']
        r.update(version=DELIVERY_VERSION,rows=s['rows'],actual_data_start=s['start'],actual_data_end=s['end'],
            absent_fields=[],duplicate_key_excess=0,quality_status=status,quality_reason=reason,
            original_vintage_pit_certified=False,schema_id=r['dataset_id']+'@v5')
        schemas[r['schema_id']]=dict(authority_path=r['authority_path'],primary_key=r['primary_key'],columns=s['columns'])
        quality.append({k:r[k] for k in ['dataset_id','domain','quality_status','quality_reason','rows','duplicate_key_excess']})
        for col,dtype in s['columns'].items():
            key=(r['dataset_id'],col)
            if key in dictionary.index:entry=dictionary.loc[key].to_dict()
            else:
                unit,definition=unit_definition(*key)
                entry=dict(unit=unit,definition=definition,quality_status='DEFINED_REQUIRES_ROW_QUALITY',source_definition=r.get('source_definition'))
            entry.update(dataset_id=key[0],field=col,physical_type=dtype,rows=s['rows'],nulls=s['nulls'][col],
                required=col in r['required_fields'],version=DELIVERY_VERSION)
            if col=='monetary_reported_quantum_cny':entry.update(unit='CNY',definition='Official table display precision after conversion to CNY; not measurement error.')
            if col in ['evidence_path','source_path','rule_evidence_path','factor_evidence_path','scope_definition_evidence','definition_evidence_path']:
                entry['definition']='Legacy source locator or compact metadata reference; original downloads were removed. Resolve available public links with source_registry, not filesystem existence.'
            if col=='source_url':entry['definition']='Public originating source URL; no retained original response is promised.'
            entry.pop('definition_evidence_path',None);fields.append(entry)
    registry.update(version=DELIVERY_VERSION,intermediate_provider_snapshots=[],formal_certification='UNRESOLVED_REQUIRED_DATA',
        interface='scripts.final_data_foundation.research_inputs.load_dataset',
        validation='data/metadata/final_validation.json',completeness='data/metadata/data_completeness.csv',
        historical_inputs_policy='Earlier v1 processed inputs used by existing formal experiments are preserved. Superseded v3 processing copies are removed; current authority is v5.',
        source_retention='Compact source links, definitions and numeric derivation parents; no original response or offline byte-reproduction claim.')
    registry['feature_authorities']={
        'frozen_market':'data/research_v2/market_features_weekly.parquet',
        'frozen_targets':'data/research_v2/prediction_targets_weekly.parquet',
        'frozen_folds':'data/research_v2/fold_membership.parquet',
        'market_continuous':'data/features/market/v4/market_extensions_weekly.parquet',
        'market_daily':'data/features/market/v4/all_a_daily.parquet',
        'index_dimensions':'data/features/market/v4/index_dimensions_daily.parquet',
        'market_correlation':'data/features/market/v4/all_a_correlation_weekly.parquet',
        'macro_by_quality':'data/features/macro/v4/{quality}/macro_weekly.parquet',
        'macro_lineage_by_quality':'data/features/macro/v4/{quality}/macro_lineage.parquet',
        'sample_masks':'data/datasets/sample_manifests/v4/{quality}/{information_set}.parquet'}
    write(METADATA/'dataset_registry.json',registry)
    write(METADATA/'schema_registry.json',dict(version=DELIVERY_VERSION,schemas=schemas,
        time_policy='Trade date YYYYMMDD; economic period/date distinct from timezone-aware release/capture/effective availability. Historical quote clock is explicit; no original-vintage claim.'))
    frame(METADATA/'field_dictionary.parquet',pd.DataFrame(fields));frame(METADATA/'quality_registry.parquet',pd.DataFrame(quality))
    sources(registry)
    c=db();matrix=pd.read_parquet(META/'data_requirements_matrix.parquet')
    matrix['candidate_rows']=matrix.numeric_candidate_rows
    matrix['search_evidence']='data/metadata/remaining_gaps.json'
    frame(META/'data_requirements_matrix.parquet',matrix)
    # Macro periods and market date/field denominators are different units;
    # retain this distinction instead of publishing a misleading grand total.
    specs={s['series_id']:s for s in specifications()};rows=[]
    for sid,g in matrix.groupby('series_id'):
        good=g.status.eq('ACCEPTED');struct=g.status.eq('STRUCTURAL_NA');expected=int((~struct).sum());n=int(good.sum())
        rows.append(dict(domain='macro',indicator=sid,name=specs[sid]['series_name'],group=specs[sid]['series_group'],
            start=str(g.period_end.min().date()),end=str(g.period_end.max().date()),count_unit='legal statistical periods',
            expected_periods=expected,available_periods=n,completeness=n/expected if expected else None,
            missing_periods=expected-n,structural_periods=int(struct.sum()),historical_reconstructed=True,
            usable='qualified periods only' if n<expected else 'yes under declared timing/scope policy',
            status='UNRESOLVED_REQUIRED_DATA' if n<expected else 'DATA READY'))
    def market_row(name,expected,available,start=START,end=END,structural=0,status=None,note=''):
        rows.append(dict(domain='market',indicator=name,name=name,group='market',start=start,end=end,
            count_unit='security-date or explicitly named field observations',expected_periods=expected,available_periods=available,
            completeness=available/expected if expected else None,missing_periods=expected-available if expected is not None else None,
            structural_periods=structural,historical_reconstructed=True,usable=note or 'yes under declared reconstruction/quality policy',
            status=status or ('DATA READY' if available==expected else 'UNRESOLVED_REQUIRED_DATA')))
    for code,g in c.execute('SELECT ts_code,trade_date FROM read_parquet(?)',[str(MARKET/'index_daily/*.parquet')]).df().groupby('ts_code'):
        market_row('index_daily:'+code,3095,len(g),note='CSI1000 has 2 conflicted dates and prelaunch backcast' if code=='000852.SH' else '',status='UNRESOLVED_REQUIRED_DATA' if code=='000852.SH' else 'DATA READY')
    n=stats['stock_daily']['rows'];market_row('stock_daily',n,n)
    market_row('factor_on_observed_stock_quote',n,n)
    basic=stats['stock_daily_basic'];q=pd.read_parquet(MARKET/'market_data_quality.parquet')
    for field in ['turnover_rate','turnover_rate_f','total_mv','circ_mv','pb','pe','pe_ttm']:
        structural=int((q.field.eq(field)&q.quality_status.eq('STRUCTURAL_NONPOSITIVE_BOOK_EQUITY')).sum())
        nulls=basic['nulls'][field];market_row('stock_daily_basic:'+field,n-structural,n-nulls,structural=structural,
            status='UNRESOLVED_REQUIRED_DATA' if field in ['turnover_rate','turnover_rate_f','total_mv','circ_mv','pb','pe','pe_ttm'] else None,
            note='Non-null is not certification: apply share-basis quality masks. PE blanks are undefined OR unavailable; their structural fraction is not certified.')
    money=c.execute('''SELECT count(*) FROM read_parquet(?) q ANTI JOIN
        (SELECT m.trade_date,i.instrument_id FROM read_parquet(?) m
         JOIN (SELECT DISTINCT ts_code,instrument_id FROM read_parquet(?)) i USING(ts_code)) m
        USING(instrument_id,trade_date)''',
        [str(MARKET/'stock_daily_observations/*.parquet'),str(MARKET/'stock_moneyflow/*.parquet'),str(MARKET/'stock_master_history.parquet')]).fetchone()[0]
    market_row('stock_moneyflow_on_traded_dates',n,n-money,status='UNAVAILABLE_OPTIONAL_DATA')
    for cat in ['股票','创业板A股']:
        for field in ['amount','total_mv','float_mv','vol','total_share','float_share']:
            got=c.execute('SELECT count("'+field+'") FROM read_parquet(?,union_by_name=true) WHERE ts_code=?',[str(MARKET/'exchange_activity_sz/*.parquet'),cat]).fetchone()[0]
            market_row('szse:'+cat+':'+field,3095,got)
    market_row('sse_statistics_dates',3095,3095)
    weights=c.execute("SELECT index_code,count(DISTINCT substr(trade_date,1,6)) FROM read_parquet(?) GROUP BY 1",[str(MARKET/'index_weights_history/*.parquet')]).fetchall()
    for code,count in weights:market_row('monthly_index_snapshot:'+code,140,count,'20150130','20260831',note='Monthly percentage-weight snapshot; max carry 45 days. No exact daily weights or 2014 snapshots claimed.')
    for name,path in registry['feature_authorities'].items():
        if name in ['frozen_market','market_continuous','market_correlation']:
            market_row(name,599,len(pd.read_parquet(ROOT/path)),'20150109','20260918',note='Candidate time points retained; use eligibility mask, not all 599 are training-eligible.')
    pd.DataFrame(rows).to_csv(METADATA/'data_completeness.csv',index=False,encoding='utf-8-sig')
    gaps=matrix[~matrix.status.isin(['ACCEPTED','STRUCTURAL_NA'])][['series_id','period_end','status','reason','numeric_candidate_rows']]
    frame(METADATA/'unresolved_macro_periods.parquet',gaps)
    contract=read(ROOT/'config/data/market_requirements.json');contract['version']=DELIVERY_VERSION
    byid={r['dataset_id']:r for r in registry['datasets']}
    for r in contract['datasets']:
        final=byid[r['dataset_id']]
        for k in ['quality_status','actual_data_start','actual_data_end','authority_path']:r[k]=final[k]
        r['coverage_evidence']='data/metadata/data_completeness.csv'
        r['contract_version']=DELIVERY_VERSION
        r['revision_policy']='Historical reconstruction with compact source/correction metadata. No complete original-vintage archive retained; v2 frozen.'
    write(ROOT/'config/data/market_requirements.json',contract)
    combined=pd.read_parquet(METADATA/'research_data_requirements.parquet')
    for idx,r in combined.iterrows():
        if r.domain=='M' and r.dataset_id in byid:
            final=byid[r.dataset_id]
            for k in ['quality_status','actual_data_start','actual_data_end','authority_path']:combined.at[idx,k]=final[k]
            combined.at[idx,'primary_key']=json.dumps(final['primary_key'])
        combined.at[idx,'coverage_evidence']='data/metadata/data_completeness.csv'
        combined.at[idx,'contract_version']=DELIVERY_VERSION
    frame(METADATA/'research_data_requirements.parquet',combined)
    policy=read(METADATA/'practical_research_policy.json');policy['status']='UNRESOLVED_REQUIRED_DATA';policy.pop('remaining_work',None)
    policy['remaining_gaps']='data/metadata/remaining_gaps.json'
    policy['market_repairs'].update(pb_nonpositive_book_equity_records=61368,szse_quantity_fields_added=6862,
        szse_zero_category_rows_repaired=4,sse_2014_dates_added=245,sse_2014_rows_added=1960)
    write(METADATA/'practical_research_policy.json',policy)
    frame(METADATA/'sample_eligibility_summary.parquet',pd.DataFrame(validation['eligibility']))
    c.close();print('DELIVERY_METADATA',len(registry['datasets']),'datasets',len(fields),'fields',len(rows),'completeness rows',flush=True)


if __name__=='__main__':build()
