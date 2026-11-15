"""Reviewed bounded supplements; publication dates are never inferred from periods."""
import re
from urllib.parse import urlparse
from lxml import html
from .common import *
from .collect import PUBLIC
from scripts.data_foundation_v3.standardize import dated_fact
from scripts.common import identity
from scripts.data_foundation_v3.requirements import specifications


ENTRIES=[
 ('https://www.mof.gov.cn/zhengwuxinxi/caijingshidian/zyzfmhwz/201501/t20150115_1180479.htm','2015-01-15','2014-12-31','2015年1月15日',{
  'tsf_ytd_flow':(164600.,'2014年社会融资规模为16.46万亿元')}),
 ('https://www.gdjr.gov.cn/gdjr/jrzx/jryw/content/post_2077.html','2016-01-22','2015-12-31','2016-01-22',{
  'tsf_ytd_flow':(154100.,'2015年社会融资规模增量为15.41万亿元')}),
 ('https://app.www.gov.cn/govdata/gov/201701/20/397562/article.html','2017-01-21','2016-12-31','2017-01-21',{
  'tsf_ytd_flow':(178000.,'全年社会融资规模增量为17.8万亿元')}),
 ('https://www.cnfin.com/rmb-xh08/a/20180112/1744806.shtml','2018-01-12','2017-12-31','2018年01月12日',{
  'tsf_ytd_flow':(194400.,'2017年社会融资规模增量累计为19.44万亿元')}),
 ('https://jrj.sh.gov.cn/SCGK194/20200117/0031-158034.html','2020-01-17','2019-12-31','2020-01-17',{
  'tsf_ytd_flow':(255800.,'2019年社会融资规模增量累计为25.58万亿元')}),
 ('https://www.ndrc.gov.cn/fggz/fgzh/gnjjjc/hbjr/202101/t20210128_1266089.html','2021-01-28','2020-12-31','2021/01/28',{
  'tsf_ytd_flow':(348600.,'2020年社会融资规模增量累计为34.86万亿元')}),
 ('https://www.ndrc.gov.cn/fggz/fgzh/gnjjjc/hbjr/202201/t20220125_1313247.html','2022-01-25','2021-12-31','2022/01/25',{
  'tsf_ytd_flow':(313500.,'2021年社会融资规模增量累计为31.35万亿元')}),
 ('https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/lastest/rptid/829487769184/index.phtml?cref=cj','2026-04-14','2026-03-31','2026-04-14',{
  'tsf_month_flow':(52260.,'2026年3月社会融资规模增量为52260亿元')}),
 ('https://finance.sina.com.cn/roll/2026-07-15/doc-inihxaez8011742.shtml','2026-07-15','2026-06-30','2026年07月15日',{
  'tsf_month_flow':(33600.,'6月单月新增社融3.36万亿元')}),
 ('https://www.jjckb.cn/2014-08/14/content_516958.htm','2014-08-14','2014-07-31','2014-08-14',{
  'rmb_loans_ytd_flow':(61300.,'人民币贷款增加6.13万亿元'),
  'tsf_ytd_flow':(108100.,'2014年1-7月，社会融资规模为10.81万亿元')}),
 ('https://www.mof.gov.cn/zhengwuxinxi/caijingshidian/zyzfmhwz/201501/t20150115_1180480.htm','2015-01-15','2014-12-31','2015年1月15日',{
  'rmb_loans_ytd_flow':(97800.,'2014年人民币贷款增加9.78万亿元')}),
 ('https://finance.eastmoney.com/a/202607153807796980.html','2026-07-15','2026-06-30','2026年07月15日',{
  'new_rmb_loans':(16100.,'6月新增人民币贷款1.61万亿元')}),
 ('https://www.thepaper.cn/newsDetail_forward_33367281','2026-06-12','2026-05-31','2026-06-12',{
  'new_rmb_loans':(5200.,'具体到5月，人民币贷款增加5200亿元'),'tsf_month_flow':(20293.,'社会融资规模增量为20293亿元'),
  'rmb_loans_ytd_flow':(91100.,'前五个月人民币贷款增加9.11万亿元'),'tsf_ytd_flow':(174800.,'前五个月社会融资规模增量累计为17.48万亿元')}),
 ('https://jrb.qingdao.gov.cn/jrdt/202607/t20260715_10677449.shtml','2026-07-15','2026-06-30','2026-07-15',{
  'rmb_loans_ytd_flow':(107200.,'上半年人民币贷款增加10.72万亿元'),'tsf_ytd_flow':(208400.,'上半年社会融资规模增量累计为20.84万亿元')}),
 ('https://www.cnfin.com/news-xh08/a/20150508/1495873.shtml','2015-05-08','2015-04-30','2015年05月08日',{
  'exports_cny_ytd_yoy':(1.8,'出口4.23万亿元，增长1.8%'),'imports_cny_ytd_yoy':(-17.,'进口3.27万亿元，下降17%')}),
 ('http://www.china.com.cn/zhibo/zhuanti/ch-xinwen/2014-07/10/content_32909911.htm','2014-07-10','2014-06-30','2014年7月10日',{
  'exports_cny_yoy':(6.3,'出口1.15万亿元，增长6.3%'),'imports_cny_yoy':(4.8,'进口0.96万亿元，增长4.8%')}),
 ('https://www.jjckb.cn/2014-03/08/content_494658.htm','2014-03-08','2014-02-28','2014-03-08',{
  'exports_cny_yoy':(-20.4,'出口6965.2亿元，下降20.4%'),'imports_cny_yoy':(7.,'进口8363.1亿元，增长7%'),
  'exports_cny_ytd_yoy':(-4.3,'出口1.96万亿元，下降4.3%'),'imports_cny_ytd_yoy':(7.,'进口1.91万亿元，增长7%')}),
 ('https://www.chinanews.com/cj/2014/05-08/6147828.shtml','2014-05-08','2014-04-30','2014年05月08日',{
  'exports_cny_yoy':(-1.4,'出口1.16万亿元，下降1.4%'),'imports_cny_yoy':(-1.3,'进口1.04万亿元，下降1.3%'),
  'exports_cny_ytd_yoy':(-4.8,'出口4.16万亿元，下降4.8%'),'imports_cny_ytd_yoy':(-1.2,'进口3.94万亿元，下降1.2%')}),
 ('https://cpc.people.com.cn/n/2014/0609/c83083-25121530.html','2014-06-09','2014-05-31','2014年06月09日',{
  'exports_cny_yoy':(5.4,'出口1.2万亿元，由前4个月的下降4.8%转为增长5.4%'),'imports_cny_yoy':(-2.9,'进口0.98万亿元，下降2.9%'),
  'exports_cny_ytd_yoy':(-2.7,'出口5.4万亿元、进口4.9万亿元，分别下降2.7%和1.6%'),
  'imports_cny_ytd_yoy':(-1.6,'出口5.4万亿元、进口4.9万亿元，分别下降2.7%和1.6%')}),
 ('http://finance.people.com.cn/n/2014/0710/c1004-25264299.html','2014-07-10','2014-06-30','2014年07月10日',{
  'exports_cny_ytd_yoy':(-1.2,'出口6.5万亿元，下降1.2%'),'imports_cny_ytd_yoy':(-.6,'进口5.9万亿元，下降0.6%')}),
 ('https://www.cnfin.com/news-xh08/a/20150819/1541008.shtml','2015-08-19','2015-07-31','2015年08月19日',{
  'exports_cny_yoy':(-8.9,'出口1.19万亿元，下降8.9%'),'imports_cny_yoy':(-8.6,'进口0.93万亿元，下降8.6%')}),
 ('https://www.chinanews.com/cj/2015/08-10/7457374.shtml','2015-08-10','2015-07-31','2015年08月10日',{
  'exports_cny_ytd_yoy':(-.9,'出口7.75万亿元，微降0.9%'),'imports_cny_ytd_yoy':(-14.6,'进口5.88万亿元，下降14.6%')}),
 ('https://jrjgj.suzhou.gov.cn/szdfjr/jrsx/202502/7bb4052662cc4d76a7d9e10c7aaea8ad.shtml','2025-02-17','2025-01-31','2025-02-17',{
  'm2_yoy':(7.,'广义货币(M2)余额318.52万亿元，同比增长7%'),
  'm1_new_yoy':(.4,'狭义货币(M1)余额112.45万亿元，同比增长0.4%'),
  'new_rmb_loans':(51300.,'1月份人民币贷款增加5.13万亿元'),
  'rmb_loans_ytd_flow':(51300.,'1月份人民币贷款增加5.13万亿元')})]


