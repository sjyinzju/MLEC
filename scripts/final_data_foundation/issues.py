"""Record-level open gaps and evidence-bound closures, never blanket completion."""
from .common import *

FIELDS=['issue_id','domain','dataset_id','series_id','instrument_id','affected_period','issue_type','severity','source_evidence','root_cause','repair_action','repair_output','verification_method','verification_result','remaining_blocker','status']


def build():
    rows=[]
    def add(**kw):rows.append({k:kw.get(k,'not_applicable') for k in FIELDS})
    matrix=pd.read_parquet(META/'data_requirements_matrix.parquet')
    for r in matrix[~matrix.status.isin(['ACCEPTED','STRUCTURAL_NA'])].itertuples(index=False):
        action='Retained direct monthly/quarterly releases, contemporary reprints and later dated tables; exact monthly/YTD/currency/scope enforced.'
        if r.series_id=='dr007':action='Collected 2947 DR007.IB weighted quotes and independently matched 30 CFETS overlap dates; historical originals remain unavailable.'
        if r.series_id.startswith(('cgb_','term_spread')):action='Searched CFETS quote archives and available local/provider history; did not substitute differently timed ChinaBond curve.'
        if r.series_id=='rmb_loans_ytd_flow':action='Blocked misidentified Eastmoney cumulative measure; direct loan YTD reports retained. Did not sum differently revised monthly values into a claimed official cumulative vintage.'
        add(issue_id='MACRO_'+r.series_id+'_'+str(r.period_end.date()),domain='Z',dataset_id='macro_facts',series_id=r.series_id,affected_period=str(r.period_end.date()),
          issue_type=r.status,severity='P0' if r.series_id in ['dr007','rmb_loans_ytd_flow'] else 'P1',source_evidence='data/raw/public_sources/v4/requests; audit/data_foundation_v3/source_requests.json; '+str(r.search_evidence),
          root_cause=r.reason,repair_action=action,repair_output='data/standardized/macro/v4/macro_facts.parquet',verification_method='Full scope-specific expected-period grid and record-level availability/quality filtering',
          verification_result='OPEN: '+r.status,remaining_blocker='Accessible original series table or archived dated publication for exact concept and period required; see source request/attempt ledgers.',status='OPEN')
    for r in read(AUDIT/'issue_closure/stock_interval_certificates.json'):
        add(issue_id=r['issue_id'],domain='M',dataset_id='stock_trading_status',instrument_id=r['instrument_code'],affected_period=r['gap_start']+'..'+r['gap_end'],
          issue_type='UNEXPLAINED_MISSING_QUOTES',severity='P0',source_evidence=json.dumps([r['start_evidence'],r['end_evidence']],ensure_ascii=False),
          root_cause='Source daily suspension feed did not cover official suspended-listing or continuous suspension interval.',repair_action='Applied source-certified suspension interval; zero synthetic quotes.',
          repair_output='data/standardized/market/v4/stock_trading_status',verification_method='Primary issuer identity, hashes, literal date assertions, full interval quote absence and endpoint checks',
          verification_result=r['verification_result'],remaining_blocker='Closed interval is retrospective; not an advance-known resumption schedule.',status='CLOSED_INDEPENDENTLY_VERIFIED')
    for r in read(ROOT/'data/raw/public_sources/v4/code_change_evidence.json'):
        add(issue_id='CODE_HISTORY_'+r['old_code'],domain='M',dataset_id='stock_master_history',instrument_id='CN-EQUITY-'+r['new_code'],
          affected_period='before '+r['effective_date'],issue_type='BACKFILLED_OR_DUPLICATED_SECURITY_CODE',severity='P0',source_evidence=r['source_path'],
          root_cause='Provider alias histories or current-code backfilling obscure the code effective on the observation date.',
          repair_action='Use official effective code intervals, retain provider code, choose one legal-security/date observation.',repair_output='data/standardized/market/v4/stock_master_history.parquet',
          verification_method='Primary announcement and canonical joins; full numeric/date/identity rechecks',verification_result=r['review_status'],remaining_blocker='No remaining issue for this evidenced code transition; global identity catalogue is separately qualified.',status='CLOSED_INDEPENDENTLY_VERIFIED')
    for r in read(AUDIT/'issue_closure/daily_basic_repairs.json'):
        add(issue_id=r['repair_id'],domain='M',dataset_id='stock_daily_basic',instrument_id=r['ts_code'],affected_period=r['trade_date'],issue_type='WRONG_CLOSE_AND_DEPENDENT_FIELDS',severity='P0',
          source_evidence=r['evidence'],root_cause=r['root_cause'],repair_action='Correct close; recompute transparent cap/turnover identities; quarantine unverifiable valuation fields.',
          repair_output='data/standardized/market/v4/stock_daily_basic_observations',verification_method='Independent unadjusted quote plus full daily/basic price join recheck',verification_result='Close repaired; price join violations zero',
          remaining_blocker='Valuation denominators for '+','.join(r['blocked_fields'])+' unavailable in independent historical source.',status='PARTIALLY_REPAIRED')
    factor=read(AUDIT/'issue_closure/factor_repairs.json')
    add(issue_id='FACTOR_MIXED_VINTAGES',domain='M',dataset_id='stock_adjustment',affected_period='2014..2026',issue_type='VERSION_DISCONTINUITY',severity='P0',source_evidence='audit/final_data_foundation/issue_closure/factor_repairs.json',
      root_cause='Nonconstant historical rescaling between provider batches produces artificial non-event return jumps.',repair_action='Replace 76 entire code histories with coherent retained provider snapshots.',repair_output='data/standardized/market/v4/stock_adjustment_observations',
      verification_method='Full 11981370 quote-factor rows and corporate-action diagnostics',verification_result=factor['status'],remaining_blocker='Provider factors still have rounding and remaining corporate-action qualifications.',status='PARTIALLY_REPAIRED')
    add(issue_id='FACTOR_000545_20150326',domain='M',dataset_id='stock_adjustment',instrument_id='000545.SZ',affected_period='2015-03-26..2026-09-22',issue_type='OMITTED_CAPITALISATION',severity='P0',source_evidence='audit/final_data_foundation/issue_closure/official_factor_repair.json',
      root_cause='Provider factor omits official 10-for-3 capitalisation.',repair_action='Apply evidenced 1.3 scale to later factors, preserve all originals.',repair_output='data/standardized/market/v4/stock_adjustment_observations',verification_method='Primary announcement and independent Tencent hfq return, followed by population recheck',verification_result='PASS',remaining_blocker='none for this event',status='CLOSED_INDEPENDENTLY_VERIFIED')
    adj=pd.read_parquet(AUDIT/'source_reconciliation/factor_adjudications.parquet')
    for r in adj[adj.classification.isin(['UNRESOLVED_FACTOR_OR_REFERENCE_BASIS','OPEN_SHARE_REFORM_FACTOR_BASIS'])].itertuples(index=False):
        add(issue_id='FACTOR_'+r.ts_code+'_'+r.trade_date,domain='M',dataset_id='stock_adjustment',instrument_id=r.ts_code,affected_period=r.trade_date,issue_type=r.classification,severity='P0',
          source_evidence='audit/final_data_foundation/source_reconciliation/factor_adjudications.parquet; data/raw/public_sources/v4/factor_action_announcements.json; data/raw/public_sources/v4/factor_000011_announcements.json',
          root_cause='Factor/reference discrepancy exceeds observed quantization allowance; corporate-action implementation basis unresolved.',repair_action='Re-observed provider history and examined independent prices and available original action notices; preserved conflicting evidence.',
          repair_output='audit/final_data_foundation/source_reconciliation/factor_adjudications.parquet',verification_method='Independent prices, issuer terms and factor ratio against reference return',verification_result='OPEN',remaining_blocker='Certified factor methodology/action entitlement reconciliation needed; no speculative rescaling.',status='OPEN')
    for r in read(AUDIT/'issue_closure/index_adjudication_summary.json')['unresolved_material_prices']:
        add(issue_id='INDEX_PRICE_'+r['ts_code']+'_'+r['trade_date'],domain='M',dataset_id='index_daily',instrument_id=r['ts_code'],affected_period=r['trade_date'],issue_type='CROSS_SOURCE_PRICE_CONFLICT',severity='P0',
          source_evidence='audit/final_data_foundation/source_reconciliation/csi1000_third_source.json',root_cause='TuShare and Tencent differ beyond display precision; third-source request did not resolve these dates.',
          repair_action='Queried Sohu and Eastmoney additional paths; retained primary and all conflicting values.',repair_output='audit/final_data_foundation/source_reconciliation/index_quote_adjudication.parquet',verification_method='OHLC arithmetic and independent-provider reconciliation',
          verification_result='OPEN',remaining_blocker='CSI/exchange authenticated historical OHLC for two dates needed.',status='OPEN')
    for code in INDEX_CODES:
        add(issue_id='EXACT_CONSTITUENTS_'+code,domain='M',dataset_id='index_constituents_history',instrument_id=code,affected_period='2014-01-01..2026-09-22',issue_type='EFFECTIVE_MEMBERSHIP_ARCHIVE_INCOMPLETE',severity='P1',
          source_evidence='data/raw/public_sources/v4/cni_source_downloads.json; audit/final_data_foundation/issue_closure/cni_reconstruction.json',root_cause='Monthly weight snapshots do not establish every effective adjustment; complete original event catalogue unavailable.',
          repair_action='Recovered and replayed 38 official 399001 adjustment events into 39 500-member books; kept all index weight snapshots without backfilling.',repair_output='data/standardized/market/v4/index_constituents_history.parquet',
          verification_method='Primary PDF/XLS extraction, signature/effective-date review, event replay and closing independent catalogue comparison',verification_result='PARTIAL' if code=='399001.SZ' else 'OPEN',
          remaining_blocker='Complete licensed/official effective constituent and daily weight history; no permission to buy data or contact third parties has been assumed.',status='PARTIALLY_REPAIRED' if code=='399001.SZ' else 'OPEN')
    add(issue_id='BASIC_SHARE_CAP_BASIS',domain='M',dataset_id='stock_daily_basic',affected_period='2014..2026, predominantly 2026',issue_type='SHARE_PRECISION_AND_DENOMINATOR',severity='P1',source_evidence='audit/final_data_foundation/source_reconciliation/basic_arithmetic',
      root_cause='Provider cap/share identities disagree; most 2026 differences fit coarser share precision, while material cases may differ in share class/float denominator.',repair_action='Population arithmetic checks, independent fresh API rereads for material examples, explicit field qualification.',repair_output='audit/final_data_foundation/market_coverage/basic_arithmetic_summary.parquet',
      verification_method='Price times shares and daily-volume turnover identities',verification_result='OPEN_FIELD_QUALIFICATIONS',remaining_blocker='Authoritative historical share-class/free-float denominator and provider precision specification required.',status='OPEN')
    add(issue_id='HISTORICAL_UNIVERSE_CATALOGUE',domain='M',dataset_id='stock_master_history',affected_period='2014..2026',issue_type='INDEPENDENT_MASTER_CERTIFICATION',severity='P0',source_evidence='data/raw/public_sources/v4/code_change_evidence.json',
      root_cause='Provider universe includes delisted securities but has not been reconciled to a complete independent exchange historical listing and identity catalogue.',repair_action='Retained 333 delisted securities and verified four code transitions; removed duplicate backfilled aliases from observations.',repair_output='data/standardized/market/v4/stock_master_history.parquet',
      verification_method='Complete observed-code joins and validity bounds; source-certified code mappings',verification_result='Observed codes reconciled; universe exhaustiveness not proven',remaining_blocker='Complete independent exchange historical securities/identity catalogue, including other legal restructurings.',status='PARTIALLY_REPAIRED')
    field_quality=pd.read_parquet(AUDIT/'market_coverage/field_quality_summary.parquet')
    structural=field_quality[field_quality.quality_status.eq('STRUCTURAL_SUSPENSION_NO_TRADE')]
    if len(structural):
        add(issue_id='NONTRADING_BASIC_PRICE_FIELDS',domain='M',dataset_id='stock_daily_basic',affected_period='2020-09-18',issue_type='NONTRADING_SOURCE_ROWS',severity='P1',
          source_evidence='data/standardized/market/v4/market_data_quality.parquet; audit/final_data_foundation/market_coverage/basic_without_quote.parquet',
          root_cause='Eleven provider basic snapshots exist on a day with explicitly recorded/verified suspension and no trade; classifying their close/turnover as missing traded values was incorrect.',
          repair_action='Keep source rows and nulls; classify only close/turnover fields as structural non-trading absence, with suspension-state evidence.',repair_output='data/standardized/market/v4/market_data_quality.parquet',
          verification_method='Full basic-to-quote reverse join and explicit suspended-state join',verification_result=str(int(structural.observations.sum()))+' structural field absences verified',
          remaining_blocker='No blocker for these price/turnover fields; valuation/share availability assessed separately.',status='CLOSED_SOURCE_VERIFIED')
    for r in field_quality[field_quality.quality_status.eq('BLOCKED_MISSING_REQUIRED_FIELD')].itertuples(index=False):
        add(issue_id='MISSING_FIELD_'+r.dataset_id+'_'+r.field,domain='M',dataset_id=r.dataset_id,affected_period='2014..2026; exact dates in market_data_quality',issue_type='MISSING_REQUIRED_FIELD',severity='P1',
          source_evidence='data/standardized/market/v4/market_data_quality.parquet',root_cause='Required provider value absent or quarantined; a null alone does not establish structural nonexistence.',
          repair_action='Audited entire population and retained field/date exception IDs; independently fixed seven wrong-close records and quarantined unverifiable denominators.',repair_output='data/standardized/market/v4/market_data_quality.parquet',
          verification_method='Full field-null scan after repairs',verification_result=str(r.observations)+' missing '+r.field+' values',remaining_blocker='Independent historical field/denominator source or verified structural reason required.',status='OPEN')
    for r in pd.read_parquet(AUDIT/'market_coverage/secondary_stock_source_summary.parquet').itertuples(index=False):
        if r.status in ['BOUNDS_AGREE_NOT_FULL_RULE_CERTIFICATION','SOURCE_PRESENT_CLASSIFICATION_NOT_INDEPENDENTLY_VERIFIED','VERIFIED_SPECIAL_RULE_NOT_ORDINARY_LIMIT']:continue
        add(issue_id='SECONDARY_'+r.dataset_id+'_'+str(r.year)+'_'+r.status,domain='M',dataset_id=r.dataset_id,affected_period=str(r.year),issue_type=r.status,severity='P1' if r.dataset_id=='stock_limits' else 'P2',
          source_evidence='audit/final_data_foundation/missing_records/'+r.dataset_id+'/'+str(r.year)+'.parquet',root_cause='Source coverage/value or price bound requires historically valid eligibility/rule/event evidence.',
          repair_action='Reconciled historical aliases and joined every actual traded security/date, retaining exact unmatched/contradictory rows.',repair_output='audit/final_data_foundation/market_coverage/secondary_stock_source_summary.parquet',
          verification_method='Full population left join and limit-bound comparison',verification_result=str(r.observations)+' affected observations',remaining_blocker='Official historical exchange rules/events or missing provider source records; no blanket IPO or ST exemption.',status='OPEN')
    for key,dataset,artifact,reason,action in [
      ('SPECIAL_PRICE_LIMITS','stock_limits','limit_rule_repairs.json','Provider ordinary 10% limits were incorrectly used on evidenced IPO/relisting/reform dates; one no-limit source row was absent.','Retained 48 IPO primary documents and issuer event notices; normalized 70 special-rule dates with original limits preserved and no synthetic numeric bounds.'),
      ('MONEYFLOW_GAP_SUPPLEMENT','stock_moneyflow','moneyflow_supplement.json','2014 source history had not been imported; subsequent observed-day gaps were present in the provider archive.','Paginated 2014 history and retried every later affected security range; admitted only previously absent security/date records, preserving capture times.')]:
        evidence=read(AUDIT/'issue_closure'/artifact)
        add(issue_id=key,domain='M',dataset_id=dataset,affected_period='2014..2026',issue_type='SOURCE_SEMANTICS_OR_COLLECTION_GAP',severity='P1' if dataset=='stock_limits' else 'P2',
          source_evidence='audit/final_data_foundation/issue_closure/'+artifact,root_cause=reason,repair_action=action,repair_output='data/standardized/market/v4/'+('stock_limits_observations' if dataset=='stock_limits' else dataset),
          verification_method='Primary source/literal review and exhaustive observed-security/date rejoin',verification_result=json.dumps(evidence,ensure_ascii=False),
          remaining_blocker=evidence.get('remaining',str(evidence.get('unfilled_observed_dates',0))+' source-classified flow dates remain absent'),status='CLOSED_SOURCE_VERIFIED' if dataset=='stock_limits' else 'PARTIALLY_REPAIRED')
    annual=read(AUDIT/'macro_coverage/annual_review_literal_verification.json')
    for r in annual:
        if 'period' not in r:continue
        scope='tsf_ytd_flow__scope_pre_201807' if r['period']<'2018-07-01' else 'tsf_ytd_flow'
        actual=matrix[matrix.series_id.eq(scope)&matrix.period_end.eq(pd.Timestamp(r['period']))]
        assert len(actual)==1 and actual.status.eq('ACCEPTED').all()
        add(issue_id='ANNUAL_TSF_'+r['period'],domain='Z',dataset_id='macro_facts',series_id=scope,affected_period=r['period'],issue_type='MISSING_CONTEMPORANEOUS_CUMULATIVE_VERSION',severity='P1',
          source_evidence=r['url']+'; audit/final_data_foundation/macro_coverage/annual_review_literal_verification.json',root_cause='No dated annual cumulative record admitted; later undated provider values did not certify the original reporting scope or vintage.',
          repair_action='Retain the dated government/press report, literal amount, reporting precision and its own publication date; never add differently revised monthly values.',repair_output='data/standardized/macro/v4/macro_facts.parquet',
          verification_method='Downloaded-byte hash, literal publication/value assertions and full expected-period grid',verification_result='ACCEPTED under conservative publication policy',remaining_blocker='No blocker for this conservative annual record; complete first-release/revision archive is not claimed.',status='CLOSED_SOURCE_VERIFIED')
    add(issue_id='TSF_2015_ENTRUSTED_LOAN_SCOPE',domain='Z',dataset_id='macro_facts',affected_period='2014..2018-06; 2015-01 boundary',issue_type='UNDERSPECIFIED_STATISTICAL_SCOPE',severity='P1',
      source_evidence='audit/final_data_foundation/macro_coverage/tsf_2015_scope_amendment.json',root_cause='The broad pre-2018 scope did not distinguish the documented 2015-01 entrusted-loan definition change.',
      repair_action='Refine record scopes and block previous/change across scope boundaries; preserve uncertain restated records in quarantine.',repair_output='data/standardized/macro/v4/macro_facts.parquet',
      verification_method='Primary PDF page 11 literal and real 2015 weekly boundary regression',verification_result='See audit/final_data_foundation/temporal_validation/tsf_2015_scope_boundary.json',remaining_blocker='No comparable historical restatement is inferred; broader archive limitations remain.',status='CLOSED_SOURCE_VERIFIED')
    add(issue_id='FACTOR_REFRESH_BACKUP_LINEAGE',domain='M',dataset_id='stock_adjustment',instrument_id='000011.SZ',affected_period='2020..2023',issue_type='STALE_AUDIT_PARENT_VALUES',severity='P1',
      source_evidence='audit/final_data_foundation/reproducibility/final/difference_adjudication.json',root_cause='Partial provider refresh changed the active factor but left 379 pre-action backup values stale.',
      repair_action='Synchronize the retained pre-action backup when an existing factor table is refreshed; full rebuild establishes a consistent baseline.',repair_output='data/standardized/market/v4/stock_adjustment_observations',
      verification_method='Regression using exact failed before-images and retained provider response, preserving active factor values',verification_result='379 mismatches before; zero after; audit/final_data_foundation/reproducibility/factor_parent_regression.json',remaining_blocker='Unresolved economic factor/action bases are tracked separately.',status='CLOSED_INDEPENDENTLY_VERIFIED')
    units=pd.read_parquet(ROOT/'data/metadata/field_dictionary.parquet')
    for r in units[units.quality_status.eq('UNVERIFIED_FIELD_DEFINITION')&(units.required|((units.dataset_id=='exchange_activity_sz')&units.field.isin(['total_share','float_share'])))].itertuples(index=False):
        add(issue_id='SOURCE_UNIT_'+r.dataset_id+'_'+r.field,domain='M',dataset_id=r.dataset_id,affected_period='full retained history',issue_type='UNVERIFIED_SOURCE_UNIT',severity='P1' if r.required else 'P2',
          source_evidence=str(r.definition_evidence_path),root_cause='Retained source definition names the quantity but does not explicitly certify its unit/scale for this dataset.',
          repair_action='Inspected provider field definitions; removed unsupported inheritance of individual-stock share units from Shenzhen aggregate fields.',repair_output='data/metadata/field_dictionary.parquet',
          verification_method='Dataset-specific definition and unit review',verification_result='Explicit UNVERIFIED_FIELD_DEFINITION; no automatic admission or conversion',remaining_blocker='Provider unit metadata or an independently matched exchange historical raw table is required.',status='OPEN')
    flow_extra=read(AUDIT/'issue_closure/moneyflow_nontrading_quarantine.json')
    add(issue_id='MONEYFLOW_WITHOUT_OBSERVED_TRADE',domain='M',dataset_id='stock_moneyflow',affected_period='2015..2022; exact 82 dates/identities in evidence',issue_type='FLOW_QUOTE_SUSPENSION_SOURCE_CONFLICT',severity='P1',
      source_evidence='audit/final_data_foundation/source_reconciliation/moneyflow_nontrading_comparison.parquet; audit/final_data_foundation/source_reconciliation/moneyflow_nontrading_rerequests.json',
      root_cause='82 provider flow records have no same-security/date canonical quote and conflict with source/official suspension status; all 82 remain present on fresh provider reread.',
      repair_action='Preserve original rows and six fresh date snapshots; quarantine net amount/volume fields instead of inventing prices, trades or zero flows.',repair_output='data/standardized/market/v4/market_data_quality.parquet',
      verification_method='Full reverse quote join, suspension-state join and independent re-observation of all six dates',verification_result=json.dumps(flow_extra),remaining_blocker='Provider historical flow-date methodology or independent transaction evidence must resolve the disagreement.',status='OPEN')
    frame(AUDIT/'issue_closure/issues.parquet',pd.DataFrame(rows));write(AUDIT/'issue_closure/issues.json',rows)
    old=read(ROOT/'audit/data_foundation_v3/unresolved_issues.json');comparison=[]
    for r in old:
        # The latest TSF scopes were split, not dropped; compare concept families.
        concept=r['series_id'].split('__scope_')[0];now=matrix[matrix.series_id.str.split('__scope_').str[0].eq(concept)]
        comparison.append({**r,'current_concept':concept,'current_unaccepted_periods':int((~now.status.isin(['ACCEPTED','STRUCTURAL_NA'])).sum()),'current_status_counts':now.status.value_counts().to_dict(),
          'status':'CLOSED_AT_CONSERVATIVE_PERIOD_COVERAGE' if now.status.isin(['ACCEPTED','STRUCTURAL_NA']).all() else 'PARTIALLY_REPAIRED_OR_OPEN'})
    write(AUDIT/'issue_closure/v3_issue_followthrough.json',comparison)
    print('Issues',len(rows),pd.DataFrame(rows).status.value_counts().to_dict(),flush=True)


if __name__=='__main__':build()
