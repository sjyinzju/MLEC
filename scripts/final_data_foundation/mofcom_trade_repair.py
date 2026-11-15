"""Read public MOFCOM trade tables in memory; retain only normalized evidence."""
import concurrent.futures
import hashlib
import re
import time
from curl_cffi import requests
from lxml import html
from .common import ROOT, MACRO, write, read, frame, pd
BASE = 'https://fdi.mofcom.gov.cn'
HEADERS = {'Referer': BASE+'/come-datatongji-con.html?id=16021'}


def request(path, payload=None):
    for attempt in range(3):
        try:
            r = requests.request('POST' if payload else 'GET', BASE+path, json=payload,
                impersonate='chrome', headers=HEADERS, timeout=20)
            r.raise_for_status()
            d = r.json()
            assert d['code'] == 0
            return d
        except Exception:
            if attempt == 2: raise
            time.sleep(.3)


def catalogue():
    # The broad catalogue sorts ties unstably across pages. Narrow each query
    # to a year/month/title, and verify its unique count against the API total.
    def query(keyword):
        payload = {'menuId':1, 'page':1, 'classifyId':12, 'keyWord':keyword}
        first = request('/cipa-api/statistics/web/list', payload)
        rows = {r['id']:r for r in first['data']}
        for page in range(2, (first['total']+9)//10+1):
            rows.update({r['id']:r for r in request('/cipa-api/statistics/web/list', {**payload, 'page':page})['data']})
        return list(rows.values()), dict(keyword=keyword, expected=first['total'], unique=len(rows))
    keywords = [f'{year}年{month}' for year in range(2020,2027) for month in ['1月','2月','1至1月','1至2月']]
    rows = {};checks = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for records, check in pool.map(query, keywords):
            rows.update({r['id']:r for r in records});checks.append(check)
    selected = [r for r in rows.values() if '人民币' in r['name'] and re.search(r'202[0-6]年(?:1至[12]|[12])月', r['name'])]
    write(ROOT/'data/metadata/mofcom_trade_catalogue.json', {'source':BASE, 'catalogue_rows_checked':len(rows), 'queries':checks, 'tables':selected})
    print('CATALOGUE', len(rows), 'SELECTED', len(selected), flush=True)
    return selected


def table(identifier):
    d = request('/cipa-api/statistics/web/get?id='+str(identifier))['data']
    tree = html.fromstring(d['content'])
    rows = [[re.sub(r'\s+', ' ', cell.text_content()).strip() for cell in row.xpath('./th|./td')] for row in tree.xpath('//tr')]
    return {'id': identifier, 'name':d['name'], 'issueDate':d['issueDate'], 'source':d['source'],
            'url':BASE+'/come-datatongji-con.html?id='+str(identifier),
            'content_sha256':hashlib.sha256(d['content'].encode()).hexdigest(), 'rows':rows}


def collect_verified():
    records = []
    # Reviewed table types: January enterprise tables and February mode tables.
    sources = [(14983,2021,1,'exports'), (14985,2021,1,'imports'),
        (15750,2023,1,'exports'), (15752,2023,1,'imports'),
        (16021,2024,1,'exports'), (16023,2024,1,'imports'),
        (15009,2021,2,None), (15749,2023,2,None), (16019,2024,2,None)]
    for identifier, year, month, direction in sources:
        d = table(identifier)
        assert d['source'] == '海关总署' and '人民币' in d['name'] and str(year)+'年' in d['name']
        k = next(i for i,r in enumerate(d['rows']) if r and r[0] == '总值')
        amount, rates = d['rows'][k:k+2]
        period = pd.Timestamp(year,month,1)+pd.offsets.MonthEnd(0)
        if direction:
            assert '1至1月' in d['name'] and len(amount) == 6 and len(rates) == 5
            values = [(direction, float(rates[0]), float(amount[1].replace(',','')))]
        else:
            assert '2月进出口商品贸易方式' in d['name'] and len(amount) == 7 and len(rates) == 6
            assert d['rows'][k-1] == ['2月','1至2月']*3
            values = [('exports',float(rates[2]),float(amount[3].replace(',',''))),
                      ('imports',float(rates[4]),float(amount[5].replace(',','')))]
        for direction, value, money in values:
            for suffix in ['yoy','ytd_yoy'] if month == 1 else ['yoy']:
                records.append(dict(series_id=direction+'_cny_'+suffix, period_end=period,
                    value=value, amount_10000_cny=money, source_url=d['url'], publication_date=d['issueDate'],
                    source_table_title=d['name'], content_sha256=d['content_sha256'],
                    selected_total_cells=__import__('json').dumps([amount,rates],ensure_ascii=False),
                    rationale='January monthly equals January YTD' if month == 1 else 'Literal monthly percent column, not cumulative percent',
                    retrieved_at=pd.Timestamp.now(tz='Asia/Shanghai')))
    evidence = pd.DataFrame(records)
    assert len(evidence) == 18 and not evidence.duplicated(['series_id','period_end']).any()
    frame(ROOT/'data/metadata/mofcom_trade_repairs.parquet', evidence)
    return evidence


def collect_attributed():
    records=[]
    for year,identifier in [(2025,1218267),(2026,1261786)]:
        url=f'https://www.chyxx.com/shuju/{identifier}.html'
        r=requests.get(url,impersonate='chrome',timeout=25);r.raise_for_status()
        tree=html.fromstring(r.content)
        article=__import__('json').loads(tree.xpath('//script[@type="application/ld+json"]/text()')[0])
        description=article['description']
        assert str(year)+'年1月' in description and '海关口径' in description and '海关总署' in tree.text_content()
        for direction,word in [('exports','出口'),('imports','进口')]:
            match=re.search(word+r'额为([\d.]+)亿元，同比(增长|下滑|下降)([\d.]+)%',description)
            assert match,description
            amount=float(match[1]);value=float(match[3])*(-1 if match[2]!='增长' else 1)
            for suffix in ['yoy','ytd_yoy']:
                records.append(dict(series_id=direction+'_cny_'+suffix,period_end=pd.Timestamp(year,1,31),
                    value=value,amount_10000_cny=amount*10000,source_url=url,
                    publication_date=article['datePublished'][:10],source_table_title=article['headline'],
                    content_sha256=hashlib.sha256(r.content).hexdigest(),selected_total_cells=__import__('json').dumps({'value':value,'amount_100m_cny':amount}),
                    rationale='Dated third-party reproduction attributed to GAC; national CNY total; January monthly equals YTD; clock is reproduction date, never original first release',
                    retrieved_at=pd.Timestamp.now(tz='Asia/Shanghai')))
    evidence=pd.DataFrame(records);frame(ROOT/'data/metadata/attributed_trade_repairs.parquet',evidence)
    return evidence


def apply(evidence):
    f = pd.read_parquet(MACRO/'macro_facts.parquet')
    additions = []
    for r in evidence.itertuples(index=False):
        official = 'fdi.mofcom.gov.cn' in r.source_url
        base = f[f.series_id.eq(r.series_id)].iloc[-1].to_dict()
        at = pd.Timestamp(r.publication_date,tz='Asia/Shanghai')+pd.Timedelta(hours=23,minutes=59,seconds=59)
        identifier = 'mofcom:trade:'+hashlib.sha256((r.series_id+str(r.period_end)+r.source_url).encode()).hexdigest()[:24]
        base.update(value=r.value, original_value=r.value, period_start=r.period_end.replace(day=1),
            period_end=r.period_end, observation_date=r.period_end, release_at=at, research_available_at=at,
            release_time_basis='Dated official reproduction at conservative end of day; no inferred earlier first release',
            vintage_id='mofcom-trade-'+r.publication_date, revision_status='dated_official_reproduction',
            source_name='海关总署，商务部中国投资指南网转载', source_url=r.source_url,
            source_record_id=identifier, source_id='mofcom:trade', retrieved_at=r.retrieved_at,
            quality_status='conservative_release_reconstructed', certification_status='ACCEPTED',
            value_quality='official_total_and_monthly_yoy_column_verified',time_quality='dated_reproduction_end_of_day',
            vintage_quality='dated_publication_reconstruction', adjustment_note=r.rationale,
            original_series_id=r.series_id,claimed_available_at=None,
            evidence_path='data/metadata/mofcom_trade_repairs.parquet',source_class='dated_official_bulletin',
            publication_date_evidence=r.source_url,reported_quantum=.1,extracted_text=None,
            extraction_method='reviewed_total_cells_from_official_public_api',extraction_evidence=None,
            parent_record_ids='[]',statistical_scope_id='as_registered',reconstructed_quote_at=pd.NaT,
            evidence_page=None,scope_definition_evidence=r.source_url,quality_reason=r.rationale,
            publication_edition_order=0,publication_edition_evidence=r.source_url,
            data_foundation_version='practical-research-data-v5')
        if not official:
            base.update(source_record_id=identifier.replace('mofcom:trade:','attributed:trade:'),
                vintage_id='attributed-trade-'+r.publication_date,revision_status='dated_attributed_reproduction',
                source_id='chyxx:attributed_gac_trade',source_name='智研咨询，注明海关总署来源',
                source_class='attributed_historical_publication',quality_status='historical_reconstructed',
                value_quality='reviewed_attributed_national_cny_yoy',
                release_time_basis='Dated attributed reproduction at end of day; never inferred original first release',
                evidence_path='data/metadata/attributed_trade_repairs.parquet')
        additions.append(base)
    f = f[~f.source_record_id.isin([r['source_record_id'] for r in additions])]
    f = pd.concat([f,pd.DataFrame(additions)],ignore_index=True)
    assert f.source_record_id.is_unique
    frame(MACRO/'macro_facts.parquet',f)
    for name in ['macro_vintages','macro_release_events','macro_quality']:
        path=MACRO/(name+'.parquet');columns=pd.read_parquet(path).columns
        frame(path,f[list(columns)])
    print('TRADE_ADMITTED',len(additions),flush=True)


if __name__ == '__main__':
    apply(collect_verified())
    apply(collect_attributed())
