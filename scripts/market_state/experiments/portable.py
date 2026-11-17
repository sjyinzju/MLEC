"""Manifest-based portable research slice; never copies the raw lake or changes seal."""
from pathlib import Path
import shutil
import subprocess
from ..common import ROOT
from ..interface_acceptance import assert_interface_accepted
from ..release import sealed_product_path, file_hash
from .artifacts import read_json, atomic_json, staging, file_manifest, check_files
from .runtime import experiment_code_hash


def package(destination, store):
    assert_interface_accepted(data_root=store.root)
    tests = read_json(ROOT / 'reports/market_state/model_io/test_results.json')
    if tests.get('experiment_code_hash') != experiment_code_hash() or tests.get('exit_code') != 0:
        raise RuntimeError('Package requires current successful non-training experiment tests')
    destination = Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(store.root.resolve()):
        raise ValueError('Package destination must be new and outside the read-only data root')
    seal = read_json(store.root / 'release/seal.json')
    with staging(destination) as temporary:
        paths = [ROOT / 'requirements-research.txt', ROOT / 'requirements-experiments.txt', ROOT / 'README.md',
            ROOT / 'AGENTS.md']  # scripts is an existing PEP 420 namespace package
        paths += list((ROOT / 'scripts/market_state').rglob('*.py'))
        paths += list((ROOT / 'config/experiments').glob('*.yaml'))
        paths += list((ROOT / 'launchers').glob('run_elastic_net.*'))
        paths += [ROOT / 'docs' / p for p in ['MLEC_research_protocol.md', 'MLEC_experiment_plan.md',
            'model_io_contract.md', 'experiments.md']]
        paths += list((ROOT / 'reports/market_state/model_io').glob('*.json'))
        paths += [ROOT / 'reports/market_state/completion_report.md', ROOT / 'reports/market_state/model_io/implementation_report.md']
        for path in paths:
            if not path.is_file():
                raise RuntimeError('Missing required package source: ' + str(path))
            target = temporary / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
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
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
        manifest = dict(package_version='portable-experiment-v1', data_version=seal['data_version'],
            original_seal_hash=file_hash(target), experiment_code_hash=experiment_code_hash(),
            base_commit=commit.stdout.strip() if commit.returncode == 0 else None,
            source_state='content hashes are authoritative, including uncommitted implementation',
            data_root='data/market_state', raw_lake_required=False, supervised_fit_calls=0,
            files=file_manifest(temporary))
        check_files(temporary, manifest['files'])
        atomic_json(temporary / 'package.manifest.json', manifest)
    return destination
