"""Parse dated official announcements separately from latest historical tables."""
import re
from io import StringIO
from pathlib import Path
from urllib.parse import urljoin
import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
from lxml import html
from scripts.experiment_framework.common import ROOT,read_json,digest,identity

BASE=ROOT/'data/raw/macro'
TZ='Asia/Shanghai'

def fact(sid,value,start,end,release,retrieved,url,evidence,measure='yoy',unit='%',frequency='M',quality='strict_pit_eligible',note='Dated official announcement; preserved original text and SHA256'):
    return dict(series_id=sid,series_name=sid,series_group='',value=float(value),unit=unit,currency='CNY' if unit in ['亿元','万亿元','CNY/USD'] else 'NA',frequency=frequency,measure_type=measure,
                period_start=pd.Timestamp(start),period_end=pd.Timestamp(end),observation_date=pd.Timestamp(end),release_at=release,
                research_available_at=release if quality!='latest_vintage_reconstructed' else retrieved,
                release_time_basis='official_dated_announcement_end_of_day' if quality=='strict_pit_eligible' else 'official_historical_fixing_date_end_of_day; no correction archive',
                vintage_id=('announcement-'+str(release.date())) if quality=='strict_pit_eligible' else 'archive-'+str(retrieved.date()),revision_status='dated_announcement' if quality=='strict_pit_eligible' else 'historical_archive_no_correction_log',
                source_name='Official dated announcement' if quality=='strict_pit_eligible' else 'Historical archive',source_url=url,
                source_record_id=identity([sid,str(end),url,str(release),value])[:24],retrieved_at=retrieved,value_quality='official_body_verified' if quality=='strict_pit_eligible' else 'mapped_archive_field',
                time_quality='verified_official_date' if quality=='strict_pit_eligible' else 'conservative_end_of_quote_date',
                vintage_quality='announcement_value_verified' if quality=='strict_pit_eligible' else 'archive_without_correction_log',quality_status=quality,
                adjustment_note=note,original_series_id=sid,original_value=float(value),claimed_available_at='',evidence_path=evidence)

def period(title,release):
    m=re.search(r'(20\d{2})年(?:1[—－–-])?(\d{1,2})月',title)
    if m:year,month=int(m[1]),int(m[2])
    else:
        m=re.match(r'(\d{1,2})月',title)
        if m:month=int(m[1]);year=release.year-(month>release.month)
        else:
            y=re.match(r'(20\d{2})年',title)
            if not y:return None
            year=int(y[1]);month=next((m for k,m in [('前三季度',9),('上半年',6),('一季度',3),('全年',12)] if k in title),12 if any(k in title for k in ['金融统计数据报告','社会消费品零售总额','规模以上工业增加值','社会融资规模']) else 0)
            if not month:return None
    if not 1<=month<=12:return None
    return pd.Timestamp(year,month,1)+pd.offsets.MonthEnd(0)

def signed(text,pattern):
    m=re.search(pattern+r'(上涨|增长|下降|降低|减少)([\d.]+)%',text)
    if m:return float(m[2])*(-1 if m[1] in ['下降','降低','减少'] else 1)
    if re.search(pattern+r'持平',text):return 0.
    return None

def table_values(body,label):
    """Read the current-release summary row, retaining column order and signs."""
    for tr in body.xpath('.//tr'):
        cells=[re.sub(r'\s+','',td.text_content()) for td in tr.xpath('./td|./th')]
        if cells and re.fullmatch(label,cells[0]):
            return [float(c) for c in cells[1:] if re.fullmatch(r'-?\d+(?:\.\d+)?',c)]
    return []

