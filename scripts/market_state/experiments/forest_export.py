"""Export a completed formal Random Forest run without any supervised fitting."""
import json
import hashlib
from pathlib import Path
import shutil
from zipfile import ZIP_DEFLATED, ZipFile

from ..release import file_hash
from .artifacts import (_atomic_writer, _cleanup_temporary, _replace_with_retry, _temporary_file,
                        atomic_json, exclusive_run, native_path, read_json)


def export_forest_run(run, destination=None):
    root = native_path(run)
    manifest_path = root / 'manifest.json'
    if not manifest_path.is_file():
        raise ValueError('Select the completed run directory explicitly')
    archive = native_path(destination or root.with_name(root.name + '_results.zip'))
    if archive.suffix.lower() != '.zip' or archive.is_relative_to(root):
        raise ValueError('Choose a ZIP path outside the run directory')
    receipt_path = archive.with_suffix('.zip.json')
    with exclusive_run(root):
        manifest = read_json(manifest_path)
        if (manifest['model'] != 'random_forest' or manifest['purpose'] != 'RESEARCH'
                or not manifest['development_complete'] or not manifest['test_complete']):
            raise ValueError('Only completed formal Random Forest B+C can be exported')
        lock = file_hash(root / 'selection.lock.json')
        if not manifest['lock_hash'] or lock != manifest['lock_hash']:
            raise ValueError('Run selection lock is missing or has changed')
        reports = {}
        for stage in ('development', 'test'):
            path = root / stage / 'report_manifest.json'
            evidence = read_json(path)
            if (evidence['run_id'], evidence['purpose'], evidence['lock_hash']) != (
                    manifest['run_id'], 'RESEARCH', lock):
                raise ValueError('Stage report does not match the finished run and lock')
            reports[stage] = file_hash(path)
        identity = dict(run_id=manifest['run_id'], versions=manifest['versions'], selection_lock_sha256=lock,
                        report_manifest_sha256=reports)
        archive.parent.mkdir(parents=True, exist_ok=True)
        with _atomic_writer(archive):
            if archive.exists():
                if receipt_path.exists():
                    receipt = read_json(receipt_path)
                    if receipt['identity'] == identity and receipt['sha256'] == file_hash(archive):
                        return archive
                    raise FileExistsError('Existing export differs. Select a new explicit destination.')
                receipt = _recover_receipt(archive, root, identity)
            else:
                receipt = _write_archive(archive, root, identity)
        atomic_json(receipt_path, receipt)
    return archive


def _recover_receipt(archive, root, identity):
    """Resume if the process stopped between committing the ZIP and its sidecar."""
    with ZipFile(archive) as source:
        manifest_path = root.name + '/EXPORT_MANIFEST.json'
        record = json.loads(source.read(manifest_path))
        files = record['files']
        if (record['identity'] != identity or len(source.namelist()) != len(files) + 1
                or set(source.namelist()) != {*files, manifest_path}):
            raise FileExistsError('Existing export differs. Select a new explicit destination.')
        for name, expected in files.items():
            with source.open(name) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                    raise ValueError('Interrupted result export contains a changed file: ' + name)
    return dict(identity=identity, files=len(files), archive_bytes=archive.stat().st_size, sha256=file_hash(archive))


def _write_archive(archive, root, identity):
    files = []
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if path.is_file() and not any(x.startswith('.') for x in relative.parts) and not path.name.endswith('.partial'):
            files.append(path)
    size = sum(path.stat().st_size for path in files)
    if shutil.disk_usage(archive.parent).free < size + 32 * 1024 ** 2:
        raise OSError('Insufficient export space. The completed run remains available for export to another volume.')
    temp = _temporary_file(archive)
    try:
        index = {}
        with ZipFile(temp, 'w', compression=ZIP_DEFLATED, compresslevel=3, allowZip64=True) as output:
            for path in files:
                key = (Path(root.name) / path.relative_to(root)).as_posix()
                index[key] = file_hash(path)
                output.write(path, key)
            output.writestr(root.name + '/EXPORT_MANIFEST.json', json.dumps(
                dict(identity=identity, files=index, archive_scope='completed run with all committed fit artifacts and logs',
                     excluded=['temporary files and process leases']), indent=2, ensure_ascii=False))
        receipt = dict(identity=identity, files=len(files), archive_bytes=temp.stat().st_size, sha256=file_hash(temp))
        _replace_with_retry(temp, archive)
        return receipt
    finally:
        _cleanup_temporary(temp)
