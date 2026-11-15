"""Small, evidence-bound corrections; raw provider snapshots remain immutable."""
from .common import *
from .market import rel


PRICE_DEPENDENT=['pe','pe_ttm','pb','ps','ps_ttm','dv_ratio','dv_ttm','volume_ratio']
RECOMPUTED=['close','total_mv','circ_mv','turnover_rate','turnover_rate_f']


def repair_daily_basic():
    evidence=read(AUDIT/'source_reconciliation/stock_close_independent.json');c=db();repairs=[]
    for row in evidence:
        if row['unadjusted_rows']:
            r=row['second_source'];raw=read(ROOT/r['path']);quote=raw['data']['klines'][0].split(',')
            day=quote[0].replace('-','');close=float(quote[2])
        else:
            r=row['sohu_source'];raw=json.loads((ROOT/r['path']).read_bytes().decode(r['encoding']));quote=raw[0]['hq'][0];day=quote[0].replace('-','');close=float(quote[2])
        assert sha(ROOT/r['path'])==r['sha256'] and day==row['trade_date'] and abs(close-row['price_close'])<1e-9
        primary=c.execute('SELECT close,vol,source_record_id FROM '+rel('stock_daily')+' WHERE ts_code=? AND trade_date=?',[row['ts_code'],day]).fetchone()
        assert abs(primary[0]-close)<1e-9
        repairs.append({**row,'verified_close':close,'verified_volume_hands':primary[1],'quote_source_record_id':primary[2],
                        'verification_evidence':r['path'],'verification_sha256':r['sha256'],
                        'repair_id':'BASIC_CLOSE_'+row['ts_code']+'_'+day})
    c.close();fields=PRICE_DEPENDENT+RECOMPUTED;results=[]
    for path in sorted((MARKET/'stock_daily_basic').glob('*.parquet')):
        relevant=[x for x in repairs if x['trade_date'][:4] in path.stem]
        if not relevant:continue
        data=pd.read_parquet(path)
        for field in fields:
            if 'provider_'+field not in data:data['provider_'+field]=data[field]
        if 'repair_id' not in data:data['repair_id']=None
        if 'parent_record_ids' not in data:data['parent_record_ids']=None
        if 'field_quality_note' not in data:data['field_quality_note']=None
        for r in relevant:
            mask=data.ts_code.eq(r['ts_code'])&data.trade_date.eq(r['trade_date']);assert mask.sum()==1
            i=data.index[mask][0];record=data.loc[i]
            assert abs(record['provider_close']-r['basic_close'])<1e-9
            changes={'close':r['verified_close'],'total_mv':r['verified_close']*record.total_share,
                     'circ_mv':r['verified_close']*record.float_share,
                     'turnover_rate':r['verified_volume_hands']/record.float_share,
                     'turnover_rate_f':r['verified_volume_hands']/record.free_share if pd.notna(record.free_share) and record.free_share>0 else None}
            for field,value in changes.items():data.loc[i,field]=value
            for field in PRICE_DEPENDENT:data.loc[i,field]=float('nan')
            data.loc[i,'repair_id']=r['repair_id'];data.loc[i,'parent_record_ids']=json.dumps([r['basic_record_id'],r['quote_source_record_id'],r['verification_evidence']])
            data.loc[i,'source_record_id']='derived:'+r['repair_id'];data.loc[i,'source_id']='mlec:verified_quote_basic_repair'
            data.loc[i,'quality_reason']='Daily/basic close conflict verified against independent unadjusted quote. Close and cap/turnover formulas recomputed; share denominators retain provider reconstruction quality.'
            data.loc[i,'field_quality_note']='pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,volume_ratio blocked: conflicting quote snapshot; original denominators/time basis cannot be independently established. Original values retained in provider_* columns for audit only.'
            results.append({'repair_id':r['repair_id'],'ts_code':r['ts_code'],'trade_date':r['trade_date'],
                'changes':changes,'original_close':r['basic_close'],'evidence':r['verification_evidence'],
                'blocked_fields':PRICE_DEPENDENT,'status':'CLOSE_REPAIRED_VALUATION_FIELDS_QUARANTINED',
                'root_cause':'Source daily_basic row uses a close different from independently verified daily close; provider internals unknown.'})
        frame(path,data)
    assert len(results)==7
    write(AUDIT/'issue_closure/daily_basic_repairs.json',results)
    print('Repaired',len(results),'daily_basic rows; valuation fields explicitly quarantined',flush=True)


if __name__=='__main__':repair_daily_basic()
