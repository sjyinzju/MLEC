"""Small, source-preserving repairs under the practical research contract."""
import json
import numpy as np
import pandas as pd
from .common import MACRO, META, ROOT, frame
from .macro_contract import specifications


def cumulative_supplements(facts, requirements):
    """Sum January..t only with continuous, accepted, same-scope monthly flows.

    Use earliest available accepted releases, not unknown future revisions.
    Derived sums describe these monthly observations, not a later restated
    official cumulative statistic. No replacement of accepted official totals.
    """
    base = facts[~facts.source_record_id.str.startswith('derived:practical_ytd:')].copy()
    accepted = base[base.certification_status.eq('ACCEPTED') & base.value.notna()
                    & base.quality_status.isin(['strict_pit_eligible', 'conservative_release_reconstructed'])]
    specs = {s['series_id']: s for s in specifications()}
    previous_derived=set(facts.loc[facts.source_record_id.str.startswith('derived:practical_ytd:'),
        ['series_id','period_end']].itertuples(index=False,name=None))
    derived_target=pd.Series([(r.series_id,r.period_end) in previous_derived for r in requirements.itertuples(index=False)],index=requirements.index)
    missing = requirements[~requirements.status.isin(['ACCEPTED', 'STRUCTURAL_NA'])|derived_target]
    additions = []
    for target in missing.itertuples(index=False):
        sid = target.series_id
        if sid == 'rmb_loans_ytd_flow':
            parent_sid = 'new_rmb_loans'
        elif sid.startswith('tsf_ytd_flow'):
            parent_sid = sid.replace('tsf_ytd_flow', 'tsf_month_flow', 1)
        else:
            continue
        end = pd.Timestamp(target.period_end)
        parents = accepted[accepted.series_id.eq(parent_sid) & accepted.period_end.dt.year.eq(end.year)
                           & accepted.period_end.le(end)].copy()
        parents = parents.sort_values(['period_end', 'research_available_at', 'source_record_id']).drop_duplicates('period_end')
        if parents.period_end.dt.month.tolist() != list(range(1, end.month + 1)):
            continue
        if any(parents[col].nunique(dropna=False) != 1 for col in ['unit', 'currency', 'statistical_scope_id']):
            continue
        if parents.research_available_at.isna().any() or not np.isfinite(parents.value).all():
            continue
        spec = specs[sid]
        row = parents.iloc[-1].to_dict()
        row.update(series_id=sid, series_name=spec['series_name'], concept_id=spec['concept_id'],
                   measure_type='ytd_flow', period_start=pd.Timestamp(end.year, 1, 1), period_end=end,
                   value=float(parents.value.sum()), original_value=np.nan,
                   source_record_id='derived:practical_ytd:'+sid+':'+end.strftime('%Y%m%d'),
                   source_name='Derived from accepted monthly publications', source_id='mlec:monthly_sum',
                   source_url='; '.join(sorted(set(parents.source_url.dropna()))),
                   source_class='derived_monthly_sum', quality_status='historical_reconstructed',
                   certification_status='ACCEPTED', release_at=pd.NaT,
                   research_available_at=parents.research_available_at.max(),
                   release_time_basis='max parent publication availability; no separate official YTD release',
                   revision_status='derived_earliest_accepted_monthly_editions',
                   vintage_id='practical_monthly_sum_v1', evidence_path=None, extracted_text=None,
                   extraction_evidence=None, publication_date_evidence=None,
                   reconstructed_quote_at=pd.NaT, original_series_id=parent_sid,
                   parent_record_ids=json.dumps(parents.source_record_id.tolist()),
                   reported_quantum=float(parents.reported_quantum.fillna(0).sum()),
                   adjustment_note='YTD=sum(January..t); same unit/currency/scope, complete months; resets each January.',
                   quality_reason='Derived sum of published monthly flows; may differ from revised official cumulative totals.',
                   data_foundation_version='practical-research-data-v5')
        additions.append(row)
    return pd.concat([base, pd.DataFrame(additions)], ignore_index=True), additions


