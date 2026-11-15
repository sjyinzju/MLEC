"""Targeted public issuer announcements for every unresolved trading interval."""
import re
from concurrent.futures import ThreadPoolExecutor
from pypdf import PdfReader
from .common import *
from .collect import fetch,PUBLIC

def collect_gap_announcements():
    gaps=pd.read_parquet(AUDIT/'missing_records/stock_gap_summary.parquet')
    gaps=gaps[gaps.status.str.contains('MISSING')].groupby('ts_code').agg(period_start=('period_start','min'),period_end=('period_end','max')).reset_index()
    jobs=[]
    for r in gaps.itertuples(index=False):
        for boundary,day in [('start',r.period_start),('end',r.period_end)]:
            day=pd.Timestamp(day)
            jobs.append((r.ts_code,boundary,(day-pd.Timedelta(days=40)).strftime('%Y-%m-%d'),(day+pd.Timedelta(days=40)).strftime('%Y-%m-%d')))
    def listing(job):
        code,boundary,start,end=job
        params={'sr':-1,'page_size':50,'page_index':1,'ann_type':'A','client_source':'web','stock_list':code[:6],'f_node':0,'s_node':0,'begin_time':start,'end_time':end}
        p,meta=fetch('https://np-anotice-stock.eastmoney.com/api/security/ann',params)
        out=[]
        if p is None:return out
        obj=read(p);total=obj.get('data',{}).get('total_hits',0)
        for page in range(1,(total+49)//50+1):
            if page>1:p,meta=fetch('https://np-anotice-stock.eastmoney.com/api/security/ann',{**params,'page_index':page});obj=read(p) if p else {}
            for x in obj.get('data',{}).get('list',[]):
                if any(s in x['title'] for s in ['暂停上市','恢复上市','恢复股票上市','终止上市','退市整理','复牌','停牌']) and not any(s in x['title'] for s in ['风险提示','可能被','可能终止','可能暂停']):
                    out.append({**x,'instrument_id':code,'boundary':boundary,'directory_evidence':meta.get('path')})
        return out
    with ThreadPoolExecutor(3) as pool:rows=[r for batch in pool.map(listing,jobs) for r in batch]
    rows=list({r['art_code']:r for r in rows}.values())
    write(PUBLIC/'issuer_gap_titles.json',rows)
    def document(row):
        url='https://pdf.dfcfw.com/pdf/H2_'+row['art_code']+'_1.pdf'
        p,r=fetch(url)
        if p:
            try:
                text='\n'.join(page.extract_text() or '' for page in PdfReader(p).pages)
                tp=p.with_suffix('.txt')
                if not tp.exists():tp.write_text(text,encoding='utf-8')
                return {**row,'pdf_evidence':r['path'],'pdf_sha256':r['sha256'],'text_evidence':tp.relative_to(ROOT).as_posix(),'status':'DOWNLOADED_NOT_YET_VERIFIED'}
            except Exception as exc:return {**row,'status':'PARSE_FAILED','error':type(exc).__name__}
        return {**row,'status':'DOWNLOAD_FAILED'}
    with ThreadPoolExecutor(3) as pool:documents=list(pool.map(document,rows))
    write(PUBLIC/'issuer_gap_documents.json',documents)
    print('issuer evidence',len(gaps),'securities',len(documents),'documents',flush=True)

def collect_text_reproductions():
    """Public, unabridged announcement text; not an authenticated issuer PDF."""
    rows=read(PUBLIC/'issuer_gap_titles.json')
    def document(row):
        p,r=fetch('https://np-cnotice-stock.eastmoney.com/api/content/ann',
                  {'art_code':row['art_code'],'client_source':'web','page_index':1})
        if p is None:return {**row,'status':'CONTENT_DOWNLOAD_FAILED'}
        data=read(p).get('data',{})
        content=data.get('notice_content','')
        return {**row,'content_evidence':r['path'],'content_sha256':r['sha256'],
                'content':content,'retrieved_at':r['retrieved_at'],
                'original_pdf_url':data.get('attach_url_web'),
                'status':'REPRODUCTION_REQUIRES_REVIEW' if content else 'EMPTY_CONTENT'}
    with ThreadPoolExecutor(3) as pool:documents=list(pool.map(document,rows))
    write(PUBLIC/'issuer_gap_reproductions.json',documents)
    print('announcement texts',pd.DataFrame(documents).status.value_counts().to_dict(),flush=True)

def collect_cninfo():
    """Bounded primary-document search for each missing-quote boundary."""
    import time
    gaps=pd.read_parquet(AUDIT/'missing_records/stock_gap_summary.parquet')
    gaps=gaps[gaps.status.str.contains('MISSING')].groupby('ts_code').agg(period_start=('period_start','min'),period_end=('period_end','max')).reset_index()
    ledger=PUBLIC/'issuer_cninfo_documents.json'
    found=read(ledger) if ledger.exists() else []
    seen={x['announcementId'] for x in found}
    failures=0
    titles=read(PUBLIC/'issuer_gap_titles.json')
    for x in gaps.itertuples(index=False):
        for boundary,day in [('start',x.period_start),('end',x.period_end)]:
            day=pd.Timestamp(day)
            names=[]
            for a in sorted(titles,key=lambda a:a.get('boundary')!=boundary):
                if a['instrument_id']!=x.ts_code or ':' not in a['title']:continue
                parts=a['title'].split(':');name=parts[1] if parts[0].isdigit() else parts[0]
                name=re.split(r'关于|股票|:',name)[0]
                name=re.sub(r'^[SN]?\*?ST','',name)
                if name.strip() and not name.isdigit():names.append(name)
            search_name=names[0] if names else x.ts_code[:6]
            if not search_name.strip():raise ValueError('Empty issuer search forbidden')
            params={'pageNum':1,'pageSize':30,'column':'sse' if x.ts_code.endswith('SH') else 'szse',
              'tabName':'fulltext','stock':'','searchkey':search_name, 'secid':'','plate':'','category':'','trade':'',
              'seDate':(day-pd.Timedelta(days=40)).strftime('%Y-%m-%d')+'~'+(day+pd.Timedelta(days=40)).strftime('%Y-%m-%d'),
              'sortName':'','sortType':'','isHLtitle':'false'}
            p,r=fetch('https://www.cninfo.com.cn/new/hisAnnouncement/query',params,'POST')
            if p is None:
                failures+=1
                if failures>=3:raise RuntimeError('CNINFO unavailable; stop repeated requests')
                continue
            failures=0;obj=read(p);rows=obj.get('announcements') or [];directory_evidence=r['path']
            if obj.get('totalpages',0)>20:
                write(PUBLIC/'issuer_query_requires_narrowing'/f'{x.ts_code}_{boundary}.json',{'params':params,'pages':obj['totalpages'],'source':r})
                continue
            for page in range(2,obj.get('totalpages',0)+1):
                p,r=fetch('https://www.cninfo.com.cn/new/hisAnnouncement/query',{**params,'pageNum':page},'POST')
                if p:rows+=read(p).get('announcements') or []
                time.sleep(.3)
            candidates=[a for a in rows if any(s in a['announcementTitle'] for s in ['暂停上市','恢复上市','恢复股票上市','退市整理','复牌','停牌'])
              and not any(s in a['announcementTitle'] for s in ['可能','核查','法律意见','风险提示','进展','保荐','补充材料','前十名','申请恢复'])]
            candidates=sorted(candidates,key=lambda a:('公告书' in a['announcementTitle'],a.get('adjunctSize',0)))[:5]
            for a in candidates:
                if a['announcementId'] in seen:continue
                url='https://static.cninfo.com.cn/'+a['adjunctUrl'];p,r=fetch(url)
                item={**a,'instrument_id':x.ts_code,'boundary':boundary,'url':url,'directory_evidence':directory_evidence,
                      'release_date':pd.Timestamp(a['announcementTime'],unit='ms',tz='UTC').tz_convert('Asia/Shanghai').strftime('%Y-%m-%d')}
                if p and p.read_bytes().startswith(b'%PDF'):
                    try:
                        content='\n'.join(page.extract_text() or '' for page in PdfReader(p).pages)
                        # CNINFO can re-key a delisted issuer's old announcements
                        # to its later OTC code. The original PDF identity wins.
                        if not re.search(r'(?:证券|股票)代码[:：]?'+re.escape(x.ts_code[:6]),re.sub(r'\s+','',content)):
                            continue
                        item.update(content=content,evidence_path=r['path'],sha256=r['sha256'],retrieved_at=r['retrieved_at'],status='PRIMARY_REQUIRES_REVIEW')
                    except Exception as exc:item.update(status='PDF_PARSE_FAILED',error=type(exc).__name__)
                else:item['status']='PDF_DOWNLOAD_FAILED'
                found.append(item);seen.add(a['announcementId']);time.sleep(.25)
            write(ledger,found)
        print('CNINFO',x.ts_code,len(found),flush=True)
    return found

if __name__=='__main__':collect_gap_announcements()


def collect_targeted_boundaries():
    """Search across board reclassifications; verify identity in the original PDF."""
    targets=[
        ('000520.SZ','凤凰','2015-08-01','2015-08-20'),
        ('000693.SZ','华泽','2018-07-01','2018-07-20'),
        ('000760.SZ','斯太尔','2021-05-01','2021-06-15'),
        ('002260.SZ','德奥','2022-04-01','2022-05-10'),
        ('300104.SZ','乐视网','2019-05-01','2019-05-20'),
        ('300104.SZ','乐视网','2020-05-01','2020-06-10'),
        ('300216.SZ','千山','2020-07-01','2020-08-10'),
        ('300362.SZ','天翔','2021-06-01','2021-07-25'),
        ('300372.SZ','欣泰','2017-06-01','2017-07-20'),
        ('300431.SZ','暴风','2020-09-01','2020-09-25'),
        ('600087.SH','长油','2014-03-01','2014-04-25'),
        ('600385.SH','金泰','2014-07-01','2014-08-10'),
        ('600485.SH','信威','2021-05-01','2021-06-05'),
        ('600610.SH','毅达','2020-07-01','2020-08-20'),
        ('600656.SH','博元','2016-03-01','2016-03-31'),
        ('600677.SH','航天通信','2021-02-01','2021-03-20'),
        ('600680.SH','上海普天','2019-04-01','2019-05-30'),
        ('600806.SH','昆明机床','2018-05-01','2018-06-01'),
        ('601268.SH','二重','2014-05-01','2014-06-01'),
        ('601268.SH','二重','2015-04-01','2015-05-25'),
        ('688766.SH','普冉','2025-12-01','2025-12-10')]
    ledger=PUBLIC/'issuer_cninfo_documents.json';found=read(ledger);seen={x['announcementId'] for x in found}
    for code,name,start,end in targets:
        params={'pageNum':1,'pageSize':30,'column':'','tabName':'fulltext','stock':'','searchkey':name,
                'secid':'','plate':'','category':'','trade':'','seDate':start+'~'+end,'sortName':'','sortType':'','isHLtitle':'false'}
        p,r=fetch('https://www.cninfo.com.cn/new/hisAnnouncement/query',params,'POST')
        if not p:continue
        obj=read(p);rows=obj.get('announcements') or [];directory=r['path']
        if obj.get('totalpages',0)>6:raise ValueError('Targeted issuer query too broad: '+name)
        for page in range(2,obj.get('totalpages',0)+1):
            p,r=fetch('https://www.cninfo.com.cn/new/hisAnnouncement/query',{**params,'pageNum':page},'POST')
            if p:rows+=read(p).get('announcements') or []
        for a in rows:
            title=a['announcementTitle']
            if a['announcementId'] in seen or '已取消' in title:continue
            if not any(s in title for s in ['恢复上市','恢复股票上市','退市整理期交易','暂停上市公告','暂停上市的公告','终止上市','复牌','摘牌']):continue
            if any(s in title for s in ['风险提示','可能','法律意见','保荐','审计','进展']):continue
            p,r=fetch('https://static.cninfo.com.cn/'+a['adjunctUrl'])
            if not p or not p.read_bytes().startswith(b'%PDF'):continue
            content='\n'.join(page.extract_text() or '' for page in PdfReader(p).pages)
            if code[:6] not in re.sub(r'\s+','',content):continue
            found.append({**a,'instrument_id':code,'boundary':'targeted','url':r['url'],'directory_evidence':directory,
                'release_date':pd.Timestamp(a['announcementTime'],unit='ms',tz='UTC').tz_convert('Asia/Shanghai').strftime('%Y-%m-%d'),
                'content':content,'evidence_path':r['path'],'sha256':r['sha256'],'retrieved_at':r['retrieved_at'],'status':'PRIMARY_REQUIRES_REVIEW'})
            seen.add(a['announcementId'])
        write(ledger,found);print('targeted',code,len(found),flush=True)
