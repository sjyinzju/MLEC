"""Dated secondary reports: literal monthly amounts, never forecasts or YTD subtraction."""
import re
from urllib.parse import urlparse
import pandas as pd
from lxml import html
from .common import ROOT,CONFIG,AUDIT,read_json,write_json


def credit_reprints():
    from .standardize import cached,dated_fact
    out=[];checks=[]
    for x in read_json(CONFIG/'credit_reprint_targets.json'):
        r=cached(x['url']);result={'url':x['url'],'period':x['period'],'status':'SOURCE_UNREACHABLE'}
        if not r:checks.append(result);continue
        tree=html.fromstring((ROOT/r['path']).read_bytes().decode(r['encoding'],errors='replace'))
        date=x.get('publication_date')
        pub=tree.xpath('//*[@id="pubtime_baidu"]/text()')
        if pub:date=pub[0].strip()[:10]
        meta=tree.xpath('//meta[@property="article:published_time" or @property="article:modified_time"]/@content')
        if meta:
            # UTC metadata sometimes differs from visible local dates; use the
            # later date, which cannot make the report available prematurely.
            timestamps=[pd.Timestamp(str(v)) for v in meta]
            dates=[(v.tz_convert('Asia/Shanghai') if v.tzinfo else v).strftime('%Y-%m-%d') for v in timestamps]
            date=max(dates+([date] if date else []))
        for node in tree.xpath('//script|//style|//nav'):node.drop_tree()
        full=re.sub(r'\s+','',tree.text_content())
        if not date or (date not in full and not pub and not meta and x.get('date_literal','<not specified>') not in full):
            result['status']='RELEASE_UNVERIFIED';checks.append(result);continue
        body=tree.xpath('//*[@id="Main_Content_Val"]')
        text=re.sub(r'\s+','',body[0].text_content()) if body else full
        # Caixin's public headline/summary is accessible without a subscription.
        # Do not decode hidden payloads or request paid article endpoints.
        if body:
            descriptions=tree.xpath('//meta[@property="og:description" or @name="description"]/@content')
            titles=tree.xpath('//meta[@property="og:title"]/@content') or tree.xpath('//title/text()')
            text=''.join(titles)+''.join(descriptions)+text
        end=pd.Timestamp(x['period']+'-01')+pd.offsets.MonthEnd(0);m=end.month
        if not 0<(pd.Timestamp(date)-end).days<75:
            result['status']='RELEASE_UNVERIFIED';checks.append(result);continue
        amount=r'(?P<sign>减少|负增长)?(?P<number>-?\d+(?:\.\d+)?)(?P<unit>万亿(?:元)?|亿(?:元)?)'
        patterns={
          'new_rmb_loans':rf'(?<![\d—－–-]){m}月份?[，,]?(?:金融机构)?(?:新增)?人民币(?:贷款|信贷)(?:增加|新增|为|仅)?'+amount,
          'tsf_month_flow':rf'(?<![\d—－–-]){m}月份?[，,]?(?:新增)?(?:社会融资规模|社融)(?:规模)?(?:增量|新增规模|新增|增加)?(?:为|约)?'+amount}
        for sid,pat in patterns.items():
            override=x.get('patterns',{}).get(sid)
            matches=list(re.finditer((override if override else pat),text))
            if not matches and not override:
                prefix=rf'从{m}月(?:的)?单月情况(?:来看|看)[，,]'
                if sid=='new_rmb_loans':pat=prefix+r'人民币贷款(?:新增|增加)?'+amount
                else:pat=prefix+r'[^。]{0,70}[；;](?:当月)?社会融资规模增量为'+amount
                matches=list(re.finditer(pat,text))
            if not matches:continue
            # Forecast sentences and explicitly approximate cumulative
            # differences are not admissible observations.
            for match in matches:
                prefix=text[max(0,match.start()-40):match.start()]
                if re.search(r'预计|预测|测算|累计数据计算|公布的数据计算',prefix):continue
                v=round(float(match['number'])*(10000 if match['unit'].startswith('万') else 1),8)
                if match['sign']:v=-abs(v)
                row=dated_fact(sid,v,end,date,r,x['url'],'flow','亿元','conservative_release_reconstructed',
                    'Literal monthly amount in a dated contemporaneous report; reported precision retained. This is secondary evidence, not a certified original PBOC release. No cumulative subtraction, forecasts, or future backdating.')
                row.update(source_name=urlparse(x['url']).netloc+' contemporaneous report',value_quality='dated_secondary_reported_amount',
                    extracted_text=match[0],publication_date_evidence=r['path']+'#'+date,
                    reported_quantum=(10**(-len(match['number'].split('.')[1])) if '.' in match['number'] else 1)*(10000 if match['unit'].startswith('万') else 1))
                out.append(row);result.setdefault('extracted',[]).append({'series_id':sid,'value':v,'text':match[0],'available_date':date})
                break
        result['status']='ACCEPTED' if result.get('extracted') else 'PARSING_FAILED'
        checks.append(result)
    write_json(AUDIT/'credit_reprint_extractions.json',checks)
    return out
