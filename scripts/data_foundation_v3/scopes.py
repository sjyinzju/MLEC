"""Separate the four documented TSF coverage expansions; never splice totals."""
import pandas as pd
from .common import ROOT,RAW,AUDIT,read_json,write_json,digest

TSF_BASE=['tsf_stock','tsf_stock_yoy','tsf_month_flow','tsf_ytd_flow']
TSF_REGIMES=[
    ('pre_201807','1900-01-01','2018-06-30','2018年7月扩围前'),
    ('201807','2018-07-01','2018-08-31','加入存款类机构ABS及贷款核销'),
    ('201809','2018-09-01','2019-08-31','再加入地方政府专项债券'),
    ('201909','2019-09-01','2019-11-30','再加入交易所企业ABS'),
    ('201912','2019-12-01','2100-12-31','再加入国债和地方政府一般债券'),
]


def regime_at(day):
    return next(key for key,start,end,_ in TSF_REGIMES if pd.Timestamp(start)<=day<=pd.Timestamp(end))


def scoped_id(base,scope):
    return base if scope=='201912' else base+'__scope_'+scope


def split_tsf_scopes(f):
    evidence=read_json(RAW/'tsf_scope_evidence.json')
    for r in evidence['sources']:
        if digest(ROOT/r['path'])!=r['sha256']:raise ValueError('TSF scope evidence changed')
    f=f.copy();f['concept_id']=f.series_id;f['statistical_scope_id']='as_registered'
    selected=f.series_id.isin(TSF_BASE)
    changes=[]
    for i,row in f[selected].iterrows():
        scope=regime_at(row.period_end)
        accepted=row.quality_status in ['strict_pit_eligible','conservative_release_reconstructed']
        # An undated modern compilation of an old period may be restated under a
        # later scope. A dated delayed reprint crossing a scope change is also
        # not enough to assign the original scope without a separate footnote.
        release_period=(row.release_at.tz_localize(None).to_period('M')-1).end_time.normalize() if pd.notna(row.release_at) else None
        uncertain=scope!='201912' and (not accepted or release_period is None or regime_at(release_period)!=scope)
        if uncertain:
            scope='unverified'
            if accepted:
                f.at[i,'quality_status']='latest_vintage_reconstructed'
                f.at[i,'claimed_available_at']=str(row.research_available_at)
                f.at[i,'research_available_at']=row.retrieved_at
                f.at[i,'release_at']=pd.NaT
                f.at[i,'time_quality']='historical_scope_unverified'
                f.at[i,'vintage_quality']='statistical_scope_unverified'
                f.at[i,'release_time_basis']='scope_unverified; retrieval_only'
        sid=scoped_id(row.series_id,scope)
        f.at[i,'series_id']=sid;f.at[i,'statistical_scope_id']='tsf_'+scope
        f.at[i,'adjustment_note']=str(row.adjustment_note)+'; v3 TSF statistical scope='+scope+'; no cross-scope splicing or total differences'
        changes.append({'source_record_id':row.source_record_id,'concept_id':row.series_id,'series_id':sid,'scope':scope,'period_end':row.period_end,'scope_unverified':uncertain})
    write_json(AUDIT/'tsf_scope_assignment.json',{'definition_evidence':evidence,'rows':changes})
    return f