def build():
    facts = pd.read_parquet(MACRO/'macro_facts.parquet')
    requirements = pd.read_parquet(META/'data_requirements_matrix.parquet')
    result, additions = cumulative_supplements(facts, requirements)
    assert not result.source_record_id.duplicated().any()
    frame(MACRO/'macro_facts.parquet', result)
    for name in ['macro_vintages', 'macro_release_events', 'macro_quality']:
        path = MACRO/(name+'.parquet')
        columns = pd.read_parquet(path).columns
        frame(path, result[columns])
    compact = pd.DataFrame(additions)[['source_record_id', 'series_id', 'period_end', 'value',
                                     'statistical_scope_id', 'parent_record_ids', 'research_available_at', 'quality_reason']]
    frame(ROOT/'data/metadata/practical_cumulative_derivations.parquet', compact)
    print('CUMULATIVE_SUPPLEMENTS', compact.groupby('series_id').size().to_dict(), flush=True)


def supplement_scope_transitions():
    """Use an explicitly restated 2018 table and a same-scope YTD anchor.

    A newly expanded scope can have published retrospective monthly values.
    Those values become available only when the restatement is published;
    they are never backdated to the original pre-expansion months.
    """
    facts=pd.read_parquet(MACRO/'macro_facts.parquet')
    facts=facts[~facts.source_record_id.str.startswith('practical:tsf_2018:')].copy()
    specs={s['series_id']:s for s in specifications()};add=[]
    capture=pd.Timestamp.now(tz='Asia/Shanghai')
    template=facts[facts.series_id.eq('tsf_ytd_flow__scope_201809')&facts.certification_status.eq('ACCEPTED')].iloc[0].to_dict()
    def make(sid,end,value,source,date,kind,parents=(),quantum=1.,note=''):
        s=specs[sid];period=pd.Timestamp(end);r=template.copy()
        at=pd.Timestamp(date+' 23:59:59',tz='Asia/Shanghai') if isinstance(date,str) else date
        rid='practical:tsf_2018:'+sid+':'+period.strftime('%Y%m%d')
        r.update(series_id=sid,series_name=s['series_name'],concept_id=s['concept_id'],
            statistical_scope_id=s['statistical_scope_id'],measure_type=s['measure_type'],
            period_start=pd.Timestamp(period.year,1,1) if s['measure_type']=='ytd_flow' else period.replace(day=1),
            period_end=period,observation_date=period,value=float(value),original_value=np.nan,
            source_record_id=rid,source_id='mlec:verified_2018_scope_supplement',source_url=source,
            source_name='PBOC statistics in dated government publications; explicit derivations',
            source_class=kind,research_available_at=at,release_at=pd.NaT if parents else at,
            value_quality='derived_from_verified_parents' if parents else 'verified_official_publication',
            time_quality='conservative_publication_clock',vintage_quality='dated_publication_reconstruction',
            release_time_basis='max parent availability' if parents else 'dated government publication, conservative end of day; not exact first release',
            quality_status='historical_reconstructed' if parents else 'conservative_release_reconstructed',
            certification_status='ACCEPTED',retrieved_at=capture,vintage_id='practical_tsf_scope_2018_v1',
            revision_status='explicit_201807_scope_backcast' if sid.endswith('201807') else 'dated_publication_or_same_scope_sum',
            parent_record_ids=json.dumps(list(parents)),reported_quantum=quantum,
            evidence_path='data/metadata/tsf_2018_scope_supplements.parquet',
            publication_date_evidence=source if not parents else None,extracted_text=None,extraction_evidence=None,
            scope_definition_evidence=source,claimed_available_at=None,
            publication_edition_order=0,publication_edition_evidence=source,
            reconstructed_quote_at=pd.NaT,original_series_id=sid,extraction_method='reviewed_literal_table_and_arithmetic',
            adjustment_note=note,quality_reason=note,data_foundation_version='practical-research-data-v5')
        add.append(r);return r
    source='https://dfjrjgj.hunan.gov.cn/tslm_71665/mtjj/201809/t20180913_5094330.html'
    values=[30733,11766,15106,16936,8476,13846,10371,15215]
    monthly=[]
    for month,value in enumerate(values,1):
        monthly.append(make('tsf_month_flow__scope_201807',pd.Timestamp(2018,month,1)+pd.offsets.MonthEnd(0),value,
            source,'2018-09-13','official_dated_scope_backcast',
            note='Explicit comparable 2018 monthly table after inclusion of depository-institution ABS and loan write-offs. All eight entries published together on 2018-09-13; not available in January-June and not mixed with pre-expansion flows.'))
    for month in [7,8]:
        make('tsf_ytd_flow__scope_201807',monthly[month-1]['period_end'],sum(values[:month]),source,
            '2018-09-13','derived_same_publication_backcast_sum',
            parents=[r['source_record_id'] for r in monthly[:month]],quantum=float(month),
            note='January..t sum from a single explicitly restated same-scope table; available only at the table publication, not the original observation month.')
    base=facts[facts.series_id.eq('tsf_ytd_flow__scope_201809')&facts.period_end.eq(pd.Timestamp('2018-09-30'))&facts.certification_status.eq('ACCEPTED')].sort_values('research_available_at').iloc[0]
    assert base.value==153700 and base.statistical_scope_id=='tsf_201809'
    for month in [10,11]:
        flows=facts[facts.series_id.eq('tsf_month_flow__scope_201809')&facts.period_end.dt.year.eq(2018)&facts.period_end.dt.month.between(10,month)&facts.certification_status.eq('ACCEPTED')].sort_values('research_available_at').drop_duplicates('period_end').sort_values('period_end')
        assert flows.period_end.dt.month.tolist()==list(range(10,month+1))
        assert flows.statistical_scope_id.eq(base.statistical_scope_id).all()
        assert flows.unit.eq(base.unit).all() and flows.currency.eq(base.currency).all()
        make('tsf_ytd_flow__scope_201809',pd.Timestamp(2018,month,1)+pd.offsets.MonthEnd(0),base.value+flows.value.sum(),
            '; '.join([base.source_url]+flows.source_url.tolist()),max(base.research_available_at,flows.research_available_at.max()),
            'derived_ytd_anchor_plus_months',parents=[base.source_record_id]+flows.source_record_id.tolist(),
            quantum=101. if month==10 else 201.,note='Published January-September YTD anchor plus complete October..t monthly flows, same 201809 scope. Sum of publication editions, not a claim of a later revised official cumulative total.')
    make('tsf_ytd_flow__scope_201809','2018-12-31',192600,
        'https://www.ndrc.gov.cn/fggz/fgzh/gnjjjc/hbjr/201901/t20190129_976682.html','2019-01-29',
        'official_dated_statistical_reproduction',quantum=100.,
        note='NDRC reproduction of PBOC 2018 annual TSF flow: 19.26 trillion CNY -> 192600 hundred-million CNY. Includes local government special bonds; availability at dated reproduction, no earlier-release claim.')
    result=pd.concat([facts,pd.DataFrame(add)],ignore_index=True)
    assert not result.source_record_id.duplicated().any()
    frame(MACRO/'macro_facts.parquet',result)
    for name in ['macro_vintages','macro_release_events','macro_quality']:
        path=MACRO/(name+'.parquet');frame(path,result[pd.read_parquet(path).columns])
    frame(ROOT/'data/metadata/tsf_2018_scope_supplements.parquet',pd.DataFrame(add)[[
        'source_record_id','series_id','period_end','value','unit','statistical_scope_id',
        'source_url','research_available_at','parent_record_ids','reported_quantum','quality_reason']])
    print('TSF_SCOPE_SUPPLEMENTS',len(add),'records, five previously missing cumulative periods',flush=True)


if __name__ == '__main__':
    build()