def reviewed():
    requests={r['url']:r for p in (PUBLIC/'requests').glob('*.json') if (r:=read(p))['status']=='ok'}
    out=[]
    for url,date,period,date_literal,values in ENTRIES:
        rec=requests[url];assert sha(ROOT/rec['path'])==rec['sha256']
        raw=(ROOT/rec['path']).read_bytes().decode(rec['encoding'],errors='replace')
        tree=html.fromstring(raw)
        for node in tree.xpath('//script|//style'):node.drop_tree()
        text=re.sub(r'\s+','',tree.text_content())
        assert date_literal in raw or date_literal in text,(url,'publication date',date_literal)
        for sid,(value,literal) in values.items():
            assert literal in text,(url,literal)
            spec=next(s for s in specifications() if s['series_id']==sid)
            measure=spec['measure_type']
            fact=dated_fact(sid,value,period,date,rec,url,measure,spec['unit'],quality='conservative_release_reconstructed',
              note='Literal contemporary publication, national total and currency reviewed. Reprint becomes available at its own publication date, not an inferred earlier first release. January cumulative flow equals January flow. Loan amount converted from trillion CNY to 100 million CNY by x10000.')
            fact.update(source_name=urlparse(url).netloc,source_class='government_reprint' if 'gov.cn' in url else 'contemporary_press_record',
              extracted_text=literal,extraction_method='reviewed_literal_national_total_currency_period',
              publication_date_evidence=rec['path']+'#'+date_literal,revision_status='contemporary_report_no_complete_revision_archive')
            if spec['unit']=='亿元':
                for number,unit in re.findall(r'([\d.]+)(万亿元|亿元)',literal):
                    scale=10000 if unit=='万亿元' else 1
                    if abs(float(number)*scale-value)<1e-8:
                        fact['reported_quantum']=scale*10**(-len(number.split('.')[1]) if '.' in number else 0)
            out.append(fact)
    return out


