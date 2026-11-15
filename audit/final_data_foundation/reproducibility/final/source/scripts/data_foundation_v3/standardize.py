"""Preserve historic facts and certify new records from literal source fields."""
import json
import re
from urllib.parse import urljoin,urlparse
import numpy as np
import pandas as pd
from lxml import html
from .common import ROOT,RAW,STANDARD,METADATA,AUDIT,TZ,read_json,write_json,save_frame,digest,identity
from .requirements import specifications,write_config
from scripts.macro_pipeline.supplement import fact,period,signed,table_values

def cached(url,params=None,method='GET'):
    p=RAW/'requests'/(identity([url,params,method])+'.json')
    if not p.exists():return None
    r=read_json(p)
    return r if r.get('status')=='ok' else None

def article(record):
    p=ROOT/record['path']
    if digest(p)!=record['sha256']:raise ValueError('Changed evidence: '+str(p))
    t=html.fromstring(p.read_bytes().decode(record['encoding'],errors='replace'))
    bodies=t.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," TRS_Editor ") or contains(concat(" ",normalize-space(@class)," ")," TRS_UEDITOR ") or @id="zoom"]')
    body=bodies[0] if bodies else t
    return body,re.sub(r'\s+','',body.text_content())

def dated_fact(sid,value,end,date,rec,url,measure='yoy',unit='%',quality='strict_pit_eligible',note='Original dated official bulletin; end-of-day policy'):
    end=pd.Timestamp(end);start=pd.Timestamp(end.year,1,1) if measure.startswith('ytd') else end.to_period('M').start_time
    release=pd.Timestamp(date,tz=TZ)+pd.Timedelta(hours=23,minutes=59,seconds=59)
    r=fact(sid,value,start,end,release,pd.Timestamp(rec['retrieved_at']),url,rec['path'],measure,unit,quality=quality,note=note)
    r['source_class']='dated_official_bulletin' if quality=='strict_pit_eligible' else 'contemporaneous_reprint'
    r['publication_date_evidence']=rec.get('date_evidence',rec['path'])
    if quality=='conservative_release_reconstructed':
        r.update(source_name='CCTV contemporaneous reproduction of PBOC report',release_time_basis='verified_reprint_date_end_of_day',time_quality='dated_contemporaneous_reprint',vintage_quality='contemporaneous_reprint_not_original',revision_status='contemporaneous_reproduction')
    return r

