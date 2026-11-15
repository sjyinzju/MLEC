"""V4 scope amendments, preserving v3 contracts and facts as immutable inputs."""
from copy import deepcopy
from .common import *
from scripts.data_foundation_v3.requirements import specifications as prior_specifications
from scripts.data_foundation_v3.scopes import TSF_BASE,TSF_REGIMES as PRIOR_REGIMES

TSF_REGIMES=[(*r[:2],'2022-12-31',r[3]) if r[0]=='201912' else r for r in PRIOR_REGIMES]
TSF_REGIMES.append(('202301','2023-01-01','2100-12-31','纳入消费金融公司、理财公司及金融资产投资公司等银行业非存款机构'))


def specifications():
    specs=deepcopy(prior_specifications())
    for sid in TSF_BASE:
        old=next(s for s in specs if s['series_id']==sid)
        new=deepcopy(old);new.update(series_id=sid+'__scope_202301',statistical_scope_id='tsf_202301',required_start='2023-01-01',
            series_name=old['series_name'].replace('2019年12月扩围后','2023年1月扩围后'))
        old['required_end']='2022-12-31';specs.append(new)
    for s in specs:
        if s['series_id'] in ['new_rmb_loans','rmb_loans_ytd_flow','rmb_loan_balance_yoy']:
            s['within_series_scope_policy']='Record-level loan scope: before 2015; 2015 includes lending to nonbank financial institutions; 2023 expands reporting institutions. Never calculate feature changes across these breaks.'
    return specs


def apply_scopes(f):
    f=f.copy();amend=[]
    # New earlier bulletins must use their historical scope too. Inherited v3
    # facts already have scoped IDs and are therefore untouched by this branch.
    for i,r in f[f.series_id.isin(TSF_BASE)&f.period_end.lt('2019-12-01')].iterrows():
        regime=next(key for key,start,end,_ in TSF_REGIMES if pd.Timestamp(start)<=r.period_end<=pd.Timestamp(end))
        release_period=(r.release_at.tz_localize(None).to_period('M')-1).end_time.normalize() if pd.notna(r.release_at) else None
        released_regime=next((key for key,start,end,_ in TSF_REGIMES if release_period is not None and pd.Timestamp(start)<=release_period<=pd.Timestamp(end)),None)
        assert r.quality_status in ['strict_pit_eligible','conservative_release_reconstructed'] and regime==released_regime, 'New early TSF supplement needs contemporaneous scope evidence'
        f.at[i,'series_id']=r.series_id+'__scope_'+regime;f.at[i,'statistical_scope_id']='tsf_'+regime
        f.at[i,'adjustment_note']=str(r.adjustment_note)+'; contemporaneous pre-expansion scope='+regime
    for i,r in f[f.series_id.isin(TSF_BASE)&f.period_end.ge('2023-01-01')].iterrows():
        f.at[i,'series_id']=r.series_id+'__scope_202301';f.at[i,'statistical_scope_id']='tsf_202301'
        f.at[i,'adjustment_note']=str(r.adjustment_note)+'; v4 separates 2023-01 statistical reporting institution expansion; PBOC reproduced report note 4.'
        amend.append({'source_record_id':r.source_record_id,'previous_series_id':r.series_id,'series_id':f.at[i,'series_id']})
    write(AUDIT/'macro_coverage/tsf_2023_scope_amendment.json',{'evidence_url':'https://jrb.qingdao.gov.cn/jrdt/202607/t20260715_10677449.shtml',
      'literal':'自2023年1月起，中国人民银行将消费金融公司、理财公司和金融资产投资公司等三类银行业非存款类金融机构纳入金融统计范围。由此，对社会融资规模中“对实体经济发放的人民币贷款”和“贷款核销”数据进行了调整。',
      'amended_records':amend,'v3_files_modified':False})
    from .collect import PUBLIC
    from lxml import html
    import re
    urls=[('https://www.gdjr.gov.cn/gdjr/jrzx/jryw/content/mpost_2075.html','自2015年起，人民币、外币和本外币存款含非银行业金融机构存放款项，人民币、外币和本外币贷款含拆放给非银行业金融机构的款项。'),
      ('https://jrb.qingdao.gov.cn/jrdt/202607/t20260715_10677449.shtml','自2023年1月起，中国人民银行将消费金融公司、理财公司和金融资产投资公司等三类银行业非存款类金融机构纳入金融统计范围。')]
    receipts={r['url']:r for p in (PUBLIC/'requests').glob('*.json') if (r:=read(p))['status']=='ok'};evidence=[]
    for url,literal in urls:
        rec=receipts[url];assert sha(ROOT/rec['path'])==rec['sha256']
        text=re.sub(r'\s+','',html.fromstring((ROOT/rec['path']).read_bytes().decode(rec['encoding'])).text_content());assert literal in text
        evidence.append({'url':url,'path':rec['path'],'sha256':rec['sha256'],'literal':literal})
    mask=f.series_id.isin(['new_rmb_loans','rmb_loans_ytd_flow','rmb_loan_balance_yoy'])
    for begin,end,scope in [('1900-01-01','2014-12-31','loan_pre_201501'),('2015-01-01','2022-12-31','loan_201501'),('2023-01-01','2100-12-31','loan_202301')]:
        q=mask&f.period_end.between(begin,end);f.loc[q,'statistical_scope_id']=scope
    f.loc[mask,'scope_definition_evidence']='audit/final_data_foundation/macro_coverage/loan_scope_amendment.json'
    write(AUDIT/'macro_coverage/loan_scope_amendment.json',{'evidence':evidence,'affected_records':int(mask.sum()),'policy':'Values retain original reporting scope; no backward comparable-series reconstruction. Previous/change features do not cross scope breaks.'})
    return f


def configure_quality(quality):
    quality.AUDIT=AUDIT/'macro_coverage';quality.METADATA=META;quality.STANDARD=MACRO
    quality.specifications=specifications;quality.TSF_REGIMES=TSF_REGIMES
