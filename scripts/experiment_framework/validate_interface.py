"""Real-data interface, alignment and leakage checks. No models imported."""
import pandas as pd
from .common import ROOT, read_json, write_json, digest
from .dataset import build_dataset, feature_registry, load_dataset
from .audit import verify_market
from scripts.final_data_foundation import research_inputs as authority


def build():
    registry_path=ROOT/'data/metadata/dataset_registry.json'
    original=digest(registry_path)
    sets=build_dataset()
    assert digest(registry_path)==original
    rows=[]
    for name,spec in sets.items():
        for fold in ['dev-2020','dev-2021','dev-2022']:
            for role in ['train','validation']:
                data=load_dataset(spec['sample_version'],name,20,fold,role)
                market=load_dataset(spec['sample_version'],'M',20,fold,role)
                assert data.metadata.sample_id.is_unique
                assert data.metadata.sample_id.tolist()==market.metadata.sample_id.tolist()
                pd.testing.assert_series_equal(data.y,market.y)
                pd.testing.assert_frame_equal(data.X[market.feature_names],market.X)
                assert data.feature_names==spec['columns']
                assert not any(c.startswith('y_') or 'target' in c or 'label' in c for c in data.X)
                assert data.metadata.asof_time.dt.year.lt(2023).all()
                if role=='train':assert data.metadata.label_available_at.le(data.metadata.fit_cutoff).all()
                rows.append(dict(feature_set=name,quality=spec['quality_version'],fold=fold,role=role,
                    sample_version=spec['sample_version'],samples=len(data.y),features=len(data.feature_names),
                    paired_ids_labels_and_market_features=True))
        print('INTERFACE',name,flush=True)
    combinations=[]
    for quality in authority.LEVELS:
        spec=feature_registry(quality)['M_plus_Z_core']
        result=authority.load_dataset(series=spec['series'],quality=quality)
        assert len(result['features'])==len(result['eligibility'])==599
        for role in ['train','validation']:
            data=load_dataset(spec['sample_version'],'M_plus_Z_core',20,'dev-2022',role)
            allowed=set(result['eligibility'].loc[result['eligibility'].eligible,'sample_id'])
            assert set(data.metadata.sample_id)<=allowed
        combinations.append(dict(quality=quality,candidate_rows=599,eligible_h20=int(result['eligibility'].eligible.sum())))
    targets=pd.read_parquet(ROOT/'data/research_v2/prediction_targets_weekly.parquet')
    for horizon in [5,20,40]:
        for label in ['combined','vol','drawdown']:
            d=load_dataset(sets['M']['sample_version'],'M',horizon,'dev-2022','train',label=label)
            ref=targets[targets.horizon.eq(horizon)].set_index('sample_id').loc[d.metadata.sample_id,d.y.name]
            assert d.y.tolist()==ref.astype(int).tolist()
    for args in [('main_v1','M',20,'dev-2020','train'),(sets['M']['sample_version'],'M',20,'final-2023','train'),
                 (sets['M']['sample_version'],'M_plus_Z_core',20,'dev-2020','train')]:
        try:load_dataset(*args)
        except ValueError:pass
        else:raise AssertionError('Invalid or locked data request was accepted')
    frozen=verify_market()
    report=dict(status='INTERFACE_PASS',data_status=read_json(ROOT/'data/metadata/remaining_gaps.json')['status'],
        candidate_rows=599,paired_development_selections=rows,quality_combinations=combinations,
        horizon_label_checks=9,frozen_artifacts_verified=frozen,global_registry_unchanged=True,
        no_model_fitting=True,no_predictions=True,
        authority='scripts.final_data_foundation.research_inputs.load_dataset')
    write_json(ROOT/'data/metadata/experiment_interface_validation.json',report)
    print('INTERFACE_PASS',len(rows),'paired selections',frozen,'frozen hashes',flush=True)
    return report


if __name__=='__main__':build()
