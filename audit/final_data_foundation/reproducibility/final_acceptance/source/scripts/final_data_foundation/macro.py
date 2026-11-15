"""Version-preserving macro normalization from original publisher tables."""
import re
import numpy as np
from lxml import html
from urllib.parse import urlparse
from .common import *
from .collect import PUBLIC
from scripts.data_foundation_v3.standardize import dated_fact
from .macro_contract import specifications,apply_scopes,configure_quality
from scripts.experiment_framework.common import identity

def gac_facts():
    facts=[];checks=[]
    for rec in read(PUBLIC/'gac_monthly_sources.json')['tables']:
        if rec['status']!='ok':continue
        if sha(ROOT/rec['path'])!=rec['sha256']:raise ValueError('Changed GAC evidence')
        tree=html.fromstring((ROOT/rec['path']).read_bytes().decode(rec['encoding'],errors='replace'))
        dates=[s.strip() for s in tree.xpath('//*[contains(@class,"date")]/text()') if s.strip()]
        if len(dates)!=1:raise ValueError('Ambiguous GAC publication date')
        date=pd.to_datetime(dates[0],format='%Y/%m/%d' if dates[0][:4].isdigit() else '%m/%d/%Y')
        rows=[[re.sub(r'\s+',' ',c.text_content()).strip() for c in tr.xpath('./td|./th')] for tr in tree.xpath('//tr')]
        header=' '.join(' '.join(r) for r in rows[:4])
        if not ('Monthly' in header and 'USD' in header and 'Export' in header and 'Import' in header):raise ValueError('Unrecognized GAC monthly schema')
        prior={r[0]:r for r in rows if len(r)==9 and re.fullmatch(r'20\d\d\.\d{1,2}',r[0])}
        for i,row in enumerate(rows[:-2]):
            if len(row)!=9 or not re.fullmatch(str(rec['year'])+r'\.\d{1,2}',row[0]):continue
            year,month=map(int,row[0].split('.'));end=pd.Timestamp(year,month,1)+pd.offsets.MonthEnd(0)
            if end>date:raise ValueError('GAC observation after printed publication date')
            yoy=rows[i+1];mom=rows[i+2]
            if len(yoy)!=9 or len(mom)!=9 or yoy[0] or mom[0]:raise ValueError('Unrecognized GAC percentage row layout')
            previous=prior.get(f'{year-1}.{month:02d}') or prior.get(f'{year-1}.{month}')
            for sid,col in [('exports_yoy',2),('imports_yoy',3)]:
                if not re.fullmatch(r'-?\d+(?:\.\d+)?',yoy[col]):continue
                value=float(yoy[col]);calc=(float(row[col].replace(',',''))/float(previous[col].replace(',',''))-1)*100 if previous else None
                agrees=calc is not None and abs(value-calc)<=.052
                check={'series_id':sid,'period_end':end,'source_url':rec['url'],'printed_yoy':value,'independent_same_table_yoy':calc,
                       'release_date':date,'status':'ARITHMETIC_CONFIRMED' if agrees else 'REQUIRES_REVIEW','evidence_path':rec['path']}
                checks.append(check)
                r=dated_fact(sid,value,end,date,rec,rec['url'],quality='conservative_release_reconstructed',
                    note='GAC dated USD monthly bulletin. Exact printed monthly percentage, independently checked against current/prior-year monthly amounts in this SAME table. Each page is a separate publication vintage; all rows become available only on that page date, never their observation month or an assumed first release. Different monthly editions are preserved; no claim of first-release archive or documented revision cause.')
                r.update(source_name='GACC English monthly bulletin',source_class='official_dated_statistical_table',
                    extracted_text=json.dumps({'month':row[0],'monthly_amount_row':row,'yoy_row':yoy,'previous_year_amount_row':previous},ensure_ascii=False),
                    reported_quantum=.1,extraction_method='literal_html_cells_plus_independent_ratio',
                    value_quality='published_percentage_independently_checked' if agrees else 'arithmetic_conflict',
                    revision_status='dated_monthly_table_version_not_first_release',vintage_id='gac-'+rec['sha256'][:20],
                    publication_date_evidence=rec['path']+'#'+dates[0])
                if not agrees:r.update(quality_status='blocked',adjustment_note=r['adjustment_note']+' Arithmetic discrepancy requires manual review; do not use.')
                facts.append(r)
    frame(AUDIT/'source_reconciliation/gac_independent_arithmetic.parquet',pd.DataFrame(checks))
    return facts