def dr007_quotes():
    from .provider import API_RAW
    out=[]
    for p in sorted((API_RAW/'requests').glob('*.json')):
        rec=read(p)
        if rec['endpoint']!='repo_daily' or rec['status']!='ok' or rec['params'].get('ts_code')!='DR007.IB':continue
        assert sha(ROOT/rec['path'])==rec['sha256']
        obj=read(ROOT/rec['path']);d=pd.DataFrame(obj['items'],columns=obj['fields'])
        assert len(d)<2000 and not d.duplicated(['ts_code','trade_date']).any()
        assert d.ts_code.eq('DR007.IB').all() and d.repo_maturity.eq('DR007').all()
        for x in d.to_dict('records'):
            assert x['weight'] is not None and 0<float(x['weight'])<30
            date=pd.to_datetime(x['trade_date']);r=dated_fact('dr007',float(x['weight']),date,date,rec,'https://tushare.pro/document/2?doc_id=256','level','%',
                quality='latest_vintage_reconstructed',note='Historical DR007.IB weighted rate, not close, R007 or FDR007. All 30 overlapping retained CFETS dates agree exactly. No original correction log: actual availability remains retrieval; reconstructed end-of-day time is separate opt-in evidence policy.')
            r.update(source_name='TuShare DR007.IB historical quote',source_class='third_party_historical_quote',release_at=pd.NaT,
                period_start=date,frequency='D',
                research_available_at=pd.Timestamp(rec['retrieved_at']),reconstructed_quote_at=date.tz_localize('Asia/Shanghai')+pd.Timedelta(hours=23,minutes=59,seconds=59),
                extracted_text=json.dumps(x),publication_date_evidence='',release_time_basis='retrieval_only_no_original_quote_archive',
                vintage_id='repo-'+rec['sha256'][:20],reported_quantum=.0001,revision_status='historical_provider_snapshot_corrections_unobserved')
            out.append(r)
    return out


