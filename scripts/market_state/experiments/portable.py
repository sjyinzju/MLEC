"""Manifest-based portable research slice; never copies the raw lake or changes seal."""
from pathlib import Path
import shutil
import subprocess
from ..common import ROOT
from ..interface_acceptance import assert_interface_accepted
from ..release import sealed_product_path, file_hash
from .artifacts import read_json, atomic_json, staging, file_manifest, check_files
from .runtime import experiment_code_hash

MACRO_DEPENDENCIES = ['scripts/common.py','scripts/final_data_foundation/common.py','scripts/final_data_foundation/macro_contract.py',
    'scripts/data_foundation_v3/common.py',
    'scripts/data_foundation_v3/requirements.py','scripts/data_foundation_v3/scopes.py']


def validate_source_receipt(record):
    if record.get('receipt_kind')!='SOURCE_FULL_PYTEST' or record.get('exit_code')!=0 or record.get('experiment_code_hash')!=experiment_code_hash():
        raise RuntimeError('A current successful unfiltered SOURCE_FULL_PYTEST receipt is required')
    if not record.get('collected') or len(record.get('node_ids',[]))!=record['collected']:
        raise RuntimeError('Incomplete source test collection evidence')
    if record.get('passed')!=record['collected']:
        raise RuntimeError('Source full suite must pass every collected test')
    actual={p.relative_to(ROOT).as_posix():file_hash(p) for p in sorted((ROOT/'tests').glob('*.py'))}
    if record.get('test_files')!=actual:
        raise RuntimeError('Source test files differ from accepted full suite')


