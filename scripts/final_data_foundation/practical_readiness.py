"""Refresh actual macro completeness without rebuilding historical audit files."""
from .common import *
from .research_inputs import prepare
from .macro_contract import specifications


def build():
    path=META/'data_requirements_matrix.parquet'
    matrix=pd.read_parquet(path);facts=pd.read_parquet(MACRO/'macro_facts.parquet')
    if 'prior_strict_workflow_status' not in matrix:
        matrix['prior_strict_workflow_status']=matrix.status
    available=prepare(facts,'historical_reconstructed')
    groups={k:g for k,g in available.groupby(['series_id','period_end'])}
    numeric={k:len(g) for k,g in facts[facts.value.notna()].groupby(['series_id','period_end'])}
    matrix['numeric_candidate_rows']=[numeric.get((r.series_id,r.period_end),0) for r in matrix.itertuples(index=False)]
    matrix['historical_reconstructed_rows']=0
    for i,r in matrix.iterrows():
        g=groups.get((r.series_id,r.period_end))
        if g is None:continue
        # Contradictory source values still require ACCEPTED certification in prepare.
        matrix.at[i,'status']='ACCEPTED'
        matrix.at[i,'reason']='Available under practical historical reconstruction policy; per-record timing/scope/quality retained; not necessarily original-vintage PIT.'
        matrix.at[i,'accepted_rows']=len(g)
        matrix.at[i,'historical_reconstructed_rows']=len(g)
        matrix.at[i,'record_ids']=json.dumps(g.source_record_id.tolist())
        matrix.at[i,'earliest_accepted_available_at']=g.effective_available_at.min()
    frame(path,matrix)
    rows=[];specs={s['series_id']:s for s in specifications()}
    for sid,g in matrix.groupby('series_id'):
        s=specs[sid];struct=g.status.eq('STRUCTURAL_NA');good=g.status.eq('ACCEPTED')
        missing=g[~(struct|good)]
        rows.append(dict(domain='macro',indicator=sid,concept=s['concept_id'],
            group=s['series_group'],frequency=s['frequency'],unit=s['unit'],
            expected_periods=int((~struct).sum()),accepted_periods=int(good.sum()),
            structural_periods=int(struct.sum()),missing_periods=len(missing),
            first_missing=str(missing.period_end.min().date()) if len(missing) else None,
            last_missing=str(missing.period_end.max().date()) if len(missing) else None,
            status='DATA READY' if missing.empty else 'UNRESOLVED_REQUIRED_DATA',
            policy='historical_reconstructed; strict first-vintage certification is separate'))
    frame(ROOT/'data/metadata/macro_completeness.parquet',pd.DataFrame(rows))
    print('MACRO_REMAINING',matrix[~matrix.status.isin(['ACCEPTED','STRUCTURAL_NA'])].groupby('series_id').size().to_dict(),flush=True)


if __name__=='__main__':build()
