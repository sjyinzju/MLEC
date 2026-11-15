"""One authority per dataset, complete physical schema and population field audit."""
from .common import *
from .contracts import TABLES
from .collect import PUBLIC
from .provider import API_RAW

ALIASES={s:s+'_observations' for s in ['stock_daily','stock_daily_basic','stock_adjustment']}
ALIASES['stock_limits']='stock_limits_observations'
META_FIELDS={
 'dataset_id':('identifier','Registered logical dataset authority'),
 'series_id':('identifier','Registered economic series and applicable statistical-scope variant'),
 'concept_id':('identifier','Economic concept shared by mutually exclusive statistical-scope variants'),
 'series_name':('text','Human-readable economic indicator name'),
 'series_group':('category','Research variable group in macro_requirements'),
 'unit':('unit_code','Measurement unit of the macro value, as registered per series'),
 'currency':('currency_code','Currency denomination or explicit not-applicable value from the series contract'),
 'frequency':('category','Observation frequency, distinct from publication frequency'),
 'measure_type':('category','Economic measure such as stock, flow, year-on-year rate or level'),
 'observation_date':('date','Actual quotation/fixing observation date where distinct from the period bucket'),
 'statistical_scope_id':('identifier','Applicable institutional/statistical coverage regime; changes must respect scope boundaries'),
 'scope_definition_evidence':('relative_path','Retained primary-document scope amendment and mapping evidence'),
 'release_time_basis':('text','Evidence or convention underlying the recorded publication time'),
 'revision_status':('category','Known vintage/revision relation; absence of a revision log is not evidence of no revisions'),
 'source_name':('text','Named originating publisher or retained provider'),
 'source_url':('URL','Original public resource address; retained evidence_path is the offline authority'),
 'source_class':('category','Primary release, dated republication, contemporary press or historical provider snapshot'),
 'value_quality':('category','Value-extraction and numerical-validation evidence classification'),
 'time_quality':('category','Publication/availability-time evidence classification'),
 'vintage_quality':('category','Historical-original or later-version evidence classification'),
 'adjustment_note':('text','Explicit transformation, correction, scope or source limitation'),
 'original_series_id':('identifier','Retained pre-standardization series identifier'),
 'original_value':('source_native','Retained value before unit or semantic standardization; not an independent observation'),
 'claimed_available_at':('Asia/Shanghai timestamp','Earlier claimed availability retained for audit; not used in preference to certified research_available_at'),
 'publication_date_evidence':('source_reference','Literal/date locator supporting the publication date'),
 'reported_quantum':('per_row_unit','Last reported numerical place expressed in the standardized value unit; not a confidence interval'),
 'extracted_text':('text','Retained literal passage or serialized source cells supporting extraction'),
 'extraction_method':('text','Named extraction and review procedure'),
 'extraction_evidence':('source_reference','Retained extraction proof or document locator'),
 'parent_record_ids':('JSON identifiers','Source-record or retained-file parents of a derived observation'),
 'certification_status':('category','Record certification outcome; ACCEPTED still requires the selected temporal quality policy'),
 'data_foundation_version':('version','Version of the standardized data foundation'),
 'evidence_page':('page_number','Reviewed document page locator, as recorded by the extractor'),
 'publication_edition_order':('ordinal','Proved bulletin edition order used to distinguish values uploaded at the same time'),
 'publication_edition_evidence':('source_reference','Retained directory evidence for bulletin edition ordering'),
 'field':('identifier','Measurement column to which this quality exception applies'),
 'rule_id':('identifier','Primary-evidence certificate for a special trading-day price-limit regime'),
 'limit_rule_status':('category','Ordinary provider rule unverified, explicit no-daily-limit, or special IPO auction regime'),
 'rule_evidence_path':('JSON relative_paths','Primary announcement and contemporaneous exchange rule sources'),
 'evidence_path':('relative_path','Retained document or audit evidence, relative to repository root'),
 'source_path':('relative_path','Retained primary source document, relative to repository root'),
 'identity_evidence':('source_reference','Primary code-change document or provider master source record ID'),
 'quote_record_ids':('source_references','Source quote row IDs; multiple source aliases may be comma-separated'),
 'suspension_record_ids':('source_references','Source suspension feed IDs, nullable when absence certified by a primary document'),
 'security_type':('category','A_SHARE or CDR; CDR excluded from all-A share proxies'),
 'exchange':('category','SSE or SZSE for historical security or calendar'),
 'list_date':('YYYYMMDD','Provider listing date; independent universe certification remains qualified'),
 'delist_date':('YYYYMMDD','Provider delisting effective date; null for securities not recorded delisted'),
 'index_code':('identifier','Index whose membership or weight is described'),
 'con_code':('identifier','Member security code as supplied by the dated source'),
 'quality_record_id':('identifier','Unique dataset/record/field/status quality-exception identifier'),
 'source_id':('identifier','Origin or explicitly declared derivation'),
 'source_record_id':('identifier','Immutable source/derived row ID; follows repair lineage when derived'),
 'research_available_at':('Asia/Shanghai timestamp','Actual supported vintage availability; never automatically trade date'),
 'reconstructed_quote_at':('Asia/Shanghai timestamp','Conditional historical end-of-day convention; not original captured vintage'),
 'retrieved_at':('Asia/Shanghai timestamp','Source snapshot capture time'),
 'release_at':('Asia/Shanghai timestamp','Documented public release; nullable when unknown'),
 'vintage_id':('identifier','Retained content snapshot or provider batch'),
 'quality_status':('category','Admission requires explicit quality policy; nonnull value does not imply certification'),
 'quality_reason':('text','Qualification or blockage explanation'),
 'trade_date':('YYYYMMDD','Exchange observation date, distinct from vintage availability'),
 'cal_date':('YYYYMMDD','Exchange calendar date'),
 'ts_code':('identifier','Historical effective code in canonical stock observations/master/status; provider-supplied alias in other source tables, requiring master interval reconciliation before use'),
 'instrument_id':('identifier','Legal security identity across verified code changes'),
 'valid_from':('date','Inclusive validity start'), 'valid_to':('date','Exclusive validity end; ex-post end must not be used as advance knowledge'),
 'period_start':('date','Economic observation period start'),'period_end':('date','Economic observation period end'),
 'amount_cny':('CNY','Daily turnover amount converted from provider thousand CNY'),
 'volume_shares':('share','Daily volume converted from provider lots of 100'),
 'adj_factor':('relative_factor','Provider multiplicative adjustment scale with explicit primary-evidence repair; not strict captured vintage'),
 'pre_close':('CNY/share or index_point','Exchange reference previous close; can differ from previous traded close due to corporate actions'),
 'pct_chg':('percent','100*(close/pre_close-1), exchange reference return'),
 'weight':('percent','Observed index-weight snapshot only; no interpolation to effective daily weights'),
 'status':('category','Observed, explicitly evidenced suspension, or unresolved; never zero-filled'),
 'value':('per_row_unit','Value governed by series_id, unit, currency and measure_type'),
}


