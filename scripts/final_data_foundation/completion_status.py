"""Current residuals, closed gaps and concrete unsuccessful source checks."""
from .common import *


def build():
    path=ROOT/'data/metadata/remaining_gaps.json';old=read(path)
    q=pd.read_parquet(MARKET/'market_data_quality.parquet')
    missing=q[q.quality_status.eq('BLOCKED_MISSING_REQUIRED_FIELD')].groupby('field').size().to_dict()
    structural=int((q.field.eq('pb')&q.quality_status.eq('STRUCTURAL_NONPOSITIVE_BOOK_EQUITY')).sum())
    blocked=q[q.quality_status.eq('BLOCKED_UNRESOLVED_SHARE_DENOMINATOR')]
    pb_numeric=int((q.field.eq('pb')&q.quality_status.isin(['ALTERNATIVE_PB_MRQ_RECONSTRUCTED','QUALIFIED_ISSUER_PB_RECONSTRUCTION','QUALIFIED_RESTATED_PB_RECONSTRUCTION'])).sum())
    matrix=pd.read_parquet(META/'data_requirements_matrix.parquet')
    residual=matrix[~matrix.status.isin(['ACCEPTED','STRUCTURAL_NA'])]
    trade=residual[residual.series_id.str.contains('_cny_')]
    required=[r for r in old['required'] if r['dataset'] not in ['index_daily','exchange_activity_sz']]
    for r in required:
        if r['dataset']=='stock_daily_basic' and r['gap_type']=='MISSING_REQUIRED_FIELD':
            r.update(fields={k:int(missing.get(k,0)) for k in ['pb','turnover_rate_f']},
                sources_checked=['E:/QuantData daily_basic and financial indicators (read only)','targeted primary daily_basic refresh, including free_share parents','BaoStock unadjusted daily PB MRQ for 221 securities; same-day prices/volume and positive overlap checks','Issuer IPO notices for five companies; first/second day public float reconstruction','Actual volume / evidenced same-day free shares','26 issuer financial reports: latest common equity, ordinary-versus-other equity instruments, exact capitalization identities and explicit correction publication clocks'],
                conclusion=f'{structural} PB blanks are separately supported nonpositive-equity semantics. PB numeric gaps now closed; four300312 observations use the2020-05-11 corrected filing and remain historical-restated only, unavailable for pre-publication predictors. All other numeric admissions have explicit source agreement or issuer denominator formulas. Two601200 free-share parents reconstructed from the original demerger public/strategic locked-share table, supported by unchanged registered quantities and surrounding source observations.',
                details=['data/metadata/pb_alternative_basis.parquet','data/metadata/pb_alternative_crosscheck.json','data/metadata/pb_issuer_financial_parents.parquet','data/metadata/pb_issuer_field_repairs.parquet','data/metadata/free_share_refreshes.parquet','data/metadata/ipo_free_share_basis.parquet','data/metadata/demerger_free_share_basis.parquet'])
        elif r['dataset']=='stock_daily_basic' and r['gap_type']=='INCONSISTENT_SOURCE':
            r.update(field_exceptions=len(blocked),fields={k:int(v) for k,v in blocked.groupby('field').size().items()},
                sources_checked=['Historical quotes and primary daily_basic quantities','Fresh primary API rereads','BaoStock turnover comparison (shared convention does not independently adjudicate denominator)','Issuer 689009 CDR listing prospectus pages 21/38; 1 underlying share = 10 CDRs','002563 registered re-lock announcement and2015 half-year opening share table:70m unrestricted,600m restricted;219 denominator exceptions adjudicated','001331 annual2025 andQ12026 filings: retrospective share count found but intervening director-lock/event effective dates not fully resolved'],
                conclusion='393 exceptions closed after documented CDR-unit normalization and14 after independently verified quote/volume correction;219 more after issuer-registered re-locking fixed float shares and circulating cap. Residual disagreements remain beyond tight precision; no arbitrary equation-forced replacement. 460960 other field exceptions fit coarser share display precision only, not independent certification.',
                concrete_example='001331.SZ20260106-20260428: float shares19712.7 versus circulating capitalization/turnover implied16787.17; issuer2025 annual report supports19712.7 but exact intervening lock-release clock remains unconfirmed. Other residuals include foreign-share scope, free-share changes and nontrivial provider precision.')
        elif r['dataset']=='macro_facts' and r['gap_type']=='BROKEN_PERIOD':
            r['sources_checked'] += ['2026-11-15 official SddsIntrRateGovYldHis recheck: 2014 total=0; control January2015 total=21; HTTP200 for both','CFETS real-time and closing curve definitions reviewed; closing or ChinaBond curve is not the registered 11:30 mean']
            r['sources_checked']=list(dict.fromkeys(r['sources_checked']))
            r['official_endpoint']='https://www.chinamoney.org.cn/ags/ms/cm-u-bk-currency/SddsIntrRateGovYldHis'
        elif r['dataset']=='macro_facts' and r['gap_type']=='MISSING_VALUE':
            r.update(fields={k:int(v) for k,v in trade.groupby('series_id').size().items()},
                missing_periods={sid:[str(x.date()) for x in g.period_end] for sid,g in trade.groupby('series_id')},
                sources_checked=['Existing facts, peer collectors and E:/QuantData','GAC English preliminary yearly archives 2020/2022/2025 and formal monthly directories: Jan/Feb combined or USD only','GAC Chinese historical tables: HTTP412 challenge or HTTPS timeout','MOFCOM FDI official API: 28 narrowed catalogue searches, 59 RMB tables reviewed; national monthly/YTD distinctions verified','MOFCOM trade data centre: monthly table USD, unsuitable for RMB replacement','NBS national data tree: HTTP403 UrlACL','hgsj attributed XLS: HTTPS refused, HTTP placeholder rather than workbook','cndatatrading mobile/desktop and HTTP/HTTPS: HTTP502','Dated Chyxx national CNY reports: January2025 and2026 admitted; remaining target search did not yield verified monthly rates','UEQ February2025 report rejected: monthly amount falls versus prior year while rate copies +3.4% cumulative'],
                conclusion='26 of40 missing periods supplied:18 official reproductions and8 dated attributed national CNY observations. Remaining14 require verified same-vintage monthly amounts/rates. No USD conversion, chart estimation, search-snippet admission or mixing cumulative growth with monthly growth.',
                details=['data/metadata/unresolved_macro_periods.parquet','data/metadata/mofcom_trade_catalogue.json','data/metadata/mofcom_trade_repairs.parquet','data/metadata/attributed_trade_repairs.parquet'])
    closed=[
        dict(dataset='index_daily',issue='CSI1000 two dates / three flagged price fields',status='CLOSED',basis='Official CSI index-perf OHLC agrees with retained primary within 0.00501 index points; Tencent conflicts rejected; dependent extension windows restored',evidence='data/metadata/index_price_conflicts.parquet'),
        dict(dataset='exchange_activity_sz',issue='2014 missing daily quantities',status='CLOSED',basis='Direct sz_daily_info 5 stock categories x245dates x3quantities=3675 source fields; count exact and all3monetary totals match official display precision',evidence='data/metadata/szse_2014_quantity_repairs.parquet'),
        dict(dataset='stock_daily_basic',issue='PB',status='CLOSED_WITH_HISTORICAL_QUALIFICATIONS',baseline_missing=13936,remaining_missing=int(missing.get('pb',0)),numeric_values_added=pb_numeric,newly_quarantined_conflicts=1,additional_structural_nonpositive=structural-61368,structural_total=structural),
        dict(dataset='stock_daily_basic',issue='free turnover',status='CLOSED_NUMERIC_GAPS_WITH_SEPARATE_DENOMINATOR_MASK',baseline_missing=16,remaining_missing=int(missing.get('turnover_rate_f',0)),values_added=16,refreshed_share_parents=6,ipo_notice_share_parents=8,demerger_notice_share_parents=2),
        dict(dataset='stock_daily_basic',issue='CDR denominators',status='PARTIALLY_CLOSED',corrected_share_quantity_fields=117,corrected_turnover_fields=242,resolved_quality_exceptions=393,remaining_all_security_exceptions=len(blocked),evidence='data/metadata/cdr_unit_repairs.parquet'),
        dict(dataset='macro_facts',issue='CNY trade',status='PARTIALLY_CLOSED',baseline_missing=40,periods_added=26,remaining_missing=len(trade)),
        dict(dataset='stock_daily_basic',issue='Seven old quote corrections absent from the authority',status='CLOSED_QUOTE_AND_ISSUER_PB',rows=7,turnover_exceptions_resolved=14,evidence='data/metadata/basic_close_field_repairs.parquet',cause='Old repair wrote superseded stock_daily_basic intermediate; current stock_daily_basic_observations still contained wrong source closes. Corrected authority and added full-population close equality and arithmetic residual checks.')]
    closed.append(dict(dataset='stock_daily_basic',issue='002563 registered re-lock',status='CLOSED',field_repairs=438,quality_exceptions_resolved=219,evidence='data/metadata/restricted_share_repairs.parquet'))
    next(r for r in closed if r['issue']=='PB').update(
        evidence=['data/metadata/pb_denominator_basis.parquet','data/metadata/pb_alternative_basis.parquet','data/metadata/pb_issuer_financial_parents.parquet','data/metadata/pb_issuer_field_repairs.parquet'],
        qualification='Four300312 PB values use the2020-05-11 corrected filing and are historical-restated only; never predictors before that publication. Other repairs retain source/issuer and same-day publication qualifications.')
    next(r for r in closed if r['issue']=='free turnover').update(
        evidence=['data/metadata/free_share_refreshes.parquet','data/metadata/ipo_free_share_basis.parquet','data/metadata/demerger_free_share_basis.parquet','data/metadata/free_turnover_derivations.parquet'],
        qualification='Numeric gaps closed using observed volume and evidenced free-share parents. Independent non-null denominator exceptions remain separately masked.')
    required=[r for r in required if not (r['gap_type']=='MISSING_REQUIRED_FIELD' and not any(r['fields'].values()))]
    old.update(status='UNRESOLVED_REQUIRED_DATA',version='practical-research-data-v5',required=required,closed_or_reduced=closed)
    write(path,old);print('CURRENT_RESIDUALS',missing,'denominator',len(blocked),'trade',len(trade),flush=True)


if __name__=='__main__':build()