def official_facts():
    output=[];listing_dates={}
    for owner,manifest_name in [('nbs','page_manifest.json'),('pboc','pboc_page_manifest.json')]:
        titles=BASE/f'official_sources/{owner}_historical_titles.parquet';manifest=BASE/'official_sources'/manifest_name
        if not titles.exists() or not manifest.exists():continue
        pages=read_json(manifest)
        for row in pd.read_parquet(titles).to_dict('records'):
            record=pages.get(row['url'],{})
            if record.get('status')!='ok':continue
            path=ROOT/record['path']
            if digest(path)!=record['sha256']:raise ValueError('Official evidence changed')
            soup=html.fromstring(path.read_bytes().decode(record['encoding'],errors='replace'))
            # Scripts and navigation can contain unrelated old numbers; parse article body.
            bodies=soup.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," TRS_Editor ") or contains(concat(" ",normalize-space(@class)," ")," TRS_UEDITOR ") or @id="zoom"]')
            body=bodies[0] if bodies else soup
            text=re.sub(r'\s+','',body.text_content());title=row['title']
            date=row.get('date')
            if owner=='pboc':
                if row['search_evidence'] not in listing_dates:
                    listing=BeautifulSoup((ROOT/row['search_evidence']).read_bytes(),'lxml');lookup={}
                    for a in listing.find_all('a',href=True):
                        td=a.find_parent('td');tag=td.find('span',class_='hui12') if td else None
                        if tag:lookup[urljoin('https://www.pbc.gov.cn',a['href'])]=tag.get_text(strip=True)
                    listing_dates[row['search_evidence']]=lookup
                date=listing_dates[row['search_evidence']].get(row['url'])
            if not date or not re.match(r'^20\d{2}-\d{2}-\d{2}$',str(date)):continue
            release=pd.Timestamp(date,tz=TZ)+pd.Timedelta(hours=23,minutes=59,seconds=59)
            end=period(title,release)
            if owner=='nbs' and '初步核算' in title and ('GDP' in title or '国内生产总值' in title):
                year=re.search(r'(20\d{2})年',title)
                quarter=re.search(r'([1234一二三四])季度',title)
                if year:
                    q=int(quarter[1]) if quarter and quarter[1].isdigit() else ('一二三四'.index(quarter[1])+1 if quarter else (2 if '上半年' in title else 4))
                    end=pd.Timestamp(int(year[1]),q*3,1)+pd.offsets.MonthEnd(0)
                    for table in body.xpath('.//table'):
                        if '比上年同期' not in table.text_content():continue
                        for tr in table.xpath('.//tr'):
                            cells=[re.sub(r'\s+','',td.text_content()) for td in tr.xpath('./td|./th')]
                            if cells and cells[0]=='GDP' and len(cells) in [3,5]:
                                retrieved=pd.Timestamp(record['retrieved_at']);evidence=record['path']
                                if len(cells)==5:
                                    output.append(fact('gdp_real_yoy',float(cells[-2]),end.to_period('Q').start_time,end,release,retrieved,row['url'],evidence,frequency='Q'))
                                elif q==1:
                                    output.append(fact('gdp_real_yoy',float(cells[-1]),end.to_period('Q').start_time,end,release,retrieved,row['url'],evidence,frequency='Q'))
                                output.append(fact('gdp_real_ytd_yoy',float(cells[-1]),pd.Timestamp(end.year,1,1),end,release,retrieved,row['url'],evidence,measure='ytd_yoy',frequency='Q'))
                                break
                        break
                    # Historical quarterly comparison tables are publication-time
                    # vintages too; do not backdate their later revisions.
                    current_year=None
                    for table in body.xpath('.//table'):
                        if 'GDP同比增长速度' not in re.sub(r'\s+','',table.text_content()):continue
                        for tr in table.xpath('.//tr'):
                            td=tr.xpath('./td|./th')
                            if len(td)<3:continue
                            label=re.sub(r'\s+','',td[0].text_content())
                            labels=re.findall(r'(?:(20\d{2})年)?([1-4])季度',label)
                            values=[float(v.strip()) for v in td[-1].itertext() if re.fullmatch(r'-?\d+(?:\.\d+)?',v.strip())]
                            if labels and len(labels)==len(values):
                                pairs=[]
                                for (yr,qr),value in zip(labels,values):
                                    if yr:current_year=int(yr)
                                    if current_year:pairs.append((current_year,int(qr),value))
                            elif re.fullmatch(r'20\d{2}',label) and len(td)==5:
                                pairs=[(int(label),i,float(c.text_content().strip())) for i,c in enumerate(td[1:],1) if re.fullmatch(r'-?\d+(?:\.\d+)?',c.text_content().strip())]
                            else:continue
                            for yr,qr,value in pairs:
                                pe=pd.Timestamp(yr,qr*3,1)+pd.offsets.MonthEnd(0)
                                if yr>=2014 and pe<=end:
                                    output.append(fact('gdp_real_yoy',value,pe.to_period('Q').start_time,pe,release,pd.Timestamp(record['retrieved_at']),row['url'],record['path'],frequency='Q',note='Quarterly comparison table value; available only at this announcement date, including historical revisions'))
                continue
            if end is None:continue
            # PMI is a survey of the named month and may be published before
            # its calendar end (e.g. 2022-01-30); that is a real release.
            if end.year<2014 or (end>release.tz_localize(None) and not ('采购经理指数' in title and end.to_period('M')==release.tz_localize(None).to_period('M'))):continue
            start=end.to_period('M').start_time
            retrieved=pd.Timestamp(record['retrieved_at'])
            def add(sid,val,measure='yoy',unit='%',start_override=None):
                if val is not None:
                    output.append(fact(sid,val,start if start_override is None else start_override,end,release,retrieved,row['url'],record['path'],measure,unit))
            if owner=='nbs':
                if '居民消费价格' in title:
                    vals=table_values(body,r'居民消费价格(?:总水平)?')
                    if len(vals)>=2:
                        add('cpi_mom',vals[0],'mom');add('cpi_yoy',vals[1])
                    else:
                        add('cpi_yoy',signed(text,r'(?:全国)?居民消费价格(?:总水平)?[^。]{0,25}?同比'))
                        add('cpi_mom',signed(text,r'(?:全国)?居民消费价格(?:总水平)?[^。]{0,25}?环比'),'mom')
                    vals=table_values(body,r'(?:其中：)?不包括食品和能源')
                    add('core_cpi_yoy',vals[1] if len(vals)>=2 else signed(text,r'(?:扣除食品和能源价格的)?核心CPI同比'))
                if '工业生产者' in title and '价格' in title:
                    vals=table_values(body,r'(?:一[、.．])?工业生产者出厂价格')
                    if len(vals)>=2:
                        add('ppi_mom',vals[0],'mom');add('ppi_yoy',vals[1])
                    else:
                        add('ppi_yoy',signed(text,r'(?:全国)?工业生产者出厂价格[^。]{0,25}?同比'))
                        add('ppi_mom',signed(text,r'(?:全国)?工业生产者出厂价格[^。]{0,25}?环比'),'mom')
                if '采购经理指数' in title or '非制造业商务活动指数' in title:
                    # A non-manufacturing bulletin must never supply manufacturing orders.
                    if '非制造业' not in title:
                        m=re.search(r'(?<!非)制造业采购经理指数(?:[（(]PMI[）)])?为([\d.]+)%',text)
                        if m:add('pmi_mfg',float(m[1]),'level','index')
                        section=text.split('二、非制造业')[0]
                        m=re.search(r'新订单指数(?:为)?([\d.]+)%',section)
                        if m:add('pmi_new_orders',float(m[1]),'level','index')
                    m=re.search(r'非制造业商务活动指数为([\d.]+)%',text)
                    if m:add('pmi_nonmfg',float(m[1]),'level','index')
                for sid,term in [('industrial_va','规模以上工业增加值'),('retail_sales','社会消费品零售总额')]:
                    if term not in title:continue
                    # Sentence starts with the single month, excluding any 1-N month range.
                    prefix=rf'(?<![\d—－–-]){end.month}月份?[，,]?(?:全国)?{term}'
                    val=signed(text,prefix+(r'同比(?:实际)?' if sid=='industrial_va' else r'[\d.]+亿元[，,]同比(?:名义)?'))
                    if val is not None:add(sid+'_yoy',val)
                    # The summary table has month and year-to-date columns;
                    # Jan-Feb releases have only a cumulative column.
                    vals=table_values(body,term)
                    ytd=vals[-1] if vals else signed(text,rf'1[—－–-]{end.month}月份?[，,]?(?:全国)?{term}'+(r'同比(?:实际)?' if sid=='industrial_va' else r'[\d.]+亿元[，,]同比(?:名义)?'))
                    add(sid+'_ytd_yoy',ytd,'ytd_yoy',start_override=pd.Timestamp(end.year,1,1))
            else:
                add('m2_yoy',signed(text,r'广义货币[（(]M2[）)]余额[^。]{0,60}?同比'))
                add('m1_yoy' if end.year<2025 else 'm1_new_yoy',signed(text,r'狭义货币[（(]M1[）)]余额[^。]{0,60}?同比'))
                add('tsf_stock_yoy',signed(text,r'社会融资规模存量[^。]{0,60}?同比'))
                m=re.search(r'社会融资规模存量为([\d.]+)万亿元',text)
                if m:add('tsf_stock',float(m[1]),'stock','万亿元')
                m=re.search(r'(?<![\d—－–-])'+str(end.month)+r'月份?(?:当月)?[，,]?社会融资规模增量(?:为|累计为)([\d.]+)(万亿元|亿元)',text)
                if m:add('tsf_month_flow',float(m[1])*(10000 if m[2]=='万亿元' else 1),'flow','亿元')
                m=re.search(r'(?:前[一二两三四五六七八九十\d]+个月|全年|上半年|前三季度|一季度|1[—－–-]'+str(end.month)+r'月)社会融资规模增量(?:累计)?(?:为|是)([\d.]+)(万亿元|亿元)',text)
                if m:add('tsf_ytd_flow',float(m[1])*(10000 if m[2]=='万亿元' else 1),'ytd_flow','亿元',pd.Timestamp(end.year,1,1))
                m=re.search(r'(?:当月|'+str(end.month)+r'月份?)[，,]?人民币贷款(增加|减少)([\d.]+)(万亿元|亿元)',text)
                if m:add('new_rmb_loans',float(m[2])*(10000 if m[3]=='万亿元' else 1)*(-1 if m[1]=='减少' else 1),'flow','亿元')
                m=re.search(r'(?:前[一二三四五六七八九十]+个月|全年|上半年|前三季度|一季度)人民币贷款增加([\d.]+)(万亿元|亿元)',text)
                if m:add('rmb_loans_ytd_flow',float(m[1])*(10000 if m[2]=='万亿元' else 1),'ytd_flow','亿元',pd.Timestamp(end.year,1,1))
    return output