def pboc_extra():
    rows=pd.read_parquet(ROOT/'data/raw/macro/official_sources/pboc_historical_titles.parquet').to_dict('records')
    pages=read_json(ROOT/'data/raw/macro/official_sources/pboc_page_manifest.json');lists={};out=[]
    legacy=RAW/'pboc_legacy_tsf_titles.json'
    if legacy.exists():
        for x in read_json(legacy):
            r=cached(x['url'])
            if r:rows.append(x);pages[x['url']]=r
    for x in rows:
        if '地区' in x['title']:continue
        rec=pages.get(x['url'],{})
        if rec.get('status')!='ok':continue
        listing=x['search_evidence']
        if listing not in lists:
            t=html.fromstring((ROOT/listing).read_bytes());mapping={}
            for a in t.xpath('//a[@href]'):
                td=a.xpath('ancestor::td[1]');dates=td[0].xpath('.//span[@class="hui12"]/text()') if td else []
                if dates:mapping[urljoin('https://www.pbc.gov.cn',a.get('href'))]=dates[0].strip()
            lists[listing]=mapping
        date=lists[listing].get(x['url'])
        if not date or not re.fullmatch(r'20\d\d-\d\d-\d\d',date):continue
        end=period(x['title'],pd.Timestamp(date))
        if end is None:continue
        body,text=article(rec);rec={**rec,'date_evidence':listing}
        def add(sid,v,measure='yoy',unit='%'):
            if v is not None:out.append(dated_fact(sid,v,end,date,rec,x['url'],measure,unit))
        if '金融统计' in x['title']:
            add('rmb_loan_balance_yoy',signed(text,r'(?<!外币)(?<!本外币)人民币(?:各项)?贷款余额[^。]{0,45}?同比'))
            m=re.search(r'(?:国家)?外汇储备余额(?:为)?([\d.]+)(万亿美元|亿美元)',text)
            if m:
                add('fx_reserves',float(m[1])*(10000 if m[2]=='万亿美元' else 1),'stock','亿美元')
                out[-1]['reported_quantum']=(10**(-len(m[1].split('.')[1])) if '.' in m[1] else 1)*(10000 if m[2]=='万亿美元' else 1)
            # Earlier histories already present in the source archive are kept.
            if end.year<2014:
                add('m2_yoy',signed(text,r'广义货币[（(]M2[）)]余额[^。]{0,60}?同比'))
                add('m1_yoy',signed(text,r'狭义货币[（(]M1[）)]余额[^。]{0,60}?同比'))
            m=re.search(r'(?:前[一二两三四五六七八九十\d]+个月|全年|上半年|前三季度|一季度|1[—－–-]'+str(end.month)+r'月份?)[，,]?人民币贷款增加([\d.]+)(万亿元|亿元)',text)
            if m:add('rmb_loans_ytd_flow',float(m[1])*(10000 if m[2]=='万亿元' else 1),'ytd_flow','亿元')
        if '社会融资规模' in x['title']:
            # An optional 月份 and comma were missing from the previous extractor.
            m=re.search(r'(?:前[一二两三四五六七八九十\d]+个月|全年|上半年|前三季度|一季度|1[—－–-]'+str(end.month)+r'月份?)[，,]?社会融资规模增量(?:累计)?(?:为|是)([\d.]+)(万亿元|亿元)',text)
            if m:add('tsf_ytd_flow',float(m[1])*(10000 if m[2]=='万亿元' else 1),'ytd_flow','亿元')
            prefix=r'(?<![\d—－–-])'+str(end.month)+r'月份?(?:当月)?[，,]?(?:社会融资规模(?:增量)?|社会融资)(?:为|累计为|是)([\d.]+)(万亿元|亿元)'
            m=re.search(prefix,text)
            if m:add('tsf_month_flow',float(m[1])*(10000 if m[2]=='万亿元' else 1),'flow','亿元')
            if end.year<2015:
                m=re.search(r'(?:前[一二两三四五六七八九十\d]+个月|全年|上半年|前三季度|一季度|1[—－–-]'+str(end.month)+r'月份?)[，,]?社会融资规模(?:增量)?(?:累计)?(?:为|是)([\d.]+)(万亿元|亿元)',text)
                if m:add('tsf_ytd_flow',float(m[1])*(10000 if m[2]=='万亿元' else 1),'ytd_flow','亿元')
    url='https://jingji.cctv.cn/2025/02/14/ARTI2Qy8fsueEEJNOCjrjBPu250214.shtml';r=cached(url)
    if r:
        _,text=article(r)
        if '2025年1月金融统计数据报告' not in text:raise ValueError('Wrong CCTV report')
        for sid,pat in [('m2_yoy',r'广义货币[（(]M2[）)]余额[^。]{0,60}?同比'),('m1_new_yoy',r'狭义货币[（(]M1[）)]余额[^。]{0,60}?同比'),('rmb_loan_balance_yoy',r'月末人民币贷款余额[^。]{0,60}?同比')]:
            value=signed(text,pat)
            if value is None:raise ValueError('CCTV field missing '+sid)
            out.append(dated_fact(sid,value,'2025-01-31','2025-02-14',r,url,quality='conservative_release_reconstructed',note='Contemporaneous CCTV full report dated 2025-02-14; do not claim original PBOC page or backdate a 2026 reprint'))
        m=re.search(r'1月份人民币贷款增加([\d.]+)万亿元',text)
        if m:out.append(dated_fact('new_rmb_loans',float(m[1])*10000,'2025-01-31','2025-02-14',r,url,'flow','亿元','conservative_release_reconstructed','CCTV dated full PBOC January 2025 financial report; financial-institution loan flow, not the TSF RMB-loan component'))
    url='http://finance.people.com.cn/bank/n/2015/0811/c202331-27442434.html';r=cached(url)
    if r:
        _,text=article(r)
        match=re.search(r'今年4-7月，金融机构人民币各项贷款分别新增7079亿元、9008亿元、([\d.]+)万亿元和1.48万亿元',text)
        if match:
            x=dated_fact('new_rmb_loans',float(match[1])*10000,'2015-06-30','2015-08-11',r,url,'flow','亿元','conservative_release_reconstructed','PBOC spokesman quoted by People.cn on 2015-08-11 confirms June flow; availability is August 11, not assumed July first release. Avoids imprecise subtraction of rounded cumulative totals.')
            x['source_name']='People.cn dated quotation of PBOC spokesman';out.append(x)
    for url,date,end in [
        ('http://money.people.com.cn/n1/2016/0316/c218900-28204613.html','2016-03-16','2016-02-29'),
        ('https://jrj.sh.gov.cn/SCGK194/20250217/cad62bef05834e1a8128fc3d7ac94c79.html','2025-02-17','2025-01-31')]:
        r=cached(url)
        if not r:continue
        _,text=article(r)
        m=re.search(r'社会融资规模存量为([\d.]+)万亿元',text)
        yoy=signed(text,r'社会融资规模存量[^。]{0,60}?同比')
        for sid,value,measure,unit in [('tsf_stock',float(m[1]) if m else None,'stock','万亿元'),('tsf_stock_yoy',yoy,'yoy','%')]:
            if value is not None:
                x=dated_fact(sid,value,end,date,r,url,measure,unit,'conservative_release_reconstructed','Contemporaneous dated reproduction of PBOC stock report. Availability uses this page publication, never assumed original PBOC release.')
                x['source_name']='Dated PBOC report reproduction';out.append(x)
    return out

