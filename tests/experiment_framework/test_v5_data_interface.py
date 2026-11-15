"""Data-only regressions: never import or fit a model."""
import sys
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'.local_deps'))
from scripts.final_data_foundation.research_inputs import make_weekly, load_dataset as authoritative
from scripts.experiment_framework.dataset import feature_registry, load_dataset, build_dataset
from scripts.experiment_framework.common import digest


def facts():
    return pd.DataFrame(dict(series_id=['cpi_yoy']*3,
        period_start=pd.to_datetime(['2019-11-01','2019-12-01','2019-11-01']),
        period_end=pd.to_datetime(['2019-11-30','2019-12-31','2019-11-30']),
        research_available_at=pd.to_datetime(['2019-12-10','2020-01-10','2020-01-12']).tz_localize('Asia/Shanghai'),
        source_record_id=['a','b','c'],quality_status=['strict_pit_eligible']*3,
        certification_status=['ACCEPTED']*3,source_class=['dated_official_bulletin']*3,
        reconstructed_quote_at=[pd.NaT]*3,publication_edition_order=[0]*3,
        statistical_scope_id=['as_registered']*3,value=[1.,2.,99.]))


def samples(dates=('2020-01-11','2020-01-18')):
    return pd.DataFrame(dict(sample_id=[str(i) for i in range(len(dates))],
        asof_time=pd.to_datetime(list(dates)).tz_localize('Asia/Shanghai')))


def test_revision_truncation_and_future_perturbation():
    f=facts();s=samples();a,_=make_weekly(f,s,'strict')
    assert a.macro__cpi_yoy__latest.tolist()==[2.,2.]
    assert a.macro__cpi_yoy__previous.tolist()==[1.,99.]
    b,_=make_weekly(f[f.research_available_at<=s.asof_time.iloc[0]],s.iloc[:1],'strict')
    pd.testing.assert_frame_equal(a.iloc[:1],b)
    f.loc[2,'value']=-10000
    changed,_=make_weekly(f,s.iloc[:1],'strict')
    pd.testing.assert_frame_equal(b,changed)


def test_delay_quality_staleness_and_scope_break():
    f=facts();f.loc[1,'research_available_at']=pd.Timestamp('2020-01-15',tz='Asia/Shanghai')
    d,_=make_weekly(f,samples(),'strict');assert d.macro__cpi_yoy__latest.tolist()==[1.,2.]
    f=facts();f['quality_status']='latest_vintage_reconstructed'
    d,_=make_weekly(f,samples(),'strict');assert d.filter(like='macro__').isna().all().all()
    d,_=make_weekly(facts(),samples(['2021-01-01']),'strict');assert d.filter(like='macro__').isna().all().all()
    f=facts();f.loc[1,'statistical_scope_id']='new_scope'
    d,l=make_weekly(f,samples(),'strict')
    assert d.macro__cpi_yoy__previous.isna().all() and d.macro__cpi_yoy__change.isna().all()
    assert l[l.feature.eq('macro__cpi_yoy__change')].status.eq('STATISTICAL_SCOPE_BREAK').all()


def test_pmi_known_before_month_end():
    f=facts().iloc[:1].copy();f['series_id']='pmi_mfg'
    f['period_start']=pd.Timestamp('2022-01-01');f['period_end']=pd.Timestamp('2022-01-31')
    f['research_available_at']=pd.Timestamp('2022-01-28 23:59:59',tz='Asia/Shanghai')
    d,_=make_weekly(f,samples(['2022-01-29']),'strict')
    assert d.macro__pmi_mfg__latest.notna().all()


def test_registry_build_never_overwrites_data_authority():
    paths=[ROOT/'data/metadata/dataset_registry.json',ROOT/'data/metadata/schema_registry.json']
    before=[digest(p) for p in paths];sets=build_dataset()
    assert [digest(p) for p in paths]==before
    for name,spec in sets.items():
        if name.startswith('M_plus_Z_core_without_'):
            assert spec['sample_version']==sets['M_plus_Z_core']['sample_version']
            assert set(spec['series'])<set(sets['M_plus_Z_core']['series'])


@pytest.mark.parametrize('fold',['dev-2020','dev-2021','dev-2022'])
def test_real_pairing_and_frozen_fold_alignment(fold):
    spec=feature_registry()['M_plus_Z_core'];raw=authoritative(series=spec['cohort_series'],quality=spec['quality_version'])
    for role in ['train','validation']:
        m=load_dataset(spec['sample_version'],'M',20,fold,role)
        z=load_dataset(spec['sample_version'],'M_plus_Z_core',20,fold,role)
        pd.testing.assert_series_equal(m.y,z.y)
        pd.testing.assert_frame_equal(z.X[m.feature_names],m.X)
        assert m.metadata.sample_id.tolist()==z.metadata.sample_id.tolist()
        allowed=raw['eligibility'][raw['eligibility'].eligible].merge(raw['folds'].query('fold_id == @fold and role == @role'),on='sample_id')
        assert set(z.metadata.sample_id)==set(allowed.sample_id)
        assert z.metadata.asof_time.dt.year.lt(2023).all()
        assert not any(c.startswith('y_') for c in z.metadata)
        assert z.feature_availability.feature_available_at.notna().all()


def test_stricter_transform_mask_and_invalid_requests():
    spec=feature_registry()['M_plus_Z_core']
    a=load_dataset(spec['sample_version'],'M_plus_Z_core',20,'dev-2022','train')
    b=load_dataset(spec['sample_version'],'M_plus_Z_core',20,'dev-2022','train',require_complete_transforms=True)
    assert set(b.metadata.sample_id)<=set(a.metadata.sample_id)
    for version,feature,fold in [('main_v1','M','dev-2020'),(spec['sample_version'],'M','final-2023'),
                                 ('v5:historical_reconstructed:M','M_plus_Z_core','dev-2020')]:
        with pytest.raises(ValueError):load_dataset(version,feature,20,fold,'train')


def test_real_future_fact_perturbation():
    f=pd.read_parquet(ROOT/'data/standardized/macro/v4/macro_facts.parquet')
    s=samples(['2020-02-07 18:00:00']);a,_=make_weekly(f,s,'historical_reconstructed')
    future=f.research_available_at.gt(s.asof_time.iloc[0])
    # Quote reconstructions use their explicit quote clock instead of capture.
    quote=f.source_class.eq('third_party_historical_quote')&f.reconstructed_quote_at.notna()
    future.loc[quote]=f.loc[quote,'reconstructed_quote_at'].gt(s.asof_time.iloc[0])
    changed=f.copy();changed.loc[future,'value']=999999.
    b,_=make_weekly(changed,s,'historical_reconstructed')
    c,_=make_weekly(f[~future],s,'historical_reconstructed')
    pd.testing.assert_frame_equal(a,b);pd.testing.assert_frame_equal(a,c)


def test_macro_semantic_regressions():
    f=pd.read_parquet(ROOT/'data/standardized/macro/v4/macro_facts.parquet')
    accepted=f[f.certification_status.eq('ACCEPTED')]
    assert accepted.source_record_id.is_unique
    assert accepted.source_url.notna().all()
    for sid,value in [('industrial_va_yoy',-2.9),('industrial_va_ytd_yoy',4.),('retail_sales_yoy',-11.1),('retail_sales_ytd_yoy',-.2)]:
        p=accepted[accepted.series_id.eq(sid)&accepted.period_end.eq('2022-04-30')]
        assert len(p) and np.allclose(p.value,value)
    assert not accepted[accepted.series_id.eq('m1_yoy')].period_end.ge('2025-01-01').any()
