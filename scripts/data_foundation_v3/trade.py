"""Dated ministry trade bulletins; never infer first release from the month."""
import re
import struct
import olefile
import pandas as pd
from lxml import html
from .common import ROOT,RAW,AUDIT,read_json,write_json,digest
from .standardize import cached,dated_fact


def doc_text(path):
    """Read Word 97+ CLX text pieces; no Office process or embedded code runs.

    MS-DOC 2.4.1: https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/01d5d8c4-cf9c-4ef9-80fd-439e763cfe01
    Only Unicode and ASCII pieces are accepted for these Chinese tables.
    """
    with olefile.OleFileIO(path) as ole:
        b=ole.openstream('WordDocument').read()
        if struct.unpack_from('<H',b)[0]!=0xA5EC:raise ValueError('Not Word binary format')
        flags=struct.unpack_from('<H',b,10)[0]
        if flags&0x100:raise ValueError('Encrypted document not supported')
        table=ole.openstream('1Table' if flags&0x200 else '0Table').read()
        off,size=struct.unpack_from('<II',b,418);clx=table[off:off+size];i=0
        while i<len(clx) and clx[i]==1:i+=3+struct.unpack_from('<H',clx,i+1)[0]
        if i>=len(clx) or clx[i]!=2:raise ValueError('Missing text piece table')
        length=struct.unpack_from('<I',clx,i+1)[0];p=clx[i+5:i+5+length]
        if len(p)!=length or (length-4)%12:raise ValueError('Invalid piece table length')
        n=(length-4)//12;cp=struct.unpack_from('<'+'I'*(n+1),p)
        if list(cp)!=sorted(cp):raise ValueError('Nonmonotonic character positions')
        text=[]
        for j in range(n):
            fc=struct.unpack_from('<I',p,4*(n+1)+8*j+2)[0];compressed=bool(fc&0x40000000)
            pos=fc&0x3fffffff;pos=pos//2 if compressed else pos;count=(cp[j+1]-cp[j])*(1 if compressed else 2)
            raw=b[pos:pos+count]
            if len(raw)!=count:raise ValueError('Truncated text piece')
            text.append(raw.decode('ascii' if compressed else 'utf-16le'))
        return ''.join(text)


def reviewed_images():
    """Replay visually checked cells bound to immutable original image hashes."""
    path=RAW/'mofcom_image_transcriptions.json';out=[]
    if not path.exists():return out
    entries=read_json(path)['entries'];seen={}
    for item in entries:
        rec=item['image'];page=cached(item['page_url'])
        if digest(ROOT/rec['path'])!=rec['sha256']:raise ValueError('Changed reviewed trade image')
        if not page or digest(ROOT/page['path'])!=page['sha256']:raise ValueError('Changed trade date evidence')
        content=html.fromstring((ROOT/page['path']).read_bytes().decode(page['encoding'],errors='replace')).text_content()
        if item['page_date'] not in content:raise ValueError('Unverified image publication date')
        match=re.search(r'(20\d\d)年(\d{1,2})月进出口',item['title'])
        if not match:raise ValueError('Missing reviewed image period')
        end=pd.Timestamp(int(match[1]),int(match[2]),1)+pd.offsets.MonthEnd(0)
        previous=item.get('corroborates_image_sha256')
        if previous:
            if seen.get(previous)!=item['values']:raise ValueError('Trade table and narrative disagree')
            continue
        seen[rec['sha256']]=item['values']
        for sid,value in item['values'].items():
            if value is None:continue
            scope='ytd_yoy' if '_ytd_' in sid else 'yoy'
            row=dated_fact(sid,value,end,item['page_date'],rec,rec['url'],scope,'%','conservative_release_reconstructed',
                'Visually checked original MOFCOM image; currency, sign, monthly/YTD heading and export/import row checked. Displayed republication date retained. January monthly and YTD refer to the identical one-month interval.')
            row.update(source_name='MOFCOM visually checked trade bulletin',source_class='dated_official_republication',publication_date_evidence=page['path'],
                extraction_method='assistant_visual_review',extraction_evidence=str(path.relative_to(ROOT)).replace('\\','/'),
                extracted_text=f"{item['title']} | {sid} | {value}%",reported_quantum=0.1)
            file_date=re.search(r'/(20\d{6})\d*\.(?:jpg|jpeg|png)$',rec['url'],re.I)
            if file_date and pd.Timestamp(file_date[1])>pd.Timestamp(item['page_date']):
                row.update(quality_status='latest_vintage_reconstructed',research_available_at=pd.Timestamp(rec['retrieved_at']),release_at=pd.NaT,
                    release_time_basis='attachment_later_than_page; retrieval_only',time_quality='historical_release_unverified',vintage_quality='attachment_version_unverified',
                    revision_status='observed_only',source_class='historical_candidate_archive',adjustment_note=row['adjustment_note']+' Attachment filename is later than page date; no historical availability certification.')
            out.append(row)
    return out


