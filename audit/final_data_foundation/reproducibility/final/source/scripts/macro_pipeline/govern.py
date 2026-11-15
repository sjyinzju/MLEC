"""Evidence preserving macro normalization. Unknown PIT is never certified."""
import re
import numpy as np
import pandas as pd
from scripts.experiment_framework.common import ROOT, TZ, digest, identity, read_json, save_frame, write_json, write_text

RAW=ROOT/'data/raw/macro/original_submissions/v1'
OUT=ROOT/'data/standardized/macro'
GROUPS={
    'prices':['cpi_yoy','cpi_mom','ppi_yoy','ppi_mom','core_cpi_yoy'],
    'growth':['pmi_mfg','pmi_new_orders','pmi_nonmfg','industrial_va_yoy','industrial_va_ytd_yoy','retail_sales_yoy','retail_sales_ytd_yoy','gdp_real_yoy','gdp_real_ytd_yoy'],
    'credit':['m2_yoy','m1_yoy','m1_new_yoy','new_rmb_loans','rmb_loans_ytd_flow','tsf_stock_yoy','tsf_month_flow','tsf_ytd_flow','tsf_stock'],
    'rates_fx':['shibor_1w','shibor_3m','shibor_on','lpr_1y','dr007','cgb_1y','cgb_10y','usdcny_fixing'],
    'external':['exports_yoy','imports_yoy']}
CORE=['cpi_yoy','ppi_yoy','pmi_mfg','pmi_new_orders','m2_yoy','shibor_1w','shibor_3m']

def group(sid):
    return next((g for g, ids in GROUPS.items() if sid in ids),'unclassified')

def timestamp(value):
    if pd.isna(value) or not str(value).strip(): return pd.NaT
    t=pd.Timestamp(value)
    return t.tz_localize(TZ) if t.tzinfo is None else t.tz_convert(TZ)

def parse_title(title):
    """Title scope belongs to the statistic, not to its release month."""
    t=re.sub(r'\s+','',str(title))
    m=re.search(r'(\d{4})年(?:(1)[—－–-])?(\d{1,2})月份?',t)
    if not m: return None
    year, cumulative, month=int(m[1]), bool(m[2]), int(m[3])
    if '社会消费品零售总额' in t: base='retail_sales'
    elif '规模以上工业增加值' in t: base='industrial_va'
    else: return None
    v=re.search(r'(增长|下降|降低)(-?\d+(?:\.\d+)?)%',t)
    if not v: return None
    val=float(v[2])*(-1 if v[1] in ('下降','降低') else 1)
    end=pd.Timestamp(year,month,1)+pd.offsets.MonthEnd(0)
    return dict(series_id=base+('_ytd_yoy' if cumulative else '_yoy'),value=val,
                measure_type='ytd_yoy' if cumulative else 'yoy',period_start=pd.Timestamp(year,1 if cumulative else month,1),period_end=end)

def parse_loan(text):
    """Only explicit cumulative loan flow; never infer a monthly amount."""
    t=re.sub(r'\s+','',text)
    m=re.search(r'(?:前([一二三四五六七八九十]+)个月|全年|上半年|前三季度|一季度|[1１][—－–-](\d+)月)人民币贷款增加([\d.]+)(万亿元|亿元)',t)
    if not m: return None
    return float(m[3])*(10000 if m[4]=='万亿元' else 1)

def validate_facts(f):
    key=['series_id','period_start','period_end','vintage_id','source_record_id']
    assert not f.duplicated(key).any(), 'duplicate version key'
    assert f.period_start.le(f.period_end).all()
    for sid,d in f.groupby('series_id'):
        assert d.measure_type.nunique()==1, f'mixed statistical meaning: {sid}'
        assert d.unit.nunique()==1, f'mixed unit: {sid}'
    strict=f[f.quality_status.eq('strict_pit_eligible')]
    assert strict.research_available_at.notna().all()
    assert strict.release_at.notna().all()
    assert strict.vintage_quality.eq('announcement_value_verified').all()
    assert np.isfinite(strict.value).all()

