"""Full-data validation with one compact result, no row-level audit copies."""
import numpy as np
from .common import *
from .research_inputs import LEVELS,FEATURES,load_dataset


def build():
    c=db();registry=read(ROOT/'data/metadata/dataset_registry.json');checks=[];tables=[]
    def check(name,actual,expected=0):
        ok=actual==expected;checks.append(dict(check=name,actual=actual,expected=expected,passed=ok))
        assert ok,(name,actual,expected)
    for item in registry['datasets']:
        name=item['dataset_id'];rel='read_parquet('+qs(ROOT/item['authority_path'])+',union_by_name=true)'
        schema=c.execute('DESCRIBE SELECT * FROM '+rel).fetchall();cols=[r[0] for r in schema]
        check(name+':required_columns',len(set(item['required_fields'])-set(cols)))
        key=','.join('"'+k+'"' for k in item['primary_key'])
        missing_key=' OR '.join('"'+k+'" IS NULL' for k in item['primary_key'])
        check(name+':primary_key_nonnull',c.execute('SELECT count(*) FROM '+rel+' WHERE '+missing_key).fetchone()[0])
        excess=c.execute('SELECT coalesce(sum(n-1),0) FROM (SELECT count(*) n FROM '+rel+' GROUP BY '+key+' HAVING count(*)>1)').fetchone()[0]
        check(name+':unique_key',int(excess))
        counts=c.execute('SELECT count(*),'+','.join('count(*) FILTER(WHERE "'+f+'" IS NULL)' for f in cols)+' FROM '+rel).fetchone()
        date=item.get('date_field');bounds=c.execute('SELECT min("'+date+'"),max("'+date+'") FROM '+rel).fetchone() if date in cols else (None,None)
        tables.append(dict(dataset_id=name,rows=counts[0],authority_path=item['authority_path'],
            primary_key=item['primary_key'],columns=dict((r[0],r[1]) for r in schema),
            nulls=dict(zip(cols,counts[1:])),start=str(bounds[0]),end=str(bounds[1])))
        print('FULL_TABLE',name,counts[0],flush=True)
    daily='read_parquet('+qs(MARKET/'stock_daily_observations/*.parquet')+')'
    idx='read_parquet('+qs(MARKET/'index_daily/*.parquet')+')'
    for label,rel in [('stock',daily),('index',idx)]:
        check(label+':ohlc_numeric',c.execute('SELECT count(*) FROM '+rel+" WHERE close<=0 OR open<=0 OR high<greatest(open,close,low) OR low>least(open,close,high) OR vol<0 OR amount<0").fetchone()[0])
    identity='read_parquet('+qs(MARKET/'stock_master_history.parquet')+')'
    check('stock:identity_interval',c.execute('SELECT count(*) FROM '+daily+' d WHERE NOT EXISTS (SELECT 1 FROM '+identity+" i WHERE i.ts_code=d.ts_code AND i.instrument_id=d.instrument_id AND strptime(d.trade_date,'%Y%m%d')>=i.valid_from AND strptime(d.trade_date,'%Y%m%d')<i.valid_to)").fetchone()[0])
    check('stock:quote_factor_coverage',c.execute('SELECT count(*) FROM '+daily+' d LEFT JOIN read_parquet('+qs(MARKET/'stock_adjustment_observations/*.parquet')+") f USING(instrument_id,trade_date) WHERE f.adj_factor IS NULL OR f.adj_factor<=0").fetchone()[0])
    check('index:registered_date_grid',c.execute('SELECT count(*) FROM '+idx).fetchone()[0],3095*7)
    check('szse:stock_total_date_grid',c.execute('SELECT count(DISTINCT trade_date) FROM read_parquet('+qs(MARKET/'exchange_activity_sz/*.parquet')+",union_by_name=true) WHERE ts_code='股票'").fetchone()[0],3095)
    check('szse:positive_stock_capitalization',c.execute('SELECT count(*) FROM read_parquet('+qs(MARKET/'exchange_activity_sz/*.parquet')+",union_by_name=true) WHERE ts_code IN ('股票','创业板A股') AND (total_mv<=0 OR float_mv<=0 OR amount<0)").fetchone()[0])
    check('sse:date_grid',c.execute('SELECT count(DISTINCT trade_date) FROM read_parquet('+qs(MARKET/'exchange_activity_sh/*.parquet')+')').fetchone()[0],3095)
    p=pd.read_parquet(ROOT/'data/metadata/szse_quantity_derivations.parquet')
    sz=c.execute('SELECT * FROM read_parquet(?,union_by_name=true)',[str(MARKET/'exchange_activity_sz/*.parquet')]).df().set_index(['ts_code','trade_date'])
    for r in p.itertuples(index=False):
        assert abs(sum(json.loads(r.parent_quantities_100m_shares))*1e8-r.value)<1
        assert abs(sz.loc[(r.ts_code,r.trade_date),r.field]-r.value)<1
        for f in ['amount','total_mv','float_mv']:
            assert abs(sz.loc[(r.ts_code,r.trade_date),f]-getattr(r,'matched_'+f+'_cny'))<1
    checks.append(dict(check='szse:all_quantity_parent_formulas',actual=len(p),passed=True))
    check('stock:basic_matches_quote_grid',c.execute('SELECT count(*) FROM '+daily+' d ANTI JOIN read_parquet('+qs(MARKET/'stock_daily_basic_observations/*.parquet')+') b USING(instrument_id,trade_date)').fetchone()[0])
    f=pd.read_parquet(MACRO/'macro_facts.parquet');check('macro:finite_numeric_values',int((f.value.notna()&~np.isfinite(f.value)).sum()))
    lookup=f.set_index('source_record_id');derived=f[f.source_record_id.str.startswith(('derived:practical_ytd:','practical:tsf_2018:'))&f.parent_record_ids.ne('[]')]
    for row in derived.itertuples(index=False):
        p=lookup.loc[json.loads(row.parent_record_ids)]
        assert abs(p.value.sum()-row.value)<1e-7
        assert p.research_available_at.max()<=row.research_available_at
        assert p.statistical_scope_id.nunique()==p.unit.nunique()==p.currency.nunique()==1
    checks.append(dict(check='macro:all_practical_derivations',actual=len(derived),passed=True))
    market=pd.read_parquet(ROOT/'data/research_v2/market_features_weekly.parquet')
    check('frozen:sample_count',len(market),599)
    eligibility=[]
    for level in LEVELS:
        weekly=pd.read_parquet(FEATURES/level/'macro_weekly.parquet');lin=pd.read_parquet(FEATURES/level/'macro_lineage.parquet')
        assert weekly.sample_id.tolist()==market.sample_id.tolist()
        for row in lin[lin.value.notna()].itertuples(index=False):
            dates=[pd.Timestamp(x) for x in json.loads(row.available_ats)]
            assert dates and max(dates)<=row.asof_time
            if row.feature.endswith('__change'):assert len(set(json.loads(row.statistical_scope_ids)))==1
        checks.append(dict(check=level+':all_feature_times_and_scopes',actual=int(lin.value.notna().sum()),passed=True))
        for group in ['M','growth','prices','credit','rates','external','all_candidates']:
            groups=[] if group=='M' else ['growth','prices','credit','rates','external'] if group=='all_candidates' else [group]
            r=load_dataset(groups=groups,quality=level)
            assert len(r['features'])==len(r['eligibility'])==599
            eligibility.append(dict(quality=level,information_set=group,eligible_h20=int(r['eligibility'].eligible.sum())))
    keep=read(ROOT/'data/metadata/frozen_integrity_hashes.json')
    for p,meta in keep.items():assert sha(ROOT/p)==meta['sha256'],p
    checks.append(dict(check='frozen:content_hashes',actual=len(keep),passed=True))
    from .validate_repairs import validate
    validate(c,check)
    write(ROOT/'data/metadata/final_validation.json',{'version':'practical-research-data-v5',
        'technical_checks_passed':True,'data_completeness_separately_assessed':True,
        'checks':checks,'tables':tables,'eligibility':eligibility,
        'warning':'Technical checks passing does not certify missing values or resolve flagged source conflicts.'})
    c.close();print('FULL_VALIDATION_PASS',len(checks),flush=True)


if __name__=='__main__':build()