def historical_trade():
    listing=RAW/'mofcom_history_titles.json';out=reviewed_images();audit=[]
    if not listing.exists():return out
    for item in read_json(listing):
        match=re.search(r'(20\d\d)年(\d{1,2})月进出口',item['title'])
        if not match or int(match[1])<2014:continue
        end=pd.Timestamp(int(match[1]),int(match[2]),1)+pd.offsets.MonthEnd(0)
        page=cached(item['url']);count=sum(r['source_url'] in {a['url'] for a in item['attachments']} for r in out);errors=[]
        if not page:continue
        t=html.fromstring((ROOT/page['path']).read_bytes().decode(page['encoding'],errors='replace'))
        # Displayed date and directory must agree. The 2021 repost date is kept.
        if item['date'] not in t.text_content():
            audit.append({**item,'status':'RELEASE_UNVERIFIED'});continue
        for rec in item['attachments']:
            if rec.get('status')!='ok' or not rec['url'].lower().endswith('.doc'):continue
            path=ROOT/rec['path']
            if digest(path)!=rec['sha256']:raise ValueError('Changed ministry attachment')
            try:text=doc_text(path)
            except (ValueError,UnicodeError,struct.error,OSError) as exc:
                errors.append(str(exc));continue
            compact=re.sub(r'\s+','',text)
            if f'{end.year}年{end.month}月进出口' not in compact:errors.append('Attachment period mismatch');continue
            for currency,unit in [('美元','亿美元'),('人民币','亿元')]:
                parts=re.split(r'进出口概况[（(]'+currency+r'[）)]',compact)
                if len(parts)!=2:continue
                section=re.split(r'进出口概况[（(]',parts[1])[0]
                monthly=re.search(r'(?<![\d—-])'+str(end.month)+r'月当月[，,](.*?)(?:项目|\x07)',section)
                ytd=section.split(f'{end.month}月当月')[0]
                for side,english in [('出口','exports'),('进口','imports')]:
                    for scope,segment in [('monthly',monthly[1] if monthly else ''),('ytd',ytd)]:
                        if currency=='美元' and scope=='ytd':continue
                        m=re.search(r'(?<!进)'+side+r'[\d.]+(?:'+unit+r')[，,](?:同比)?(增长|下降)([\d.]+)%',segment)
                        if not m:continue
                        value=float(m[2])*(-1 if m[1]=='下降' else 1)
                        sid=english+('_yoy' if currency=='美元' else '_cny_yoy' if scope=='monthly' else '_cny_ytd_yoy')
                        row=dated_fact(sid,value,end,item['date'],rec,rec['url'],'ytd_yoy' if scope=='ytd' else 'yoy','%','conservative_release_reconstructed',
                            'MOFCOM dated GAC bulletin attachment. Uses displayed ministry publication date, including delayed reposts; never assumes first GAC release. Currency and monthly/YTD paragraph matched literally.')
                        row.update(source_name='MOFCOM dated trade bulletin',source_class='dated_official_republication',publication_date_evidence=page['path'],extracted_text=m[0],reported_quantum=0.1)
                        file_date=re.search(r'/(20\d{6})\d*\.doc$',rec['url'])
                        if file_date and pd.Timestamp(file_date[1])>pd.Timestamp(item['date']):
                            # Evidence of a later attachment replacement prevents
                            # attributing today's file to the older page timestamp.
                            row.update(quality_status='latest_vintage_reconstructed',research_available_at=pd.Timestamp(rec['retrieved_at']),release_at=pd.NaT,
                                release_time_basis='attachment_later_than_page; retrieval_only',time_quality='historical_release_unverified',vintage_quality='attachment_version_unverified',
                                revision_status='observed_only',source_class='historical_candidate_archive',adjustment_note=row['adjustment_note']+' Attachment filename is later than page date; not certified for that historical publication.')
                        out.append(row);count+=1
        audit.append({'title':item['title'],'url':item['url'],'date':item['date'],'records':count,'status':'ACCEPTED' if count else 'PARSING_FAILED','details':errors or (['Image-only or unsupported attachment; not auto-certified by OCR'] if not count else [])})
    write_json(AUDIT/'mofcom_extractions.json',audit)
    return out
