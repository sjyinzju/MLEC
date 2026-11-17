"""Atomic task journals and content-verified, version-specific fit reuse."""
from pathlib import Path
from contextlib import contextmanager
import json
import os
import shutil
import tempfile
import pandas as pd
from ..common import digest
from ..release import file_hash


def native_path(path):
    """Support Windows long temporary/output roots without changing stored identities."""
    path = Path(path).resolve()
    value = str(path)
    if os.name == 'nt' and not value.startswith('\\\\?\\'):
        value = '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
    return Path(value)


@contextmanager
def exclusive_run(root):
    """An OS lease is released on process exit; a stale filename is harmless."""
    root = native_path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.run.lock').open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('Another process is already operating this run') from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_json(path):
    return json.loads(native_path(path).read_text(encoding='utf8'))


def atomic_json(path, record):
    path = native_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.partial')
    temp.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str, allow_nan=False) + '\n', encoding='utf8')
    os.replace(temp, path)


def atomic_parquet(path, frame):
    path = native_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.partial')
    frame.to_parquet(temp, index=False, compression='zstd')
    os.replace(temp, path)


@contextmanager
def staging(destination):
    destination = native_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix='.partial-', dir=destination.parent))
    try:
        yield tmp
        if destination.exists():
            raise RuntimeError('Refusing to overwrite committed artifacts: ' + str(destination))
        os.replace(tmp, destination)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)  # only our just-created staging directory


def file_manifest(directory):
    return {p.relative_to(directory).as_posix(): file_hash(p)
        for p in sorted(Path(directory).rglob('*')) if p.is_file()}


def check_files(directory, files):
    directory = Path(directory).resolve()
    for relative, expected in files.items():
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or file_hash(path) != expected:
            raise RuntimeError('Missing/modified artifact: ' + str(path))


class TaskJournal:
    def __init__(self, run_root, *, resume, max_attempts):
        self.root = Path(run_root)
        self.resume, self.max_attempts = resume, max_attempts
        self.records = {}
        for path in self.root.glob('*/tasks/*.json'):
            record = read_json(path)
            self.records[record['task_id']] = record
        self.initial_ids = set(self.records)

    def path(self, task):
        return self.root / task['stage'] / 'tasks' / (task['task_id'] + '.json')

    def record(self, task, **fields):
        record = dict(task, **fields)
        atomic_json(self.path(task), record)
        self.records[task['task_id']] = record
        return record

    def succeeded(self, task):
        record = self.records.get(task['task_id'])
        if record is None:
            return None
        if record['identity'] != task['identity'] or record['fit_id'] != task['fit_id']:
            raise RuntimeError('Task identity collision')
        if not self.resume and task['task_id'] in self.initial_ids:
            raise RuntimeError('Existing task requires --resume')
        if record['status'] == 'SUCCEEDED':
            check_files(self.root / record['artifact'], record['files'])
            return record
        return None

    def snapshot(self):
        rows = []
        for record in self.records.values():
            row = {k: v for k, v in record.items() if k not in ['identity', 'files', 'diagnostics', 'attempt_history']}
            row['identity_json'] = json.dumps(record['identity'], sort_keys=True)
            row['attempt_history_json'] = json.dumps(record.get('attempt_history', []), sort_keys=True)
            rows.append(row)
        atomic_parquet(self.root / 'tasks.parquet', pd.DataFrame(rows))
        failures = [{k: r.get(k) for k in ['task_id', 'stage', 'status', 'error', 'attempts']}
            for r in self.records.values() if r['status'] == 'FAILED']
        atomic_json(self.root / 'logs/failures.json', failures)
