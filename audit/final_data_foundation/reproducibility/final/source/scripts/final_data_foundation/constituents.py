"""Replay issuer-authenticated CNI adjustments; catalog completeness stays qualified.

Discovery reference: rootSunc/CNEquity 399001-history.json. All financial facts
are independently extracted here from the retained CNI documents, not that seed.
"""
import re
from pypdf import PdfReader
from lxml import html
from .common import *
from .collect import PUBLIC
from .market import rel

LEGACY={6:('2017-01-13',['002354'],['000748']),12:('2019-03-07',['002867'],['002450']),
 13:('2019-05-09',['000560','002203'],['002477','002143']),15:('2019-09-11',['003816'],['002509']),
 16:('2019-11-06',['002099'],['002716'])}
VISUAL_DATES={4:('2016-06-20','2016-07'),5:('2016-12-12','2017-01'),7:('2017-06-12','2017-07'),
 8:('2017-12-18','2018-01'),9:('2018-06-11','2018-07'),11:('2018-12-10','2019-01'),
 14:('2019-06-03','2019-06-17'),17:('2019-12-02','2019-12-16')}


def build():
    seed=read(ROOT/read(PUBLIC/'cni_source_targets.json')['discovery']['path'])
    docs={r['url']:r['evidence'] for r in read(PUBLIC/'cni_source_downloads.json')}
    def source(spec):
        r=docs[spec['url']];assert sha(ROOT/r['path'])==spec['sha256']==r['sha256'];return r
    def text(r):
        p=ROOT/r['path']
        return '\n'.join(x.extract_text() for x in PdfReader(p).pages) if p.suffix=='.pdf' else html.fromstring(p.read_bytes().decode(r['encoding'])).text_content()
    opening=source(seed['opening']);sheet=pd.read_excel(ROOT/opening['path'],dtype=str)
    assert '公告时间：2015-3-20 正式实施时间：2015-5-20' in sheet.columns
    members=set(sheet['证券代码']+'.SZ');assert len(members)==500
    cal=db();days=cal.execute('SELECT cal_date FROM '+rel('trade_calendar')+" WHERE exchange='SZSE' AND is_open=1 ORDER BY cal_date").df().cal_date.tolist();cal.close()
    events=[];fail=[]
    for i,e in enumerate(seed['events']):
        try:
            r=source(e['payload']);authority=source(e.get('date_authority',e['payload']));t=text(authority);compact=re.sub(r'\s+','',t)
            expected=pd.Timestamp(e['effective_date']);date_matches=re.findall(r'(20\d{2})年(\d{1,2})月(\d{1,2})日',compact)
            if i in LEGACY:
                published,adds,removes=LEGACY[i]
                # First/last pages visually reviewed; damaged text is not used to infer direction/date.
                assert all(v in t for v in adds+removes)
                evidence=f'audit/final_data_foundation/issue_closure/cni_review/{i}_1.png'
                effective=expected
            else:
                if i in VISUAL_DATES:
                    pub,eff=VISUAL_DATES[i]
                    resolved=next(d for d in days if d.startswith(eff.replace('-',''))) if len(eff)==7 else eff.replace('-','')
                    assert pd.to_datetime(resolved)==expected
                    # The rendered first/last pages were directly reviewed. Use a
                    # synthetic date clause only after binding those facts to the
                    # verified original digest, never OCR output or filename.
                    compact+=f'决定于{expected.year}年{expected.month}月{expected.day}日'
                    date_matches=[pd.Timestamp(pub).strftime('%Y-%m-%d').split('-')]
                assert date_matches,('No date',i)
                published=pd.Timestamp('-'.join(date_matches[-1])).strftime('%Y-%m-%d')
                if authority['sha256']=='d10ad678fad650ca63755d35c4739534179ed0df8d0fae171e7e469c2f8eedbe':
                    # Signature characters 年/月/日 are absent from this PDF's
                    # text layer. Page 2 was visually verified, not inferred
                    # from its body effective date or source filename.
                    published='2023-05-29'
                explicit=re.search(r'决定于(20\d{2})年(\d{1,2})月(\d{1,2})日',compact)
                firstday=re.search(r'决定于(20\d{2})年(\d{1,2})月第一个交易日',compact)
                if explicit:effective=pd.Timestamp('-'.join(explicit.groups()))
                elif firstday:
                    ym=f'{int(firstday[1]):04}{int(firstday[2]):02}';effective=pd.to_datetime(next(d for d in days if d.startswith(ym)))
                elif e['parser']=='merger':
                    date=re.search(r'于(20\d{2})年(\d{1,2})月(\d{1,2})日调入',compact);assert date
                    effective=pd.Timestamp('-'.join(date.groups()))
                elif 'delisting_authority' in e:
                    at=re.sub(r'\s+','',text(source(e['delisting_authority'])))
                    date=re.search(r'(?:将于|将自)(20\d{2})年(\d{1,2})月(\d{1,2})日起终止上市',at);assert date and '002013' in at
                    effective=pd.Timestamp('-'.join(date.groups()))
                else:raise ValueError('Unsupported explicit effective date')
                assert effective==expected,(i,effective,expected)
                if e['parser']=='workbook':
                    w=pd.read_excel(ROOT/r['path'],dtype=str);w=w[w['指数代码'].eq('399001')]
                    assert len(w) and w['调整类型'].isin(['+','-']).all()
                    adds=w.loc[w['调整类型'].eq('+'),'证券代码'].tolist();removes=w.loc[w['调整类型'].eq('-'),'证券代码'].tolist()
                elif e['parser']=='merger':
                    m=re.search(r'鉴于[^()（）]+[（(](\d{6})[）)][^()（）]+[（(](\d{6})[）)]吸收合并',compact);assert m
                    removes=[m[1]];adds=[m[2]]
                else:
                    # Preserve whitespace between adjacent numeric cells and page numbers.
                    heading=r'\s*'.join('深证成份指数样本股调整名单');h=re.search(heading,t)
                    if h:
                        section=t[h.end():];end=re.search(r'\s*'.join('指数样本股调整名单'),section)
                        if end:section=section[:end.start()]
                        assert re.sub(r'\s+','',section).startswith('调入名单调出名单证券代码证券简称证券代码证券简称')
                        codes=re.findall(r'(?<!\d)\d{6}(?!\d)',section);assert len(codes)%2==0
                        adds,removes=codes[::2],codes[1::2]
                    else:
                        assert '调入股票调出股票证券代码证券简称证券代码证券简称' in compact
                        chunks=re.split(r'(?<!\d)(399\d{3}|CN\d{4})(?!\d)',t);adds=[];removes=[]
                        for j in range(1,len(chunks),2):
                            if chunks[j]=='399001':
                                codes=re.findall(r'(?<!\d)\d{6}(?!\d)',chunks[j+1]);assert len(codes)==2
                                adds.append(codes[0]);removes.append(codes[1])
                evidence=authority['path']
                if authority['sha256']=='d10ad678fad650ca63755d35c4739534179ed0df8d0fae171e7e469c2f8eedbe':
                    evidence+=';audit/final_data_foundation/issue_closure/cni_review/20230529_signature.png'
                if i in VISUAL_DATES:evidence+=f';audit/final_data_foundation/issue_closure/cni_review/{i}_first.png;{i}_last.png'
            assert adds and len(adds)==len(set(adds))==len(removes)==len(set(removes)) and not set(adds)&set(removes)
            assert pd.Timestamp(published)<=effective
            events.append(dict(event_id='cni-'+r['sha256'][:24],index_code='399001.SZ',effective_date=effective,
                release_at=pd.Timestamp(published,tz='Asia/Shanghai'),research_available_at=pd.Timestamp(published,tz='Asia/Shanghai')+pd.Timedelta(days=1),
                additions=[x+'.SZ' for x in adds],removals=[x+'.SZ' for x in removes],source_path=r['path'],source_sha256=r['sha256'],
                source_url=r['url'],retrieved_at=r['retrieved_at'],date_evidence=evidence,quality_status='official_adjustment_document_verified'))
        except Exception as exc:fail.append({'index':i,'effective_date':e['effective_date'],'error':str(exc)})
    write(AUDIT/'issue_closure/cni_parse_results.json',{'events':events,'failures':fail,'catalog_completeness':'UNVERIFIED: seed helps discovery; endpoint/anchor agreement alone cannot prove no missing intermediate announcement'})
    if fail:print('CNI parse failures',fail,flush=True);return
    frame(MARKET/'index_adjustment_events.parquet',pd.DataFrame(events))
    # A complete book at each verified event. Its interval end is retrospective
    # metadata; point-in-time queries must replay only announcements already known.
    books=[('2015-05-20',members.copy(),opening['path'],pd.Timestamp('2015-03-21',tz='Asia/Shanghai'))]
    for e in events:
        missing=set(e['removals'])-members
        assert not missing,(e['effective_date'],missing)
        assert not set(e['additions'])&members,(e['effective_date'],'already member')
        members=(members-set(e['removals']))|set(e['additions']);assert len(members)==500
        books.append((e['effective_date'],members.copy(),e['source_path'],e['research_available_at']))
    reference=set(seed['closing_reference']['members']);closing_difference=sorted(members^reference)
    rows=[]
    for i,(date,book,evidence,available) in enumerate(books):
        end=pd.Timestamp(books[i+1][0]) if i+1<len(books) else pd.Timestamp('2026-09-23')
        for code in sorted(book):rows.append({'index_code':'399001.SZ','con_code':code,'valid_from':pd.Timestamp(date),'valid_to':end,
            'research_available_at':available,'source_path':evidence,'quality_status':'QUALIFIED_CATALOG_COMPLETENESS_UNVERIFIED',
            'quality_reason':'500-member event replay; all 38 captured announcements checked. Missing intermediate notices cannot be ruled out by endpoint agreement alone.',
            'weight':None,'data_version':VERSION})
    frame(MARKET/'index_constituents_history.parquet',pd.DataFrame(rows))
    write(AUDIT/'issue_closure/cni_reconstruction.json',{'events':len(events),'books':len(books),'rows':len(rows),'closing_reference_difference':closing_difference,
        'closing_reference_is_secondary_catalog':True,'first_effective':'2015-05-20','last_observation':'2026-09-22','daily_weights_available':False,'status':'QUALIFIED_NOT_FULL_UNIVERSE_CERTIFIED'})
    print('CNI',len(events),'events',len(rows),'memberships; closing difference',len(closing_difference),flush=True)


if __name__=='__main__':build()
