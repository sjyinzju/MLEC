"""Additional primary-evidenced historical code, no price or label changes."""
import re
from .common import *
from .collect import PUBLIC


def register():
    review=read(PUBLIC/'identity_601313_601360_review.json');r=review['source']
    assert sha(ROOT/r['path'])==r['sha256']
    text=re.sub(r'\s+','',review['matching_pages'][0]['text'])
    assert '股票代码601313' in text and '2018年2月28日起变更为601360' in text
    path=PUBLIC/'code_change_evidence.json';rows=read(path)
    record={'old_code':'601313.SH','new_code':'601360.SH','effective_date':'2018-02-28','publication_date':'2018-02-28',
      'url':r['url'],'source_path':r['path'],'source_sha256':r['sha256'],'retrieved_at':r['retrieved_at'],
      'text_path':'data/raw/public_sources/v4/identity_601313_601360_review.json',
      'mapping_kind':'same legal listed entity after asset restructuring; share-class/corporate-action changes remain separately audited',
      'review_status':'PRIMARY_DOCUMENT_VERIFIED','source_page':6}
    rows=[x for x in rows if x['old_code']!=record['old_code']]+[record];write(path,rows)
    write(AUDIT/'issue_closure/identity_601313_601360.json',{'status':'SOURCE_VERIFIED_REBUILD_PENDING','source':record,
      'root_cause':'Provider backfills the current 601360 identifier before its actual 2018-02-28 effective date; raw records contain no 601313 observations.',
      'repair':'Rebuild identity intervals, trading status and canonical observations; retain original provider code and values.'})


def verify():
    from .market import rel
    c=db();results=[]
    for table in ['stock_daily','stock_daily_basic','stock_adjustment']:
        q=rel(table+'_observations')
        d=c.execute('SELECT ts_code,trade_date,source_instrument_code FROM '+q+" WHERE instrument_id='CN-EQUITY-601360.SH'").df()
        active=d[d.trade_date.ge('20140101')]
        assert active.loc[active.trade_date.lt('20180228'),'ts_code'].eq('601313.SH').all()
        assert active.loc[active.trade_date.ge('20180228'),'ts_code'].eq('601360.SH').all()
        fields=['open','high','low','close','pre_close','vol','amount'] if table=='stock_daily' else ['close','total_share','float_share'] if table=='stock_daily_basic' else ['adj_factor']
        changed=c.execute('SELECT count(*) FROM '+q+' a JOIN '+rel(table)+" b ON a.source_record_id=b.source_record_id WHERE a.instrument_id='CN-EQUITY-601360.SH' AND ("+' OR '.join('a.'+x+' IS DISTINCT FROM b.'+x for x in fields)+')').fetchone()[0]
        assert changed==0
        results.append({'dataset_id':table,'observations':len(d),'historical_code_rows':int(d.ts_code.eq('601313.SH').sum()),'changed_numeric_fields':changed})
    c.close();path=AUDIT/'issue_closure/identity_601313_601360.json';r=read(path)
    r.update(status='CLOSED_INDEPENDENTLY_VERIFIED',verification=results);write(path,r)
    return r


if __name__=='__main__':register()