def nbs_extra():
    listing=RAW/'nbs_titles.json';out=[];fail=[]
    if not listing.exists():return out
    for x in read_json(listing):
        if 'stats.gov.cn/' not in x['url'] or not any(s in x['url'] for s in ['/zxfb','/xwfbh/fbhwd/']):continue
        rec=cached(x['url'])
        if not rec:continue
        title=x['title'];end=period(title,pd.Timestamp(x['date']))
        short_range=re.match(r'1[—－–-](\d{1,2})月份?',title)
        if short_range:
            end=pd.Timestamp(pd.Timestamp(x['date']).year,int(short_range[1]),1)+pd.offsets.MonthEnd(0)
        if end is None:
            # Headline may say first half, first three quarters, or annual economy.
            y=re.match(r'(20\d\d)年',title)
            if y:
                month=next((m for s,m in [('前三季度',9),('上半年',6),('一季度',3),('全年',12)] if s in title),12 if re.match(r'20\d\d年(?:国民经济|全国固定资产投资)',title) else None)
                if month is None and '经济' in title and pd.Timestamp(x['date']).month==1:month=12
                if month:end=pd.Timestamp(int(y[1]),month,1)+pd.offsets.MonthEnd(0)
            else:
                month=next((m for s,m in [('前三季度',9),('上半年',6),('一季度',3),('全年',12)] if title.startswith(s)),None)
                if month:
                    release=pd.Timestamp(x['date']);year=release.year-(month==12 and release.month<3)
                    end=pd.Timestamp(year,month,1)+pd.offsets.MonthEnd(0)
        if end is None or end>pd.Timestamp(x['date']):continue
        body,text=article(rec);rec={**rec,'date_evidence':x['search_evidence']}
        def add(sid,v,measure='yoy',unit='%'):
            if v is not None:out.append(dated_fact(sid,v,end,x['date'],rec,x['url'],measure,unit))
        if '固定资产投资' in title and '民间' not in title:
            # Explicit national non-rural-household scope, never private investment.
            v=signed(text,r'全国固定资产投资(?:[（(]不含农户[^）)]*[）)])?[\d.]+亿元[，,](?:按可比口径计算[，,])?(?:比上年同期|比上年|同比)')
            if v is None:v=signed(title,r'全国固定资产投资(?:[（(]不含农户[）)])?(?:同比)?')
            add('fai_ytd_yoy',v,'ytd_yoy')
        if '规模以上工业增加值' in title and end.month==2:
            add('industrial_va_ytd_yoy',signed(text,r'1[—－–-]2月份?[，,](?:全国)?规模以上工业增加值同比(?:实际)?'),'ytd_yoy')
        if '经济' in title:
            for label,sid in [('规模以上工业增加值','industrial_va_ytd_yoy'),('社会消费品零售总额','retail_sales_ytd_yoy')]:
                vals=table_values(body,r'(?:[一二三四五六七八九十]+[、.．])?'+label+r'(?:[（(]亿元[）)])?')
                if vals and end.month!=1:add(sid,vals[-1],'ytd_yoy')
            # NBS national economic table has current-month and cumulative columns.
            # Currency is specified in the row/header; never mix USD and CNY.
            for table in body.xpath('.//table'):
                tabletext=re.sub(r'\s+','',table.text_content())
                if '进出口总额' not in tabletext:continue
                trade_currency=None
                for tr in table.xpath('.//tr'):
                    cells=[re.sub(r'\s+','',td.text_content()) for td in tr.xpath('./td|./th')]
                    if not cells:continue
                    label=cells[0]
                    if '进出口' in label:
                        if '亿美元' in label:trade_currency='USD'
                        elif '亿元' in label:trade_currency='CNY'
                    side='exports' if re.fullmatch(r'(?:其中[:：]?)?出口(?:总额|额)?(?:[（(]亿元[）)])?',label) else 'imports' if re.fullmatch(r'(?:其中[:：]?)?进口(?:总额|额)?(?:[（(]亿元[）)])?',label) else None
                    if not side or len(cells)!=5:continue
                    # Four numeric cells: monthly level, monthly rate, YTD level, YTD rate.
                    if not trade_currency:continue
                    if re.fullmatch(r'-?\d+(?:\.\d+)?',cells[2]) and not (end.year>=2020 and end.month in [1,2]):add(side+('_cny_yoy' if trade_currency=='CNY' else '_yoy'),float(cells[2]))
                    if trade_currency=='CNY' and re.fullmatch(r'-?\d+(?:\.\d+)?',cells[4]):add(side+'_cny_ytd_yoy',float(cells[4]),'ytd_yoy')
    return out