def reviewed_mofcom():
    # Literal national totals from the reviewed opening paragraphs, excluding
    # later commodity/regional details and forecasts in these long articles.
    selected=[{'url':'https://data.mofcom.gov.cn/article/zxtj/202208/58450.html','date':'2022-08-11','period':'2022-06-30',
       'values':{'exports_cny_yoy':(22.,'出口2.21万亿元，同比增长22.0%'),
                 'imports_cny_yoy':(4.8,'进口1.56万亿元，同比增长4.8%'),
                 'exports_cny_ytd_yoy':(13.2,'出口111416.7亿元，同比增长13.2%'),
                 'imports_cny_ytd_yoy':(4.8,'进口86605.1亿元，同比增长4.8%')}}]
    requests={r['url']:r for p in (PUBLIC/'requests').glob('*.json') if (r:=read(p))['status']=='ok'}
    out=[]
    for entry in selected:
        rec=requests[entry['url']];raw=(ROOT/rec['path']).read_bytes().decode(rec['encoding'],errors='replace')
        text=re.sub(r'\s+','',html.fromstring(raw).text_content())
        if entry['date'] not in raw:raise ValueError('Missing MOFCOM date')
        for sid,(value,quote) in entry['values'].items():
            if quote not in text:raise ValueError('Reviewed literal changed')
            row=dated_fact(sid,value,entry['period'],entry['date'],rec,entry['url'],'ytd_yoy' if '_ytd_' in sid else 'yoy',quality='conservative_release_reconstructed',
                 note='MOFCOM dated analytical reproduction; reviewed national CNY total and monthly/YTD paragraph. Availability is August 11, not inferred July first release.')
            row.update(source_name='MOFCOM data centre',source_class='dated_official_republication',extracted_text=quote,reported_quantum=.1,
                       extraction_method='reviewed_literal_with_currency_and_period_context')
            out.append(row)
    return out

def gac_preliminary_facts():
    ledger=PUBLIC/'gac_preliminary_sources.json'
    if not ledger.exists():return []
    out=[];checks=[]
    months=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    for rec in read(ledger)['tables']:
        if rec['status']!='ok':continue
        if sha(ROOT/rec['path'])!=rec['sha256']:raise ValueError('Changed GAC preliminary evidence')
        tree=html.fromstring((ROOT/rec['path']).read_bytes().decode(rec['encoding'],errors='replace'))
        dates=[s.strip() for s in tree.xpath('//*[contains(@class,"date")]/text()') if s.strip()]
        if len(dates)!=1:raise ValueError('Ambiguous GAC date')
        date=pd.to_datetime(dates[0],format='%Y/%m/%d' if dates[0][:4].isdigit() else '%m/%d/%Y')
        month=months.index(rec['month_label'][:3])+1;end=pd.Timestamp(rec['year'],month,1)+pd.offsets.MonthEnd(0)
        if end>pd.Timestamp('2026-09-30'):continue
        if end>date:raise ValueError('GAC preliminary observation after publication')
        rows=[[re.sub(r'\s+',' ',c.text_content()).strip() for c in tr.xpath('./td|./th')] for tr in tree.xpath('//tr')]
        header=' '.join(' '.join(r) for r in rows[:4]);count=0
        for side,english in [('Total Export','exports'),('Total Import','imports')]:
            matching=[r for r in rows if r and r[0]==side]
            if len(matching)!=1:continue
            row=matching[0]
            if rec['currency'] not in header or str(rec['year']) not in header:raise ValueError('Preliminary currency/year mismatch')
            if len(row)==6 and 'Month-on-Month' in header and header.count('Year-on-Year')==2:
                values=[('monthly',row[4]),('ytd',row[5])]
            elif len(row)==3 and month==2 and 'January-February' in header and 'Year-on-Year' in header:
                values=[('ytd',row[2])]
            else:
                checks.append({'url':rec['url'],'status':'UNRECOGNIZED_TABLE_LAYOUT','row':row});continue
            for scope,value in values:
                if rec['currency']=='USD' and scope=='ytd':continue
                if not re.fullmatch(r'-?\d+(?:\.\d+)?',value):continue
                sid=english+('_yoy' if rec['currency']=='USD' else '_cny_yoy' if scope=='monthly' else '_cny_ytd_yoy')
                r=dated_fact(sid,float(value),end,date,rec,rec['url'],'ytd_yoy' if scope=='ytd' else 'yoy',quality='conservative_release_reconstructed',
                    note='GAC dated preliminary national-total table. Column headers distinguish monthly MoM, monthly YoY, and YTD YoY. January-February combined totals are only YTD; no invented separate months. Observed publication version retained, not silently substituted by a later monthly bulletin.')
                r.update(source_name='GACC preliminary trade table',source_class='official_dated_statistical_table',extracted_text=json.dumps({'header':rows[:4],'row':row,'scope':scope},ensure_ascii=False),
                    extraction_method='literal_named_row_and_header_columns',reported_quantum=.1,publication_date_evidence=rec['path']+'#'+dates[0],
                    revision_status='dated_preliminary_table_version',vintage_id='gac-'+rec['sha256'][:20])
                out.append(r);count+=1
        checks.append({'url':rec['url'],'status':'EXTRACTED' if count else 'IMAGE_OR_UNRECOGNIZED_LAYOUT','facts':count,'evidence_path':rec['path']})
    write(AUDIT/'macro_coverage/gac_preliminary_extractions.json',checks)
    return out