def build(write_outputs=True,retrieval_times=None):
    raw=pd.read_parquet(RAW/'deliverables/macro_raw.parquet')
    titles=pd.read_csv(RAW/'data_raw/nbs_list_items.csv').drop_duplicates('url').set_index('url')
    manifest=ROOT/'data/raw/macro/official_sources/page_manifest.json'
    pages=read_json(manifest) if manifest.exists() else {}
    from lxml import html
    texts={}
    needed_urls=set(raw.source_url)
    for u,r in pages.items():
        if r['status']!='ok' or u not in needed_urls: continue
        if digest(ROOT/r['path'])!=r['sha256']:raise ValueError('Cached source changed: '+u)
        texts[u]=html.fromstring((ROOT/r['path']).read_bytes().decode(r['encoding'],errors='replace')).text_content()
    print('Official page evidence decoded:',len(texts),flush=True)
    facts=[]; corrections=[]
    for r in raw.to_dict('records'):
        sid=r['series_id']; end=pd.Timestamp(r['period_end']); freq=r['frequency']
        start=end if freq=='D' else end.to_period('Q' if freq=='Q' else 'M').start_time
        retrieved=timestamp(r['retrieved_at'])
        x=dict(series_id=sid,series_name=r['series_name'],series_group=group(sid),value=r['value'],unit=r['unit'],
               currency='USD' if sid in ['exports_yoy','imports_yoy'] else ('CNY' if sid=='new_rmb_loans' else 'NA'),
               frequency=freq,measure_type=r['measure_type'],period_start=start,period_end=end,observation_date=end,
               release_at=pd.NaT,research_available_at=retrieved,release_time_basis='historical_release_unverified; gated_at_retrieval',
               vintage_id='submission-'+str(r['vintage_date']),revision_status=r['revision_flag'],
               source_name=r['source_name'],source_url=r['source_url'],source_record_id=r['row_id'],retrieved_at=retrieved,
               value_quality='unverified_submission',time_quality='unknown',vintage_quality='latest_or_unverified',
               quality_status='latest_vintage_reconstructed',adjustment_note=str(r['adjustment_note']),
               original_series_id=sid,original_value=r['value'],claimed_available_at=str(r['available_at']),
               evidence_path='data/raw/macro/original_submissions/v1/deliverables/macro_raw.parquet')
        if sid=='retail_sales_ytd_yoy': x['period_start']=pd.Timestamp(end.year,1,1)
        if sid=='gdp_real_yoy' and 'eastmoney' in r['source_url']:
            # Peer collector uses RPT_ECONOMY_GDP.SUM_SAME: cumulative GDP.
            # E.g. 2020-Q2 is -1.6 (Jan-Jun), not the quarter's +3.2.
            x.update(series_id='gdp_real_ytd_yoy',measure_type='ytd_yoy',period_start=pd.Timestamp(end.year,1,1),
                     value_quality='provider_scope_reconciled',adjustment_note='Peer script maps SUM_SAME cumulative GDP; relabeled YTD, not quarterly growth; historical vintage remains unverified')
            corrections.append(dict(source_record_id=r['row_id'],old_series=sid,new_series=x['series_id'],old_value=r['value'],new_value=x['value'],title='RPT_ECONOMY_GDP.SUM_SAME cumulative scope, verified against 2020 Q2 official -1.6 YTD versus +3.2 quarter',url=r['source_url']))
        if sid in ['industrial_va_yoy','retail_sales_ytd_yoy']:
            x.update(quality_status='blocked',adjustment_note='Statistical scope requires title/body evidence')
            if r['source_url'] in titles.index:
                title=titles.loc[r['source_url'],'title']; parsed=parse_title(title)
                if parsed:
                    x.update(parsed); x.update(value_quality='title_verified',quality_status='latest_vintage_reconstructed',adjustment_note='Scope and sign reparsed from preserved NBS title; original value retained')
                    corrections.append(dict(source_record_id=r['row_id'],old_series=sid,new_series=x['series_id'],old_value=r['value'],new_value=x['value'],title=title,url=r['source_url']))
        if sid=='new_rmb_loans':
            x.update(quality_status='blocked',adjustment_note='Monthly versus YTD flow unverified; no monthly derivation')
            v=parse_loan(texts.get(r['source_url'],''))
            if v is not None:
                x.update(series_id='rmb_loans_ytd_flow',measure_type='ytd_flow',value=v,unit='亿元',period_start=pd.Timestamp(end.year,1,1),value_quality='body_ytd_verified',quality_status='latest_vintage_reconstructed',adjustment_note='Explicit YTD amount parsed from official body; not monthly flow')
        if sid.startswith('shibor'):
            x.update(period_start=end,observation_date=end,frequency='D',measure_type='level',unit='%')
        # Signed monthly industrial/retail values may be stated separately from the title.
        text=texts.get(r['source_url'],''); compact=re.sub(r'\s+','',text)
        date=str(r['release_date'])
        date_verified=bool(text and date and (date in text or date.replace('-','/') in text))
        def certify(value):
            value.update(release_at=timestamp(date+' 23:59:59'),research_available_at=timestamp(date+' 23:59:59'),
                         time_quality='page_date_verified_time_end_of_day',release_time_basis='official_dated_announcement_end_of_day',
                         vintage_quality='announcement_value_verified',quality_status='strict_pit_eligible',revision_status='dated_announcement',
                         vintage_id='announcement-'+date,evidence_path=pages[r['source_url']]['path'])
        if date_verified and r['source_url'] in titles.index and x['value_quality']=='title_verified':
            if re.sub(r'\s+','',titles.loc[r['source_url'],'title']) in compact:certify(x)
        if text and sid in ['industrial_va_yoy','retail_sales_ytd_yoy']:
            monthly=(rf'(?<![\d—－–-]){end.month}月份[，,](?:全国)?规模以上工业增加值同比(?:实际)?(增长|下降)([\d.]+)%' if sid=='industrial_va_yoy'
                     else rf'(?<![\d—－–-]){end.month}月份[，,]社会消费品零售总额[\d.]+亿元[，,]同比(增长|下降)([\d.]+)%')
            m=re.search(monthly,compact)
            if m:
                derived=x.copy(); derived.update(series_id='industrial_va_yoy' if sid=='industrial_va_yoy' else 'retail_sales_yoy',measure_type='yoy',period_start=end.to_period('M').start_time,value=float(m[2])*(-1 if m[1]=='下降' else 1),value_quality='official_body_verified',source_record_id=r['row_id']+'-monthly',adjustment_note='Monthly value separately extracted from official body')
                if date_verified:certify(derived)
                facts.append(derived)
        if text:
            x['evidence_path']=pages[r['source_url']]['path']
            # Preserve a dated announcement only when page timestamp matches original claim.
            if date and (date in text or date.replace('-','/') in text):
                x.update(release_at=timestamp(date+' 23:59:59'),time_quality='page_date_verified_time_end_of_day',release_time_basis='official_page_date; end_of_day')
        x['series_group']=group(x['series_id']); facts.append(x)
    # Reparse every preserved title, including negative titles omitted by the old scraper.
    for url,r in titles.iterrows():
        p=parse_title(r.title)
        if not p: continue
        template=next((a for a in facts if a['source_url']==url),None)
        if template is None:
            template=next(a for a in facts if a['series_id'].startswith(p['series_id'].split('_y')[0])).copy()
            template.update(source_url=url,source_record_id='title-'+identity(url)[:16],original_value=None,
                            value_quality='title_verified',quality_status='latest_vintage_reconstructed',
                            release_at=pd.NaT,time_quality='submission_date_only',evidence_path='data/raw/macro/original_submissions/v1/data_raw/nbs_list_items.csv',
                            adjustment_note='Recovered title omitted by original parser; publication/vintage not certified')
            template.update(p);template['observation_date']=p['period_end'];facts.append(template)
    # Read-only local extraction retains every observed vintage; retrieval is not publication.
    mapping={'cn_cpi':{'nt_yoy':('cpi_yoy','yoy','%')},'cn_ppi':{'ppi_yoy':('ppi_yoy','yoy','%')},
             'cn_m':{'m2_yoy':('m2_yoy','yoy','%')},
             'cn_pmi':{'pmi010000':('pmi_mfg','level','index'),'pmi010500':('pmi_new_orders','level','index')},
             'sf_month':{'inc_month':('tsf_month_flow','flow','亿元'),'inc_cumval':('tsf_ytd_flow','ytd_flow','亿元'),'stk_endval':('tsf_stock','stock','万亿元')}}
    for ep,cols in mapping.items():
        path=ROOT/f'data/raw/macro/third_party_sources/quant/{ep}.parquet'
        if not path.exists(): continue
        for r in pd.read_parquet(path).to_dict('records'):
            end=pd.Timestamp(str(r['month'])+'01')+pd.offsets.MonthEnd(0)
            for col,(sid,measure,unit) in cols.items():
                if pd.isna(r[col]): continue
                retrieved=timestamp(r['_ingested_at'])
                facts.append(dict(series_id=sid,series_name=sid,series_group=group(sid),value=r[col],unit=unit,currency='CNY' if ep=='sf_month' else 'NA',frequency='M',measure_type=measure,
                    period_start=pd.Timestamp(end.year,1,1) if measure=='ytd_flow' else end.to_period('M').start_time,period_end=end,observation_date=end,
                    release_at=pd.NaT,research_available_at=retrieved,release_time_basis='provider_observed_only; gated_at_retrieval',
                    vintage_id=str(r['_revision']),revision_status='provider_latest',source_name='TuShare local registered active extraction',source_url='https://tushare.pro/document/2?doc_id=325' if ep=='cn_pmi' else 'https://tushare.pro',
                    source_record_id=r['_row_hash']+'-'+col,retrieved_at=retrieved,value_quality='mapped_provider_field',time_quality='unknown',vintage_quality='observed_only',quality_status='latest_vintage_reconstructed',adjustment_note='Source field '+col+'; not certified first-release history',original_series_id=sid,original_value=r[col],claimed_available_at='',evidence_path=path.relative_to(ROOT).as_posix()))
    from scripts.macro_pipeline.supplement import build as supplement
    print('Submission normalized:',len(facts),flush=True)
    facts.extend(supplement(retrieval_times=retrieval_times))
    print('Combined macro facts:',len(facts),flush=True)
    f=pd.DataFrame(facts)
    # One source/period/measure/vintage fact; separately extracted identical body values
    # are corroboration, not a second observation. Conflicting values remain auditable.
    f=f.drop_duplicates(['series_id','period_start','period_end','vintage_id','source_url','value'],keep='last')
    # M1 definition changed in January 2025; do not splice regimes silently.
    f.loc[f.series_id.eq('m1_yoy') & f.period_end.ge('2025-01-01'),'series_id']='m1_new_yoy'
    f['series_group']=f.series_id.map(group)
    f['series_name']=f.series_id.map({
        'industrial_va_yoy':'规模以上工业增加值当月同比','industrial_va_ytd_yoy':'规模以上工业增加值累计同比',
        'retail_sales_yoy':'社会消费品零售总额当月同比','retail_sales_ytd_yoy':'社会消费品零售总额累计同比',
        'rmb_loans_ytd_flow':'年初以来累计新增人民币贷款'}).fillna(f.series_name)
    # Canonical unit for PMI levels is an index, even when official tables print a percent sign.
    f.loc[f.series_id.str.startswith('pmi_'),'unit']='index'
    for c in ['release_at','research_available_at','retrieved_at']: f[c]=pd.to_datetime(f[c],utc=True).dt.tz_convert(TZ)
    key=['series_id','period_start','period_end','vintage_id','source_record_id']
    f=f.drop_duplicates(key).sort_values(['series_id','period_end','research_available_at','source_record_id'])
    validate_facts(f)
    if not write_outputs:return f
    save_frame(OUT/'macro_facts.parquet',f)
    save_frame(OUT/'macro_vintages.parquet',f[key+['revision_status','vintage_quality','retrieved_at','value']])
    save_frame(OUT/'macro_release_events.parquet',f[key+['release_at','research_available_at','release_time_basis','time_quality']])
    save_frame(ROOT/'data/metadata/data_lineage.parquet',f[key+['source_name','source_url','evidence_path','original_series_id','original_value','adjustment_note']])
    save_frame(ROOT/'audit/framework/macro_corrections.parquet',pd.DataFrame(corrections))
    coverage=[]
    for sid,d in f.groupby('series_id'):
        periods=d.period_end.drop_duplicates().sort_values();freq=d.frequency.iloc[0]
        expected=pd.date_range(periods.min(),periods.max(),freq='ME' if freq=='M' else 'QE') if freq in ['M','Q'] else periods
        expected=pd.DatetimeIndex(expected)
        missing=expected.difference(pd.DatetimeIndex(periods))
        accepted=d[d.quality_status.isin(['strict_pit_eligible','conservative_release_reconstructed'])]
        initial=accepted[accepted.period_end.between('2014-01-01','2019-12-31')]
        coverage.append(dict(series_id=sid,group=group(sid),start=str(periods.min().date()),end=str(periods.max().date()),records=len(d),observations=len(periods),expected_periods=len(expected),coverage=len(periods)/len(expected),missing_periods=','.join(str(x.date()) for x in missing),nonfinite=int((~np.isfinite(d.value)).sum()),version_duplicates=int(d.duplicated(key).sum()),strict_rows=int(d.quality_status.eq('strict_pit_eligible').sum()),initial_training_eligible=bool(len(initial)),quality=';'.join(sorted(d.quality_status.unique())),daily_expected_basis='observed_quote_dates_only; official calendar not certified' if freq=='D' else 'calendar_months; January gaps may be structural'))
    cover=pd.DataFrame(coverage); path=ROOT/'data/metadata/macro_feature_catalog.csv';path.parent.mkdir(parents=True,exist_ok=True);cover.to_csv(path,index=False,encoding='utf-8-sig')
    write_json(ROOT/'audit/framework/macro_gate.json',{'core_eligible':None,'reason':'Await joint as-of coverage acceptance; latest/unverified vintages remain gated at retrieval','quality_counts':f.quality_status.value_counts().to_dict(),'core':CORE,'missing_candidates':[s for ids in GROUPS.values() for s in ids if s not in set(f.series_id)]})
    write_text(ROOT/'reports/data_quality/macro_coverage.md','# Macro candidate coverage\n\n'+cover.to_markdown(index=False)+'\n\nDaily expected counts use observed quotes, not a certified full quotation calendar. Missing-month detail is retained in the CSV. No daily date was converted to month-end.\n')
    return f