def financial_extra():
    out=[];errors=[]
    requests=[read_json(p) for p in sorted((RAW/'requests').glob('*.json'))]
    for r in requests:
        if r['status']!='ok':continue
        url=r['url'];path=ROOT/r['path'];retrieved=pd.Timestamp(r['retrieved_at'])
        if 'data.mofcom.gov.cn/datamofcom/front/totalmonth/query' in url:
            j=json.loads(path.read_bytes())
            for x in j[0]:
                day=pd.Timestamp(str(x['trade_date'])[:4]+'-'+str(x['trade_date'])[4:6]+'-01')+pd.offsets.MonthEnd(0)
                for field,sid in [('export_per','exports_yoy'),('import_per','imports_yoy')]:
                    if x.get(field) is None:continue
                    out.append(fact(sid,x[field],day.to_period('M').start_time,day,retrieved,retrieved,url,r['path'],'yoy','%','M','latest_vintage_reconstructed','MOFCOM public monthly GAC USD table: explicit export_per/import_per fields; no historical publication timestamps; retain as present-day official compilation, never backdate'))
        elif 'LprHis' in url:
            for x in json.loads(path.read_bytes()).get('records',[]):
                day=pd.Timestamp(x['showDateCN'])
                if day<pd.Timestamp('2019-08-20'):continue
                f=fact('lpr_1y',x['1Y'],day.to_period('M').start_time,day+pd.offsets.MonthEnd(0),day.tz_localize(TZ)+pd.Timedelta(hours=23,minutes=59,seconds=59),retrieved,url,r['path'],'level','%','M','conservative_release_reconstructed','Official LPR history, 1Y field; post-2019 mechanism; quotation date verified, correction history unavailable')
                f['observation_date']=day;out.append(f)
        elif url.endswith('currency/prr-chrt.csv'):
            for line in path.read_text(encoding=r['encoding']).splitlines():
                cells=line.split(',')
                if len(cells)<9 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',cells[0]):continue
                if not cells[7]:continue
                day=pd.Timestamp(cells[0])
                out.append(fact('dr007',cells[7],day,day,day.tz_localize(TZ)+pd.Timedelta(hours=23,minutes=59,seconds=59),retrieved,url,r['path'],'level','%','D','conservative_release_reconstructed','Official prr-chart.html explicitly maps zero-based CSV column 7 to DR007. End-of-day weighted成交 rate; not R007/FDR007; no correction log'))
        elif 'safe.gov.cn' in url and '.xls' in url:
            try:
                sheets=pd.read_excel(path,header=None,sheet_name=None)
                for sheet,d in sheets.items():
                    # Long historical reserve table.
                    if '国家外汇储备规模' in str(d.iloc[:4].values):
                        for row in d.itertuples(index=False,name=None):
                            if not isinstance(row[0],(pd.Timestamp,__import__('datetime').datetime)):continue
                            day=pd.Timestamp(row[0])+pd.offsets.MonthEnd(0);v=pd.to_numeric(row[1],errors='coerce')
                            if pd.notna(v):out.append(fact('fx_reserves',v,day.to_period('M').start_time,day,retrieved,retrieved,url,r['path'],'stock','亿美元','M','latest_vintage_reconstructed','SAFE monthly historical compilation; Excel cell day is formatting residue, normalized to named month end; original release and revisions unavailable; usable only at retrieval'))
                        continue
                    labels=d.iloc[:,0].fillna('').astype(str)
                    indexes=labels[labels.str.contains('外汇储备')].index
                    if len(indexes)!=1:continue
                    i=indexes[0]
                    for col in range(1,d.shape[1]):
                        header=' '.join(d.iloc[:i,col].fillna('').astype(str));m=re.search(r'(20\d\d)[.年/-](\d{1,2})',header)
                        if not m or not ('美元' in header or 'USD' in header):continue
                        v=pd.to_numeric(str(d.iloc[i,col]).strip(),errors='coerce')
                        if pd.isna(v):continue
                        day=pd.Timestamp(int(m[1]),int(m[2]),1)+pd.offsets.MonthEnd(0)
                        out.append(fact('fx_reserves',v,day.to_period('M').start_time,day,retrieved,retrieved,url,r['path'],'stock','亿美元','M','latest_vintage_reconstructed',f'SAFE reserve assets sheet {sheet}, row {i+1}, column {col+1}; USD column, excludes SDR and total reserve assets; file URL date is not certified publication date'))
            except Exception as exc:errors.append({'url':url,'evidence_path':r['path'],'error':type(exc).__name__+': '+str(exc)[:120]})
    listing=RAW/'safe_release_titles.json'
    if listing.exists():
        for x in read_json(listing):
            r=cached(x['url'])
            if not r:continue
            _,text=article(r)
            date=re.search(r'发布日期[:：](20\d\d-\d\d-\d\d)',text)
            value=re.search(r'截至(20\d\d)年(\d{1,2})月(?:末|\d{1,2}日)[，,](?:我国)?外汇储备(?:规模|余额)(?:为)?([\d.]+)亿美元',text)
            if not date or not value:continue
            day=pd.Timestamp(int(value[1]),int(value[2]),1)+pd.offsets.MonthEnd(0)
            row=dated_fact('fx_reserves',float(value[3]),day,date[1],r,x['url'],'stock','亿美元',note='SAFE monthly dated news bulletin; rounded published value kept separately from precise archive table; displayed publication date, not URL directory date')
            row['reported_quantum']=10**(-len(value[3].split('.')[1])) if '.' in value[3] else 1
            out.append(row)
    # One independently dated contemporary GAC report, useful as a regression
    # anchor. No invented monthly interpolation for the remaining USD gaps.
    url='https://www.chinanews.com/cj/2014/02-12/5830156.shtml';r=cached(url)
    if r:
        _,text=article(r)
        for side,sid in [('出口','exports_yoy'),('进口','imports_yoy')]:
            value=signed(text,side+r'[\d.]+亿美元[，,]')
            if value is not None:
                f=dated_fact(sid,value,'2014-01-31','2014-02-12',r,url,quality='conservative_release_reconstructed',note='China News Service contemporaneous report explicitly attributes January 2014 USD goods trade to GAC, dated 2014-02-12')
                f['source_name']='China News Service contemporaneous GAC report';out.append(f)
    write_json(AUDIT/'spreadsheet_parse_failures.json',errors)
    return out