def authority(dataset):
    p=MARKET/(ALIASES.get(dataset,dataset)+'.parquet')
    return p if p.exists() else MARKET/ALIASES.get(dataset,dataset)/'*.parquet'


def relation(path):return 'read_parquet('+qs(path)+',union_by_name=true,hive_partitioning=false)'


def unit_definition(dataset,field):
    if field in META_FIELDS:return META_FIELDS[field]
    if dataset=='index_identity' and field=='base_point':return ('index_point','Index base level, as described in the retained index_basic definition')
    if dataset=='stock_connect_top10' and field=='rank':return ('ordinal','Provider ranking position, as described in the retained hsgt_top10 definition')
    if dataset=='exchange_activity_sz' and field in ['amount','total_mv','float_mv']:
        return ('CNY','SZSE category monetary value in yuan; official daily headers and comparisons in data/metadata/szse_currency_basis.parquet. Newly added official daily values have 1,000,000 CNY display quantum.')
    if dataset=='exchange_activity_sz' and field in ['vol','total_share','float_share']:
        return ('shares (stock categories only)','Stock-category quantity verified against official 2020-03 monthly turnover and listed-security share counts; data/metadata/szse_stock_unit_basis.json. Nonstock categories are outside this unit certification. Missing dates/fields remain explicit.')
    if field in ['open','high','low','close','change']:return ('index_point' if dataset.startswith('index_') else 'CNY/share','Unadjusted price; index series is price index, excluding reinvested cash dividends')
    if field in ['turnover_rate','turnover_rate_f']:return ('percent','Provider turnover against float/free-float share denominator; denominator semantics require field quality check')
    if field in ['pe','pe_ttm','pb','ps','ps_ttm']:return ('ratio','Provider valuation ratio; PE may be undefined for losses, other missingness is not automatically waived')
    if field in ['total_share','float_share','free_share']:return ('10000 shares','Provider total/float/free-float share basis; basis and precision issues remain in quality registry')
    if field in ['total_mv','circ_mv','float_mv']:
        return ('CNY' if dataset=='index_daily_basic' else '10000 CNY' if dataset=='stock_daily_basic' else '100000000 CNY' if dataset=='exchange_activity_sh' else 'SOURCE_DEFINITION_REQUIRED','Provider market capitalization; share class basis must be independently established')
    if field in ['amount','vol'] and dataset in ['stock_daily','index_daily']:
        return ('1000 CNY' if field=='amount' else '100 shares','Preserved provider unit; normalized companion column available')
    if field.startswith('provider_') or field.startswith('_'):return ('source_native','Audit-only source field; not admitted automatically')
    if field in ['rzye','rqye','rzrqye','rzmre','rzche']:return ('CNY','Margin trading lending/short-sale balance or flow, per registered provider definition')
    if field=='net_mf_amount':return ('10000 CNY','Provider-classified net money flow, not independently verified investor cash flow')
    if field=='net_mf_vol':return ('100 shares','Provider-classified net order volume')
    if field in ['up_limit','down_limit']:return ('CNY/share','Ordinary provider daily price bound; certified no-limit/special IPO auction days are NULL and require limit_rule_status. Original provider bounds retained separately; session auction controls are not ordinary fixed daily limits.')
    if field=='cash_div_tax':return ('CNY/share','Pretax per-share cash distribution')
    if field=='stk_div':return ('shares/share','Per-share stock dividend/capitalisation ratio')
    return ('see_source_contract','Preserved source/lineage field; use only according to linked source definition, never infer unit from name')