def archive_facts():
    output=[];now=pd.Timestamp.now(tz=TZ)
    jobs={
      'RPT_ECONOMY_RMB_LOAN':{'RMB_LOAN':('new_rmb_loans','flow','亿元'),'RMB_LOAN_ACCUMULATE':('rmb_loans_ytd_flow','ytd_flow','亿元')},
      'RPT_ECONOMY_INDUS_GROW':{'BASE_SAME':('industrial_va_yoy','yoy','%'),'BASE_ACCUMULATE':('industrial_va_ytd_yoy','ytd_yoy','%')},
      'RPT_ECONOMY_TOTAL_RETAIL':{'RETAIL_TOTAL_SAME':('retail_sales_yoy','yoy','%'),'RETAIL_ACCUMULATE_SAME':('retail_sales_ytd_yoy','ytd_yoy','%')},
      'RPTA_WEB_RATE':{'LPR1Y':('lpr_1y','level','%')}}
    for report,cols in jobs.items():
        path=BASE/f'third_party_sources/eastmoney/{report}.parquet'
        if not path.exists():continue
        # Retrieval timestamp is pinned to raw artifact creation, not every normalization run.
        retrieved=pd.Timestamp(path.stat().st_mtime,unit='s',tz='UTC').tz_convert(TZ)
        for row in pd.read_parquet(path).to_dict('records'):
            day=pd.Timestamp(row.get('REPORT_DATE',row.get('TRADE_DATE')))
            end=day if report=='RPTA_WEB_RATE' else day+pd.offsets.MonthEnd(0)
            if end.year<2014:continue
            if report=='RPTA_WEB_RATE' and day<pd.Timestamp('2019-08-20'):continue
            for col,(sid,measure,unit) in cols.items():
                if pd.isna(row.get(col)):continue
                # Combined February cannot enter a monthly flow/rate series.
                if end.month==2 and sid in ['industrial_va_yoy','retail_sales_yoy']:continue
                start=pd.Timestamp(end.year,1,1) if measure.startswith('ytd') else (day if report=='RPTA_WEB_RATE' else end.to_period('M').start_time)
                loan=report=='RPT_ECONOMY_RMB_LOAN'
                output.append(fact(sid,row[col],start,end,retrieved,retrieved,'https://datacenter-web.eastmoney.com/api/data/v1/get?reportName='+report,path.relative_to(ROOT).as_posix(),measure,unit,quality='blocked' if loan else 'latest_vintage_reconstructed',note='Explicit provider field '+col+('; substantial differences from official announced loan flows; historical definition/revision unverified, exclude' if loan else '; statistical month normalized to period end; not historical first release')))
    # Official financial quote histories: values and quote dates verified; historical
    # correction vintages are unavailable, so these are explicitly reconstructed.
    folder=BASE/'official_sources/financial';manifest=folder/'manifest.json'
    if manifest.exists():
        retrieved=pd.Timestamp(read_json(manifest)['retrieved_at'])
        for name,cols,datecol in [('shibor',{'ON':'shibor_on','1W':'shibor_1w','3M':'shibor_3m'},'showDateCN'),('govyield',{'oneRate':'cgb_1y','tenRate':'cgb_10y'},'dateString')]:
            path=folder/f'{name}.parquet'
            for row in pd.read_parquet(path).to_dict('records'):
                day=pd.Timestamp(row[datecol]);release=day.tz_localize(TZ)+pd.Timedelta(hours=23,minutes=59,seconds=59)
                for col,sid in cols.items():
                    if pd.isna(row.get(col)) or row.get(col) in ['','---','--']:continue
                    output.append(fact(sid,float(row[col]),day,day,release,retrieved,'https://www.chinamoney.com.cn/chinese/'+('bkshibor/' if name=='shibor' else 'sddsintigy/'),path.relative_to(ROOT).as_posix(),'level','%','D','conservative_release_reconstructed',note='Official historical fixing; available after quotation day end; no historical correction log. '+('CFETS 11:30 mean government yield curve; not ChinaBond' if name=='govyield' else 'Shibor fixing; tenor explicitly identified by series_id')))
    path=BASE/'source_references/safe_xlsx.xlsx'
    if path.exists():
        df=pd.read_excel(path);retrieved=pd.Timestamp(path.stat().st_mtime,unit='s',tz='UTC').tz_convert(TZ)
        for date,value in df.iloc[:,:2].itertuples(index=False,name=None):
            day=pd.to_datetime(date,errors='coerce')
            if pd.isna(day) or day.year<2014:continue
            release=day.tz_localize(TZ)+pd.Timedelta(hours=23,minutes=59,seconds=59)
            output.append(fact('usdcny_fixing',float(value)/100,day,day,release,retrieved,'https://www.safe.gov.cn/safe/2020/1218/17833.html',path.relative_to(ROOT).as_posix(),'level','CNY/USD','D','conservative_release_reconstructed',note='SAFE official USD fixing per 100 USD divided by 100; archived quote with no correction log'))
    path=BASE/'source_references/safe_2026.html'
    if path.exists():
        soup=BeautifulSoup(path.read_bytes(),'lxml');table=soup.select_one('#InfoTable')
        retrieved=pd.Timestamp(path.stat().st_mtime,unit='s',tz='UTC').tz_convert(TZ)
        for tr in table.find_all('tr'):
            cells=[td.get_text(strip=True) for td in tr.find_all('td')]
            if len(cells)<2 or not re.match(r'^2026-\d{2}-\d{2}$',cells[0]):continue
            day=pd.Timestamp(cells[0]);release=day.tz_localize(TZ)+pd.Timedelta(hours=23,minutes=59,seconds=59)
            output.append(fact('usdcny_fixing',float(cells[1])/100,day,day,release,retrieved,'https://www.safe.gov.cn/AppStructured/hlw/RMBQuery.do',path.relative_to(ROOT).as_posix(),'level','CNY/USD','D','conservative_release_reconstructed',note='SAFE 2026 dated USD fixing per 100 USD divided by 100; no correction log'))
    return output

def build():return official_facts()+archive_facts()
