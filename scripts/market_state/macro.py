"""Release-state as-of alignment, preserving scope and vintage metadata."""
import numpy as np
import pandas as pd
from .common import *
from scripts.final_data_foundation.macro_contract import specifications

def current_specifications():
    """Economic scope endpoints are distinct from an old inventory's last date."""
    specs=specifications()
    for s in specs:
        # The source contract's September 2026 inventory boundary is not an
        # economic discontinuation. Real ended TSF/M1 regimes stay bounded.
        if pd.Timestamp(s['required_end']).year>=2026:s['required_end']='2100-12-31'
        if s['series_id']=='m1_yoy':s['required_end']='2024-12-31'
    return specs

LEVELS={'strict':['strict_pit_eligible'],
 'historical_reconstructed':['strict_pit_eligible','conservative_release_reconstructed','historical_reconstructed'],
 'latest_at_retrieval':['strict_pit_eligible','conservative_release_reconstructed','historical_reconstructed','latest_vintage_reconstructed']}

def prepare(f,level='historical_reconstructed'):
    f=f.copy();f['effective_available_at']=f.research_available_at
    allowed=f.quality_status.isin(LEVELS[level])
    if level=='historical_reconstructed':
        quote=f.source_class.eq('third_party_historical_quote') & f.reconstructed_quote_at.notna()
        allowed|=quote;f.loc[quote,'effective_available_at']=f.loc[quote,'reconstructed_quote_at']
    f=f[allowed & f.certification_status.eq('ACCEPTED') & f.value.notna()].copy()
    f['quality_rank']=f.quality_status.map({'strict_pit_eligible':3,'conservative_release_reconstructed':2,'historical_reconstructed':1,'latest_vintage_reconstructed':0})
    return f.sort_values(['effective_available_at','publication_edition_order','quality_rank','source_record_id'])

def align(f,points,level='historical_reconstructed'):
    allowed=prepare(f,level);rows=[];lineage=[];specs=[s for s in current_specifications() if s.get('required',True)]
    for spec in specs:
        sid=spec['series_id'];g=allowed[allowed.series_id.eq(sid)&allowed.period_end.between(spec['required_start'],spec['required_end'])]
        timeline=g.to_dict('records');state={};cursor=0;sr=[]
        for point in points.itertuples(index=False):
            t=point.asof_time;date=point.asof_date;prefix='macro__'+sid+'__'
            while cursor<len(timeline) and timeline[cursor]['effective_available_at']<=t:
                rec=timeline[cursor];state[rec['period_end']]=rec;cursor+=1
            parents=[state[p] for p in sorted(state)];last=parents[-1] if parents else None;prev=parents[-2] if len(parents)>1 else None
            structural=date<pd.Timestamp(spec['required_start']) or date>pd.Timestamp(spec['required_end'])+pd.Timedelta(days=spec['max_staleness_days'])
            status='NOT_APPLICABLE' if structural else 'NO_RELEASE' if last is None else 'AVAILABLE'
            gap=bool(last and (date-last['period_end']).days>spec['max_staleness_days'])
            if status=='AVAILABLE' and gap:status='RELEASE_GAP_HELD_VALUE'
            valid=last is not None and not structural
            scope_break=bool(last and prev and last['statistical_scope_id']!=prev['statistical_scope_id'])
            reset=bool(last and prev and spec['measure_type']=='ytd_flow' and last['period_end'].year!=prev['period_end'].year)
            period_gap=bool(last and prev and (last['period_end']-prev['period_end']).days > (7 if spec['frequency']=='D' else 110 if spec['frequency']=='Q' else 65))
            change=last['value']-prev['value'] if valid and prev and not(scope_break or reset or period_gap) else np.nan
            row={'asof_date':date,prefix+'latest':last['value'] if valid else np.nan,prefix+'change':change,
                prefix+'age_days':(t-last['effective_available_at']).total_seconds()/86400 if valid else np.nan,
                prefix+'not_applicable':int(structural),prefix+'release_gap':int(gap and valid),prefix+'missing':int(not valid and not structural)}
            if spec['frequency']=='D':
                for h in [5,20]:
                    group=parents[-h-1:];comparable=len(group)==h+1 and len({p['statistical_scope_id'] for p in group})==1
                    row[prefix+f'change_{h}obs']=group[-1]['value']-group[0]['value'] if valid and comparable else np.nan
                    row[prefix+f'vol_{h}obs']=np.std(np.diff([p['value'] for p in group]),ddof=0) if valid and comparable else np.nan
            sr.append(row)
            lineage.append(dict(asof_date=date,asof_time=t,series_id=sid,series_group=spec['series_group'],status=status,
                source_record_id=last['source_record_id'] if valid else None,previous_record_id=prev['source_record_id'] if pd.notna(change) else None,
                available_at=last['effective_available_at'] if valid else pd.NaT,
                actual_vintage_available_at=last['research_available_at'] if valid else pd.NaT,
                statistical_scope_id=last['statistical_scope_id'] if valid else None,
                source_url=last['source_url'] if valid else None,quality=last['quality_status'] if valid else None,
                period_end=last['period_end'] if valid else pd.NaT,change_scope_break=scope_break,change_ytd_reset=reset,
                change_period_gap=period_gap,held_legal_release=valid,quality_view=level,
                daily_history_parent_ids=json.dumps([p['source_record_id'] for p in parents[-21:]]) if spec['frequency']=='D' and valid else None))
        rows.append(pd.DataFrame(sr).set_index('asof_date'))
    result=pd.concat(rows,axis=1).copy().reset_index()
    return result,pd.DataFrame(lineage),specs

def build_macro():
    f=pd.read_parquet(ROOT/'data/standardized/macro/v4/macro_facts.parquet')
    points=read('future_window_outcomes')[['asof_date','asof_time']].drop_duplicates().sort_values('asof_date')
    for quality in LEVELS:
        features,lineage,specs=align(f,points,quality)
        frame('macro/'+quality+'/features',features);frame('macro/'+quality+'/lineage',lineage)
        print('macro asof',quality,len(features),flush=True)
    write(OUT/'macro/specifications.json',specs)
