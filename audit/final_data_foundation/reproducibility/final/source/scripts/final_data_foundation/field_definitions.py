"""Read retained public provider contracts, never infer units from magnitudes."""
import re
from lxml import html
from .collect import *
from .contracts import DOC_IDS


def build():
    rows=[]
    for ep,num in DOC_IDS.items():
        p,r=fetch('https://tushare.pro/document/2',{'doc_id':num})
        if p is None:raise ValueError('Missing provider definition '+ep)
        tree=html.fromstring(p.read_bytes().decode(r['encoding']))
        tables=[]
        for table in tree.xpath('//table'):
            rr=[[re.sub(r'\s+',' ',cell.text_content()).strip() for cell in tr.xpath('./td|./th')] for tr in table.xpath('.//tr')]
            if rr and rr[0][:2]==['名称','类型'] and '描述' in rr[0]:tables.append(rr)
        assert len(tables)==2,(ep,len(tables))
        for v in tables[1][1:]:
            rows.append(dict(endpoint=ep,field=v[0],type=v[1],source_description=v[-1],source_url=r['final_url'],source_path=r['path'],sha256=r['sha256']))
    write(PUBLIC/'provider_field_definitions.json',rows)
    print('Provider field definitions',len(rows),flush=True)


if __name__=='__main__':build()