def reviewed_trade_reports():
    """Qualified contemporary press records, never official first vintages."""
    entries=[
      ('https://www.jjckb.cn/2015-02/16/content_538643.htm','2015-02-16','2015-01-31','2015-02-16',{
        'exports_yoy':(-3.3,'出口2002.6亿美元，下降3.3%'),
        'imports_yoy':(-19.9,'进口1402.3亿美元，下降19.9%'),
        'exports_cny_yoy':(-3.2,'出口1.23万亿元，进口0.86万亿元，分别下降3.2%和19.7%'),
        'imports_cny_yoy':(-19.7,'出口1.23万亿元，进口0.86万亿元，分别下降3.2%和19.7%'),
        'exports_cny_ytd_yoy':(-3.2,'2015年1月，全国进出口2.09万亿元'),
        'imports_cny_ytd_yoy':(-19.7,'2015年1月，全国进出口2.09万亿元')}),
      ('http://caifang.china.com.cn/2015-05/18/content_7914120.htm','2015-05-18','2015-04-30','2015-05-18',{
        'exports_yoy':(-6.4,'出口1763亿美元，下降6.4%'),'imports_yoy':(-16.2,'进口1422亿美元，下降16.2%'),
        'exports_cny_yoy':(-6.2,'出口1.08万亿元，下降6.2%'),'imports_cny_yoy':(-16.1,'进口0.87万亿元，下降16.1%')}),
      ('https://www.chinanews.com/cj/2015/08-19/7477425.shtml','2015-08-19','2015-07-31','2015年08月19日',{
        'exports_yoy':(-8.3,'出口1951亿美元，下降8.3%'),'imports_yoy':(-8.1,'进口1521亿美元，下降8.1%')}),
      ('https://ifinance.ifeng.com/c/7Zy7VVQBdUU','2017-09-08','2017-08-31','2017-09-08',{
        'exports_yoy':(5.5,'中国8月出口同比(按美元计)5.5%'),'imports_yoy':(13.3,'中国8月进口同比(按美元计)13.3%')}),
      ('https://ifinance.ifeng.com/c/7Zy9efTaZge','2017-11-08','2017-10-31','2017-11-08',{
        'exports_yoy':(6.9,'以美元计价10月中国出口同比增长6.9%，进口同比增长17.2%'),
        'imports_yoy':(17.2,'以美元计价10月中国出口同比增长6.9%，进口同比增长17.2%')}),
      ('https://www.orientaldaily.com.my/news/business/2017/12/08/223380','2017-12-08','2017-11-30','2017-12-08',{
        'exports_yoy':(12.3,'以美元计，2017年11月份出口、进口同比增速均加快至12.3%、17.7%'),
        'imports_yoy':(17.7,'以美元计，2017年11月份出口、进口同比增速均加快至12.3%、17.7%')})]
    requests={r['url']:r for p in (PUBLIC/'requests').glob('*.json') if (r:=read(p))['status']=='ok'};out=[]
    for url,date,period,date_literal,values in entries:
        rec=requests[url];assert sha(ROOT/rec['path'])==rec['sha256']
        raw=(ROOT/rec['path']).read_bytes().decode(rec['encoding'],errors='replace')
        assert date_literal in raw,(url,'Publication date not verified')
        tree=html.fromstring(raw)
        for node in tree.xpath('//script|//style'):node.drop_tree()
        text=re.sub(r'\s+','',tree.text_content())
        for sid,(value,literal) in values.items():
            assert literal in text,(url,literal)
            if '_ytd_' in sid:
                assert pd.Timestamp(period).month==1 and values[sid.replace('_ytd','')][0]==value
            r=dated_fact(sid,value,period,date,rec,url,'ytd_yoy' if '_ytd_' in sid else 'yoy',quality='conservative_release_reconstructed',
                note='Reviewed contemporary press record quoting GAC/MOFCOM national totals, currency and observation month explicit. Available at this article date, not assumed earlier official release. January YTD equals January monthly by definition. Secondary publication; not strict PIT or authenticated original announcement.')
            r.update(source_name=urlparse(url).netloc,source_class='contemporary_press_record',extracted_text=literal,
                extraction_method='reviewed_literal_national_total_currency_period',reported_quantum=.1,
                publication_date_evidence=rec['path']+'#'+date_literal,revision_status='contemporary_report_no_complete_revision_archive')
            out.append(r)
    return out