def package(destination, store, *, model='elastic_net', wheelhouse=None):
    from ..models import require_model
    require_model(model)
    forest = model == 'random_forest'
    if forest:
        from .config import load_config
        from .forest_technical import verify_forest_receipt
        assert_interface_accepted(data_root=store.root, feature_extension='z_star')
        verify_forest_receipt(load_config(ROOT / 'config/experiments/random_forest.yaml'), store)
    else:
        assert_interface_accepted(data_root=store.root)
    tests = read_json(ROOT / 'reports/market_state/model_io/test_results.json')
    validate_source_receipt(tests)
    destination = Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(store.root.resolve()):
        raise ValueError('Package destination must be new and outside the read-only data root')
    seal = read_json(store.root / 'release/seal.json')
    with staging(destination) as temporary:
        paths = [ROOT / 'requirements-research.txt', ROOT / 'requirements-experiments.txt', ROOT / 'pytest.ini', ROOT / 'README.md',
            ROOT / 'AGENTS.md', ROOT / 'README_START_HERE.md', ROOT / 'START_WINDOWS.cmd',
            ROOT / 'START_LINUX.sh']  # scripts is an existing PEP 420 namespace package
        if model == 'elastic_net':
            paths += [ROOT / name for name in ['CHECK_WINDOWS.cmd', 'CHECK_LINUX.sh', 'TECHNICAL_WINDOWS.cmd']]
        paths += list((ROOT / 'scripts/market_state').rglob('*.py'))
        paths += list((ROOT / 'config/experiments').glob('*.yaml'))
        paths += [p for p in (ROOT / 'launchers').rglob('*') if p.is_file() and p.suffix in ['.ps1', '.sh', '.cmd', '.md']]
        paths += list((ROOT / 'tests').glob('*.py'))
        paths += list((ROOT / 'portable_tests').glob('*.py'))
        paths += [ROOT / name for name in MACRO_DEPENDENCIES]
        paths += list((ROOT / 'reports/model_build' / model).glob('*.md'))
        paths += list((ROOT / 'reports/model_build' / model).glob('acceptance.json'))
        optimization = ROOT / 'reports/model_build' / model / ('optimization_20261120' if model=='rbf_svm' else 'optimization_20261119')
        if optimization.exists():
            paths += [p for p in optimization.glob('*') if p.suffix in ['.md', '.json']]
        repair = ROOT/'reports/model_build'/model/'repair_20261121'
        if repair.exists():
            paths += [p for p in repair.glob('*') if p.suffix in ['.md','.json']]
        paths += [ROOT / 'docs' / p for p in ['MLEC_research_protocol.md', 'MLEC_experiment_plan.md',
            'model_io_contract.md', 'experiments.md', 'rbf_svm.md', 'rbf_macro_learning_20261125.md']]
        if model == 'rbf_svm':
            macro_report = ROOT / 'reports/model_build/rbf_svm/macro_20261125'
            paths += [p for p in macro_report.glob('*') if p.suffix in ['.md', '.json']]
        if forest:
            paths += [ROOT / 'docs' / name for name in ['random_forest_zstar.md', 'z_star.md']]
            paths += list((ROOT / 'reports/model_build/random_forest').glob('*.json'))
            paths += list((ROOT / 'reports/model_build/random_forest').glob('*.csv'))
            paths += [p for p in (ROOT / 'reports/market_state/model_io/z_star').iterdir() if p.is_file()]
        paths += list((ROOT / 'reports/market_state/model_io').glob('*.json'))
        paths += [ROOT / 'reports/market_state/completion_report.md', ROOT / 'reports/market_state/model_io/implementation_report.md']
        for path in paths:
            if not path.is_file():
                raise RuntimeError('Missing required package source: ' + str(path))
            target = temporary / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        if wheelhouse is not None:
            wheels = sorted(Path(wheelhouse).glob('*.whl'))
            if not wheels:
                raise ValueError('Wheelhouse contains no wheels')
            (temporary / 'wheels').mkdir()
            for wheel in wheels:
                shutil.copy2(wheel, temporary / 'wheels' / wheel.name)
        if model == 'rbf_svm':
            for name in ['README_START_HERE.md', 'START_WINDOWS.cmd', 'START_LINUX.sh', 'CHECK_WINDOWS.cmd', 'CHECK_LINUX.sh', 'TECHNICAL_WINDOWS.cmd']:
                shutil.copy2(ROOT / 'launchers/rbf_svm' / name, temporary / name)
        if forest:
            for name in ['README_START_HERE.md', 'START_WINDOWS.cmd', 'START_LINUX.sh',
                         'CHECK_WINDOWS.cmd', 'CHECK_LINUX.sh', 'TECHNICAL_WINDOWS.cmd']:
                shutil.copy2(ROOT / 'launchers/random_forest' / name, temporary / name)
        (temporary/'pytest.ini').write_text('[pytest]\ntestpaths = portable_tests\n'
            'norecursedirs = tests results .venv-rbf-svm .venv-random-forest\n',encoding='utf8')
        (temporary/'SOURCE_TESTS_README.md').write_text('Source full pytest proof is copied unchanged from the source workspace.\n'
            'tests/ is source reference and may require omitted collection assets.\n'
            'Default pytest runs portable_tests/ only, produces PORTABLE_SUBSET evidence, and cannot reissue SOURCE_FULL_PYTEST.\n'
            'Real fitting requires the separate explicit TECHNICAL entry.\n',encoding='utf8')
        from scripts.final_data_foundation.macro_contract import specifications
        from ..macro import feature_specifications
        from ..common import digest
        base,features=specifications(),feature_specifications()
        sealed=read_json(store.root/'macro/specifications.json')
        required=[s for s in features if s.get('required',True)]
        if required!=sealed or len({s['series_id'] for s in features})!=len(features):
            raise RuntimeError('Real macro definitions differ from sealed feature specifications')
        atomic_json(temporary/'macro_contract_identity.json',dict(base_count=len(base),feature_count=len(features),
            base_digest=digest(base),feature_digest=digest(features),required_count=len(required),required_digest=digest(required)))
        for relative, sha in seal['products'].items():
            source = sealed_product_path(relative, store.root)
            if file_hash(source) != sha:
                raise RuntimeError('Sealed product changed during packaging: ' + relative)
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        target = temporary / 'data/market_state/release/seal.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(store.root / 'release/seal.json', target)
        if forest:
            from ..z_star_release import DIRECTORY, validate_extension
            overlay = validate_extension(store.root)
            for relative, sha in overlay['source_hashes'].items():
                source = (sealed_product_path(relative, store.root)
                    if relative.startswith('data/market_state/') else ROOT / relative)
                if not source.is_file() or file_hash(source) != sha:
                    raise RuntimeError('Z* rebuild source differs: ' + relative)
                target_source = temporary / relative
                target_source.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target_source)
            for relative in ('release/bse_factor_returns_20260923.parquet',
                             'release/bse_factor_returns_20260923.json', 'sources/trade_calendar.parquet'):
                reference = temporary / 'data/market_state' / relative
                reference.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(store.root / relative, reference)
            for name in [*overlay['products'], 'manifest.json']:
                source = store.root / DIRECTORY / name
                target_overlay = temporary / 'data/market_state' / DIRECTORY / name
                target_overlay.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target_overlay)
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
        manifest = dict(package_version='portable-experiment-v2', model=model, data_version=seal['data_version'],
            original_seal_hash=file_hash(target), experiment_code_hash=experiment_code_hash(),
            base_commit=commit.stdout.strip() if commit.returncode == 0 else None,
            **({'feature_extension': 'z_star', 'feature_version': overlay['feature_version']} if forest else {}),
            source_state='content hashes are authoritative, including uncommitted implementation',
            data_root='data/market_state', raw_lake_required=False, supervised_fit_calls=0, calibration_fit_calls=0,
            wheelhouse='wheels' if wheelhouse is not None else None,
            source_test_receipt_sha256=file_hash(temporary/'reports/market_state/model_io/test_results.json'),
            acceptance_scopes=dict(source='SOURCE_FULL_PYTEST',portable='PORTABLE_SUBSET plus explicit SMOKE_ONLY real technical'),
            files=file_manifest(temporary))
        check_files(temporary, manifest['files'])
        atomic_json(temporary / 'package.manifest.json', manifest)
    return destination


def verify_package(directory):
    directory = Path(directory).resolve()
    manifest = read_json(directory / 'package.manifest.json')
    check_files(directory, manifest['files'])
    receipt=directory/'reports/market_state/model_io/test_results.json'
    if manifest['source_test_receipt_sha256']!=file_hash(receipt):
        raise RuntimeError('Immutable source test proof changed')
    validate_source_receipt(read_json(receipt))
    if manifest['original_seal_hash'] != file_hash(directory / 'data/market_state/release/seal.json'):
        raise RuntimeError('Portable seal differs from manifest')
    print('PACKAGE_INTEGRITY_PASSED', len(manifest['files']), 'files; supervised fits=0')
    return manifest


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Verify a portable package, without training')
    parser.add_argument('--verify', type=Path, required=True)
    verify_package(parser.parse_args().verify)