def safe_annual_reserves():
    from pypdf import PdfReader
    from urllib.parse import urljoin
    requests={r['url']:r for p in (PUBLIC/'requests').glob('*.json') if (r:=read(p))['status']=='ok'}
    out=[]
    for year,url,date in [(2014,'https://www.safe.gov.cn/safe/2015/0511/6128.html','2015-05-11'),
                          (2015,'https://www.safe.gov.cn/safe/2016/0513/6129.html','2016-05-13')]:
        page=requests[url];raw=(ROOT/page['path']).read_bytes().decode(page['encoding']);assert date in raw
        tree=html.fromstring(raw);links=[urljoin(url,a.get('href')) for a in tree.xpath('//a[@href]') if '.pdf' in a.get('href')];assert len(links)==1
        rec=requests[links[0]];assert sha(ROOT/rec['path'])==rec['sha256']
        matches=[(i,p.extract_text()) for i,p in enumerate(PdfReader(ROOT/rec['path']).pages) if f'表S11 {year}年1' in p.extract_text() and '月份' in p.extract_text()]
        assert len(matches)==1;page_number,txt=matches[0];assert '单位：亿美元' in txt
        values={}
        for a,b,c,d in re.findall(r'^\s*([1-6])\s+(\d{5})\s+(\d{1,2})\s+(\d{5})\s*$',txt,re.M):values[int(a)]=float(b);values[int(c)]=float(d)
        assert set(values)==set(range(1,13))
        for month,value in sorted(values.items()):
            end=pd.Timestamp(year,month,1)+pd.offsets.MonthEnd(0)
            r=dated_fact('fx_reserves',value,end,date,rec,url,'stock','亿美元','conservative_release_reconstructed',
               'Dated SAFE annual report table S11. Rounded to 1 hundred million USD. Available only at annual report publication, never backdated into the historical observation month.')
            r.update(source_name='SAFE dated annual report',source_class='official_dated_statistical_table',reported_quantum=1.,
                extracted_text=f'Table S11 month={month} reserves={value}',publication_date_evidence=page['path']+'#'+date,
                extraction_method='literal_pdf_text_table',revision_status='later_annual_compilation_not_first_release',evidence_page=page_number+1)
            out.append(r)
    for url,date in [('https://www.safe.gov.cn/dalian/2016/1209/259.html','2016-12-09'),('https://www.safe.gov.cn/safe/2017/0107/5843.html','2017-01-07')]:
        rec=requests[url];raw=(ROOT/rec['path']).read_bytes().decode(rec['encoding']);assert date in raw
        tree=html.fromstring(raw);cells=[[re.sub(r'\s+','',c.text_content()) for c in tr.xpath('./td|./th')] for tr in tree.xpath('//tr')]
        assert '亿美元' in tree.text_content();seen=[]
        for row in cells:
            if len(row)<2:continue
            m=re.fullmatch(r'(?:2016年)?(\d{1,2})(?:月)?',row[0])
            if not m:continue
            month=int(m[1]);value=float(row[1].replace(',',''));assert 1<=month<=12 and 30000<value<33000
            end=pd.Timestamp(2016,month,1)+pd.offsets.MonthEnd(0)
            r=dated_fact('fx_reserves',value,end,date,rec,url,'stock','亿美元','conservative_release_reconstructed',
                'SAFE dated historical reserves table; USD column (not SDR). Available at this later publication, not historical observation date.')
            r.update(source_name='SAFE dated historical reserves',source_class='official_dated_statistical_table',reported_quantum=.01,
                extracted_text=json.dumps(row,ensure_ascii=False),revision_status='dated_later_table_not_first_release')
            out.append(r);seen.append(month)
        assert len(seen)==(11 if 'dalian' in url else 12)
    return out


def january_identities(f):
    """An exact single-period identity; parent time/quality/vintage are preserved."""
    rows=[]
    for sid in ['exports_cny_yoy','imports_cny_yoy']:
        parents=f[f.series_id.eq(sid)&f.period_end.dt.month.eq(1)&f.certification_status.eq('ACCEPTED')]
        for row in parents.to_dict('records'):
            parent=row['source_record_id'];row['series_id']=sid.replace('_yoy','_ytd_yoy')
            row['concept_id']=row['series_id'];row['measure_type']='ytd_yoy'
            row['source_record_id']=identity(['v4_january_identity',parent,row['series_id']]);row['parent_record_ids']=json.dumps([parent])
            row['adjustment_note']=str(row['adjustment_note'])+'; exact January YTD = January monthly identity; not a new independent observation.'
            row['extraction_method']='january_identity_from_accepted_parent';rows.append(row)
    return pd.DataFrame(rows)