def finalize_macro_views():
    """Reconcile publication editions before making eligibility/completeness views."""
    from scripts.data_foundation_v3 import quality
    configure_quality(quality)
    f=pd.read_parquet(MACRO/'macro_facts.parquet')
    months=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    editions={r['url']:r['year']*100+months.index(r['month_label'][:3])+1 for r in read(PUBLIC/'gac_monthly_sources.json')['tables']}
    f['publication_edition_order']=f.source_url.map(editions).fillna(0).astype(int)
    f['publication_edition_evidence']=f.source_url.map({r['url']:r['directory_evidence'] for r in read(PUBLIC/'gac_monthly_sources.json')['tables']})
    f['adjustment_note']=f.adjustment_note.str.replace('Publisher warns monthly data can be revised; no claim of first-release archive.','Different monthly editions are preserved; no claim of first-release archive or documented revision cause.',regex=False)
    f['quality_reason']=f.adjustment_note
    d=pd.read_parquet(AUDIT/'macro_coverage/source_reconciliation.parquet');records=f.set_index('source_record_id')
    edition_map=records.publication_edition_order.to_dict();source_map=records.source_name.to_dict()
    mask=d.left_record_id.map(source_map).eq('GACC English monthly bulletin')&d.right_record_id.map(source_map).eq('GACC English monthly bulletin')
    mask&=d.left_record_id.map(edition_map).ne(d.right_record_id.map(edition_map))&d.classification.eq('VALUE_CONFLICT')
    d.loc[mask,'classification']='DOCUMENTED_TABLE_EDITION_DIFFERENCE'
    d.loc[mask,'interpretation']='Both amounts/percentages verified against separate official monthly editions identified by publisher directory. Same upload day does not mean same edition. Retain all; latest known edition at actual page publication date wins. Statistical cause of change is not inferred.'
    unresolved=d[d.classification.eq('VALUE_CONFLICT')&d.left_available_at.eq(d.right_available_at)]
    remaining=set(unresolved.left_record_id)|set(unresolved.right_record_id)
    recover=f.source_name.eq('GACC English monthly bulletin')&f.certification_status.eq('VALUE_CONFLICT')&~f.source_record_id.isin(remaining)
    f.loc[recover,'certification_status']='ACCEPTED'
    frame(AUDIT/'macro_coverage/source_reconciliation.parquet',d)
    d.to_csv(AUDIT/'macro_coverage/source_reconciliation.csv',index=False,encoding='utf-8-sig')
    summary=read(AUDIT/'macro_coverage/reconciliation_summary.json')
    summary.update(counts=d.classification.value_counts().to_dict(),same_time_certified_conflict_ids=sorted(set(f.loc[f.certification_status.eq('VALUE_CONFLICT'),'source_record_id'])),edition_pairs_resolved=int(mask.sum()),edition_record_ids_restored=f.loc[recover,'source_record_id'].tolist())
    write(AUDIT/'macro_coverage/reconciliation_summary.json',summary)
    frame(MACRO/'macro_facts.parquet',f)
    frame(MACRO/'macro_vintages.parquet',f[['series_id','period_end','vintage_id','source_record_id','value','release_at','research_available_at','revision_status','source_id','quality_status','publication_edition_order','certification_status']])
    frame(MACRO/'macro_release_events.parquet',f[['source_record_id','series_id','period_end','release_at','research_available_at','release_time_basis','source_id','publication_date_evidence']])
    frame(MACRO/'macro_quality.parquet',f[['source_record_id','series_id','period_end','quality_status','certification_status','quality_reason']])
    quality.completeness(f)
    return f