def build():
    write_config();spec={r['series_id']:r for r in specifications()}
    from scripts.macro_pipeline.govern import build as rebuild_legacy_raw
    base=rebuild_legacy_raw(write_outputs=False,retrieval_times=read_json(METADATA/'legacy_retrieval_times.json'))
    from .reprints import credit_reprints
    from .trade import historical_trade
    extra=pd.DataFrame(pboc_extra()+nbs_extra()+financial_extra()+credit_reprints()+historical_trade())
    f=pd.concat([base,extra],ignore_index=True)
    for c in ['release_at','research_available_at','retrieved_at']:f[c]=pd.to_datetime(f[c],utc=True).dt.tz_convert(TZ)
    for c in ['period_start','period_end','observation_date']:f[c]=pd.to_datetime(f[c])
    # The legacy parser downgraded five retail records after finding a wrong
    # publication date, but retained that date in research_available_at. Preserve
    # the submitted claim as evidence; every unverified vintage is retrieval-only.
    late=f.quality_status.eq('latest_vintage_reconstructed')
    bad=late&f.research_available_at.lt(f.retrieved_at)
    write_json(AUDIT/'legacy_availability_corrections.json',f.loc[bad,['source_record_id','series_id','period_end','release_at','research_available_at','retrieved_at','evidence_path']].to_dict('records'))
    f.loc[bad,'claimed_available_at']=f.loc[bad,'research_available_at'].astype(str)
    f.loc[bad,'release_at']=pd.NaT
    f.loc[bad,'release_time_basis']='legacy_unverified_date_rejected; gated_at_retrieval'
    f.loc[bad,'adjustment_note']=f.loc[bad,'adjustment_note'].astype(str)+'; v3 rejects inherited unverified availability and gates at retrieval'
    f.loc[late,'research_available_at']=f.loc[late,'retrieved_at']
    lpr=f.series_id.eq('lpr_1y')
    f.loc[lpr,'frequency']='M';f.loc[lpr,'period_end']=f.loc[lpr,'period_end']+pd.offsets.MonthEnd(0)
    f.loc[lpr,'period_start']=f.loc[lpr,'period_end'].dt.to_period('M').dt.start_time
    # January monthly and YTD flows are algebraically identical, without summing
    # different-vintage months or differencing rounded cumulative totals.
    jan=f[(f.period_end.dt.month==1)&f.series_id.isin(['tsf_month_flow','new_rmb_loans'])&f.quality_status.isin(['strict_pit_eligible','conservative_release_reconstructed'])].copy()
    jan['parent_record_ids']=jan.source_record_id.map(lambda x:json.dumps([x]))
    jan['series_id']=jan.series_id.map({'tsf_month_flow':'tsf_ytd_flow','new_rmb_loans':'rmb_loans_ytd_flow'})
    jan['measure_type']='ytd_flow';jan['source_record_id']=jan.source_record_id+'-january-ytd';jan['adjustment_note']='Exact January identity: monthly flow equals January year-to-date; no across-vintage summation'
    f=pd.concat([f,jan],ignore_index=True)
    # Same-source/day/quality term spread with explicit two-parent lineage.
    a=f[f.series_id=='cgb_10y'];b=f[f.series_id=='cgb_1y'];pair=a.merge(b,on=['period_end','research_available_at','quality_status','source_url'],suffixes=('_10','_1'))
    spread=[]
    for x in pair.to_dict('records'):
        row={c:x.get(c,x.get(c+'_10')) for c in f.columns};row.update(series_id='term_spread_10y_1y',value=x['value_10']-x['value_1'],unit='percentage_points',measure_type='spread',source_record_id=identity([x['source_record_id_10'],x['source_record_id_1'],'spread'])[:24],parent_record_ids=json.dumps([x['source_record_id_10'],x['source_record_id_1']]),adjustment_note='Same CFETS 11:30 government curve, same quotation date: 10Y minus 1Y; no mixed-source yield spread')
        spread.append(row)
    f=pd.concat([f,pd.DataFrame(spread)],ignore_index=True)
    from .scopes import split_tsf_scopes
    f=split_tsf_scopes(f)
    # Keep every source version; drop only identical records inherited twice.
    f=f.drop_duplicates(['series_id','period_end','source_record_id','value'])
    f['series_group']=f.series_id.map(lambda s:spec.get(s,{}).get('series_group','unregistered'))
    f['series_name']=f.series_id.map(lambda s:spec.get(s,{}).get('series_name',s))
    f['currency']=f.series_id.map(lambda s:spec.get(s,{}).get('currency','NA'))
    f['source_id']=f.source_url.map(lambda u:identity([urlparse(str(u)).netloc,str(u)])[:24])
    f['source_class']=f.get('source_class',pd.Series(index=f.index,dtype=str)).fillna('')
    mask=f.source_class.eq('');f.loc[mask,'source_class']=np.where(f.loc[mask,'quality_status'].eq('strict_pit_eligible'),'dated_official_bulletin',np.where(f.loc[mask,'quality_status'].eq('conservative_release_reconstructed'),'official_quote_history','historical_candidate_archive'))
    f['parent_record_ids']=f.get('parent_record_ids',pd.Series(index=f.index,dtype=str)).fillna('[]')
    f['publication_date_evidence']=f.get('publication_date_evidence',pd.Series(index=f.index,dtype=str)).fillna(f.evidence_path)
    f['certification_status']=np.where(f.quality_status.isin(['strict_pit_eligible','conservative_release_reconstructed']),'ACCEPTED',np.where(f.quality_status.eq('blocked'),'SEMANTIC_ERROR','VINTAGE_UNVERIFIED'))
    f['data_foundation_version']='data-foundation-v3.0.0'
    f=f.sort_values(['series_id','period_end','research_available_at','source_record_id']).reset_index(drop=True)
    save_frame(STANDARD/'macro_facts.parquet',f)
    save_frame(STANDARD/'macro_vintages.parquet',f[['series_id','period_end','vintage_id','source_record_id','value','release_at','research_available_at','revision_status','source_id','quality_status']])
    save_frame(STANDARD/'macro_release_events.parquet',f[['source_record_id','series_id','period_end','release_at','research_available_at','release_time_basis','source_id','publication_date_evidence']])
    print('Standardized',len(f),'rows,',f.series_id.nunique(),'series; new raw-derived records',len(extra),flush=True)
    return f