def build():
    from .contracts import build as contract_build
    contract_build();c=db();datasets=[];fields=[];schemas={};quality=[]
    definitions={(r['endpoint'],r['field']):r for r in read(PUBLIC/'provider_field_definitions.json')}
    market=read(ROOT/'config/data/market_requirements.json');macro=read(ROOT/'config/data/macro_requirements.json')
    plans=[(r['dataset_id'],'M',authority(r['dataset_id']),r) for r in market['datasets']]
    if (MARKET/'market_data_quality.parquet').exists():
        plans.append(('market_data_quality','M',MARKET/'market_data_quality.parquet',{'primary_key':['quality_record_id'],
          'required_fields':['quality_record_id','dataset_id','instrument_id','trade_date','field','quality_status','quality_reason','evidence_path'],
          'source_definition':'scripts/final_data_foundation/market_quality.py','required':True}))
    for name in ['macro_facts','macro_vintages','macro_release_events','macro_quality']:
        plans.append((name,'Z',MACRO/(name+'.parquet'),{'primary_key':['source_record_id'],'required_fields':['source_record_id','series_id','period_end'],'source_definition':'config/data/macro_requirements.json','required':True}))
    for name,domain,path,contract in plans:
        rel=relation(path);schema=c.execute('DESCRIBE SELECT * FROM '+rel).df();cols=schema.column_name.tolist()
        counts=c.execute('SELECT count(*),'+','.join('count(*) FILTER(WHERE "'+f+'" IS NULL)' for f in cols)+' FROM '+rel).fetchone();n=counts[0]
        date=next((x for x in ['trade_date','period_end','cal_date','valid_from','start_date','list_date','ann_date'] if x in cols),None)
        bounds=c.execute('SELECT min("'+date+'"),max("'+date+'") FROM '+rel).fetchone() if date else (None,None)
        missing=sorted(set(contract['required_fields'])-set(cols));keys=contract['primary_key']
        duplicates=c.execute('SELECT coalesce(sum(n-1),0) FROM (SELECT count(*) n FROM '+rel+' GROUP BY '+','.join('"'+k+'"' for k in keys)+' HAVING count(*)>1)').fetchone()[0] if set(keys)<=set(cols) else None
        status='FAIL' if missing or duplicates else 'QUALIFIED'
        reason='Full physical schema and primary key inspected; research certification remains conditional on domain/field/source/temporal evidence.'
        if name=='index_constituents_history':reason='399001 official-event reconstruction only, 2015-05-20 onward; event catalogue completeness unproved and other six indices missing effective histories.'
        if name=='index_weights_history':reason='Observed monthly snapshots only; no exact daily effective weights.'
        if name=='stock_adjustment':reason='Mixed-vintage and one omitted official action repaired; remaining corporate-action/precision/basis qualifications retained.'
        if name=='stock_master_history':reason='Official code-effective intervals plus provider listing/delisting snapshot. Descriptive name/industry/area fields remain snapshot attributes; historical names must use stock_name_history through verified aliases. Independent full historical universe remains unproven.'
        if name=='stock_daily_basic':reason='Seven wrong closes repaired; related valuation fields quarantined. Additional cap/share precision and denominator discrepancies unresolved.'
        if name in ['stock_limits','stock_moneyflow','margin_market','margin_security','exchange_activity_sh','exchange_activity_sz','stock_connect_top10']:
            reason+=' Full date/observed-security diagnostics: audit/final_data_foundation/market_coverage/secondary_source_limits.json; historical rule/eligible-universe and source-classification certification incomplete.'
        if name=='index_daily' and read(AUDIT/'issue_closure/index_adjudication_summary.json')['unresolved_material_prices']:
            status='FAIL';reason+=' Two unresolved CSI1000 source-price conflicts; affected continuous price windows excluded.'
        if name=='index_constituents_history':status='FAIL'
        if name=='stock_adjustment':
            x=pd.read_parquet(AUDIT/'source_reconciliation/factor_adjudications.parquet')
            if x.classification.isin(['UNRESOLVED_FACTOR_OR_REFERENCE_BASIS','OPEN_SHARE_REFORM_FACTOR_BASIS']).any():status='FAIL'
        if name=='stock_daily_basic':
            x=pd.read_parquet(AUDIT/'market_coverage/field_quality_summary.parquet')
            if x.dataset_id.eq(name).where(x.quality_status.str.startswith('BLOCKED_'),False).any():status='FAIL'
        if name=='stock_limits' and (AUDIT/'market_coverage/secondary_stock_source_summary.parquet').exists():
            x=pd.read_parquet(AUDIT/'market_coverage/secondary_stock_source_summary.parquet')
            if ((x.dataset_id==name)&~x.status.isin(['BOUNDS_AGREE_NOT_FULL_RULE_CERTIFICATION','VERIFIED_SPECIAL_RULE_NOT_ORDINARY_LIMIT'])&x.observations.gt(0)).any():status='FAIL'
        if name=='macro_facts':
            x=pd.read_parquet(META/'data_requirements_matrix.parquet')
            if (~x.status.isin(['ACCEPTED','STRUCTURAL_NA'])).any():status='FAIL'
        if name=='stock_moneyflow':
            x=pd.read_parquet(AUDIT/'market_coverage/secondary_stock_source_summary.parquet')
            if ((x.dataset_id==name)&x.status.ne('SOURCE_PRESENT_CLASSIFICATION_NOT_INDEPENDENTLY_VERIFIED')&x.observations.gt(0)).any():
                status='FAIL';reason+='; required traded-date source rows/values remain absent; unsupported off-quote flow rows are field-quarantined.'
        item=dict(dataset_id=name,domain=domain,authority_path=path.relative_to(ROOT).as_posix(),version=VERSION,rows=n,primary_key=keys,
          actual_data_start=str(bounds[0]),actual_data_end=str(bounds[1]),date_field=date,required_fields=contract['required_fields'],absent_fields=missing,
          duplicate_key_excess=int(duplicates) if duplicates is not None else None,quality_status=status,quality_reason=reason,required=contract.get('required',True),
          original_vintage_pit_certified=False,source_definition=contract['source_definition'],schema_id=name+'@v4')
        datasets.append(item);schemas[item['schema_id']]={'authority_path':item['authority_path'],'primary_key':keys,'columns':dict(zip(cols,schema.column_type)),
          'logical_mapping':{'dataset_id':'registry constant unless physical dataset_id column exists','instrument_or_series_id':next((x for x in ['series_id','instrument_id','ts_code','con_code','index_code','exchange'] if x in cols),'field_specific'),
          'value':'macro value column; market wide measurement column; constituent membership represented by row presence with value 1',
          'source_id':'physical source_id or source_path/identity_evidence/quote_record_ids/suspension_record_ids for multi-source derived observations',
          'release_at':'physical release_at if known; otherwise unknown, never implied by trade/effective date',
          'research_available_at':'physical research_available_at; status/adjudication/end-date information is retrospective and excluded from strict historical feature input',
          'unit_currency_measure':'field_dictionary plus macro_requirements; no automatic unit inference'}}
        quality.append({k:item[k] for k in ['dataset_id','domain','quality_status','quality_reason','rows','duplicate_key_excess']})
        if domain=='M':contract.update(actual_data_start=str(bounds[0]),actual_data_end=str(bounds[1]),quality_status=status,authority_path=item['authority_path'],coverage_evidence='audit/final_data_foundation/market_coverage')
        for field,typ,nulls in zip(cols,schema.column_type,counts[1:]):
            unit,meaning=unit_definition(name,field)
            definition=definitions.get((contract.get('source_dataset'),field),{})
            if definition:
                meaning=definition['source_description'] or meaning
                match=__import__('re').search(r'[（(](亿股|万股|股|亿元|万元|千元|元|万笔|手|%|％)[）)]',meaning)
                if match:unit=match[1]
                elif unit=='see_source_contract':
                    numeric=typ.startswith(('DOUBLE','FLOAT','DECIMAL','INTEGER','BIGINT','SMALLINT','HUGEINT','UBIGINT','UINTEGER'))
                    unit='SOURCE_DEFINITION_REQUIRED' if numeric else 'source_defined_text_or_category'
            if name=='stock_master_history' and field in ['name','fullname','enname','industry','area','market']:
                meaning+='; provider master snapshot attribute, NOT certified as the value throughout this historical identity interval'
            fields.append(dict(dataset_id=name,field=field,physical_type=typ,unit=unit,definition=meaning,required=field in contract['required_fields'],
              nulls=nulls,rows=n,quality_status='UNVERIFIED_FIELD_DEFINITION' if unit in ['see_source_contract','SOURCE_DEFINITION_REQUIRED'] else 'DEFINED_REQUIRES_ROW_QUALITY',
              source_definition=contract['source_definition'],definition_evidence_path=definition.get('source_path'),version=VERSION))
        print('Catalogue',name,n,'duplicate excess',duplicates,'absent',missing,flush=True)
    f=pd.read_parquet(MACRO/'macro_facts.parquet');matrix=pd.read_parquet(META/'data_requirements_matrix.parquet')
    for spec in macro['variables']:
        g=f[f.series_id.eq(spec['series_id'])];q=matrix[matrix.series_id.eq(spec['series_id'])]
        spec.update(actual_data_start=str(g.period_end.min()) if len(g) else None,quality_status='QUALIFIED' if q.status.isin(['ACCEPTED','STRUCTURAL_NA']).all() else 'FAIL',
          authority_path='data/standardized/macro/v4/macro_facts.parquet',period_status_counts=q.status.value_counts().to_dict())
    write(ROOT/'config/data/market_requirements.json',market);write(ROOT/'config/data/macro_requirements.json',macro)
    combined=pd.DataFrame(market['datasets']+macro['variables'])
    for col in combined:
        if combined[col].map(lambda x:isinstance(x,(list,dict))).any():combined[col]=combined[col].map(lambda x:json.dumps(x,ensure_ascii=False) if isinstance(x,(list,dict)) else x)
    frame(ROOT/'data/metadata/research_data_requirements.parquet',combined)
    write(ROOT/'data/metadata/dataset_registry.json',{'version':VERSION,'datasets':datasets,'intermediate_provider_snapshots':['data/standardized/market/v4/'+s for s in ALIASES],
      'frozen_market_authority':'data/research_v2','interface':'scripts.final_data_foundation.research_inputs.load_dataset','formal_certification':'INCOMPLETE'})
    write(ROOT/'data/metadata/schema_registry.json',{'version':VERSION,'schemas':schemas,'time_policy':'Trade dates are YYYYMMDD source fields; observation/period columns date; availability timestamps have timezone Asia/Shanghai. Never conflate these fields.'})
    frame(ROOT/'data/metadata/field_dictionary.parquet',pd.DataFrame(fields));frame(ROOT/'data/metadata/quality_registry.parquet',pd.DataFrame(quality))
    # Source receipt catalogue contains both successful and failed public attempts.
    sources=[]
    for folder,kind in [(PUBLIC/'requests','public_document'),(API_RAW/'requests','provider_api')]:
        for p in sorted(folder.glob('*.json')):
            r=read(p);sources.append(dict(source_id=r.get('request_id',p.stem),source_kind=kind,url=r.get('url'),endpoint=r.get('endpoint'),
              request_metadata=p.relative_to(ROOT).as_posix(),evidence_path=r.get('path'),sha256=r.get('sha256'),retrieved_at=str(r.get('retrieved_at')),
              status=r.get('status'),error=r.get('error'),version=VERSION))
    for ep in sorted(read(AUDIT/'integrity/external_manifest.json')['schemas']):
        sources.append(dict(source_id='tushare:'+ep,source_kind='read_only_external_dataset',endpoint=ep,evidence_path='audit/final_data_foundation/integrity/external_manifest.json',status='CATALOGUED',version=VERSION))
    for source,script in [('mlec:verified_quote_basic_repair','market_repairs.py'),('mlec:official_corporate_action','factor_actions.py'),('derived:primary_limit_rule','limit_rules.py')]:
        sources.append(dict(source_id=source,source_kind='evidence_bound_derivation',evidence_path='scripts/final_data_foundation/'+script,status='REGISTERED',version=VERSION))
    # Macro publisher IDs are distinct from retrieval receipts; map them explicitly.
    for row in f[['source_id','source_name','source_url']].drop_duplicates().itertuples(index=False):
        sources.append(dict(source_id=row.source_id,source_kind='macro_publisher',url=row.source_url,source_name=row.source_name,status='REGISTERED',version=VERSION))
    frame(ROOT/'data/metadata/source_registry.parquet',pd.DataFrame(sources).drop_duplicates())
    edges=[]
    for path,r in read(AUDIT/'integrity/market_standardization.json').items():edges.append(dict(child=path,parent=r['raw_path'],edge_type='standardization',evidence='audit/final_data_foundation/integrity/market_standardization.json'))
    for name in ALIASES:edges.append(dict(child='data/standardized/market/v4/'+ALIASES[name],parent='data/standardized/market/v4/'+name,edge_type='canonical_identity_and_repair',evidence='audit/final_data_foundation/issue_closure'))
    for r in pd.read_parquet(MARKET/'stock_limit_rule_evidence.parquet').itertuples(index=False):
        for parent in json.loads(r.rule_evidence_path):edges.append(dict(child='limit_rule:'+r.rule_id,parent=parent,edge_type='primary_special_price_rule',evidence=r.rule_date_evidence))
    for r in f.itertuples(index=False):
        edges.append(dict(child=r.source_record_id,parent=r.evidence_path,edge_type='macro_source_record',evidence=r.source_url))
        for parent in json.loads(r.parent_record_ids or '[]'):edges.append(dict(child=r.source_record_id,parent=parent,edge_type='macro_derivation',evidence=r.extraction_method))
    for r in datasets:edges.append(dict(child=r['dataset_id'],parent=r['authority_path'],edge_type='authority',evidence=r['schema_id']))
    for name in ['all_a_daily','all_a_correlation_weekly','index_dimensions_daily']:
        edges.append(dict(child='data/features/market/v4/'+name+'.parquet',parent='stock_daily' if name.startswith('all_a') else 'index_daily',edge_type='feature_transform',evidence='scripts/final_data_foundation/market_features.py'))
    frame(ROOT/'data/metadata/data_lineage.parquet',pd.DataFrame(edges));c.close()


if __name__=='__main__':build()