def build():
    from .macro_supplements import reviewed,january_identities,dr007_quotes,safe_annual_reserves
    old=pd.read_parquet(ROOT/'data/standardized/macro/v3/macro_facts.parquet')
    extra=pd.DataFrame(gac_facts()+gac_preliminary_facts()+reviewed_mofcom()+reviewed_trade_reports()+reviewed()+dr007_quotes()+safe_annual_reserves());spec={x['series_id']:x for x in specifications()}
    extra['series_name']=extra.series_id.map(lambda s:spec[s]['series_name'])
    extra['series_group']=extra.series_id.map(lambda s:spec[s]['series_group'])
    extra['currency']=extra.series_id.map(lambda s:spec[s]['currency'])
    extra['concept_id']=extra.series_id;extra['statistical_scope_id']='as_registered';extra['parent_record_ids']='[]'
    extra['source_id']=extra.source_url.map(lambda u:identity([urlparse(u).netloc,u])[:24])
    extra['certification_status']=np.where(extra.quality_status.eq('blocked'),'VALUE_CONFLICT','ACCEPTED')
    f=pd.concat([old,extra],ignore_index=True)
    f=pd.concat([f,january_identities(f)],ignore_index=True)
    f=apply_scopes(f)
    f['series_name']=f.series_id.map(lambda s:spec[s]['series_name'])
    for c in ['release_at','research_available_at','retrieved_at']:f[c]=pd.to_datetime(f[c],utc=True).dt.tz_convert('Asia/Shanghai')
    f['data_foundation_version']=VERSION;f['dataset_id']='macro_facts'
    f['quality_reason']=f.adjustment_note
    f=f.drop_duplicates('source_record_id').sort_values(['series_id','period_end','research_available_at','source_record_id']).reset_index(drop=True)
    frame(MACRO/'macro_facts.parquet',f)
    frame(MACRO/'macro_vintages.parquet',f[['series_id','period_end','vintage_id','source_record_id','value','release_at','research_available_at','revision_status','source_id','quality_status']])
    frame(MACRO/'macro_release_events.parquet',f[['source_record_id','series_id','period_end','release_at','research_available_at','release_time_basis','source_id','publication_date_evidence']])
    frame(MACRO/'macro_quality.parquet',f[['source_record_id','series_id','period_end','quality_status','certification_status','quality_reason']])
    # Reuse the established period contract with every output redirected to v4.
    from scripts.data_foundation_v3 import quality
    configure_quality(quality)
    quality.reconcile(f);f=finalize_macro_views()
    write(AUDIT/'macro_coverage/new_fact_summary.json',{'inherited_rows':len(old),'new_rows':len(extra),'total_rows':len(f),'new_quality_counts':extra.quality_status.value_counts().to_dict()})
    print('macro',len(f),'facts;',len(extra),'new',flush=True)
    return f

if __name__=='__main__':build()
