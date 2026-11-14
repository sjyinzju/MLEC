"""Inventory before migration; protect historical data and model artifacts."""
import os
import shutil
import subprocess
from pathlib import Path
import pyarrow.parquet as pq
from .common import ROOT,AUDIT,digest,read_json,write_json,now,local

SKIP={'.git','__pycache__','.pytest_cache','matplotlib_cache'}

def inventory():
    path=AUDIT/'baseline.json'
    if path.exists():return read_json(path)
    tracked=set(subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode('utf-8').split('\0'))
    files=[]
    for folder,dirs,names in os.walk(ROOT):
        dirs[:]=[d for d in dirs if d not in SKIP]
        for name in names:
            p=Path(folder)/name;rel=p.relative_to(ROOT).as_posix()
            if rel.startswith('audit/data_foundation_v3/'):continue
            row={'path':rel,'bytes':p.stat().st_size,'tracked':rel in tracked}
            if rel.startswith('.local_deps/'):
                row['kind']='local_runtime_not_research_data'
            else:row['sha256']=digest(p)
            if p.suffix=='.parquet':
                q=pq.ParquetFile(p);row.update(rows=q.metadata.num_rows,schema=str(q.schema_arrow))
            row['protected']=rel.startswith(('data/research_v2/','config/research_v2/','audit/research_v2/','reports/research_v2/','experiments/','artifacts/models/','reports/benchmark/','data/standardized/macro/','data/datasets/','data/features/','data/raw/macro/','config/experiments/'))
            files.append(row)
    result={'created_at':now(),'root':str(ROOT),'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip(),
        'branch':subprocess.check_output(['git','branch','--show-current'],cwd=ROOT).decode().strip(),
        'initial_user_worktree':'clean, observed before creating v3 implementation',
        'status_at_inventory':subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).decode('utf-8'),
        'disk_free_bytes':{drive:shutil.disk_usage(drive).free for drive in ['C:/','D:/','E:/'] if Path(drive).exists()},
        'files':files,'scope':'data-only; historical experiments protected and not read for variable selection'}
    write_json(path,result)
    print('Inventory:',len(files),'files;',sum(x['bytes'] for x in files),'bytes',flush=True)
    return result

def migrate():
    baseline=inventory();by_path={r['path']:r for r in baseline['files']};moves=[]
    prior=read_json(AUDIT/'migration_manifest.json') if (AUDIT/'migration_manifest.json').exists() else {}
    prior_moves={x['old_path']:x for x in prior.get('files',[])}
    for row in baseline['files']:
        rel=row['path'];destination=None
        if '/' not in rel and rel.endswith('.docx'):destination='docs/research_design/'+rel
        elif rel.startswith('datacodes_lec3/'):
            # Course material is a self-contained teaching example, not research input.
            suffix=rel.removeprefix('datacodes_lec3/datacodes_lec3/').removeprefix('datacodes_lec3/')
            destination=('data/archive/course_examples/lecture03/' if Path(rel).suffix.lower() in ['.rdata','.csv','.parquet','.xlsx','.xls'] else 'docs/course/lecture03/')+suffix
        elif rel.startswith('deliverables/'):
            destination='docs/archive/legacy_deliverables_pointers/'+rel.removeprefix('deliverables/')
        if not destination:continue
        src=local(rel);dst=local(destination);dst.parent.mkdir(parents=True,exist_ok=True)
        if not dst.exists():shutil.copy2(src,dst)
        expected=prior_moves.get(rel,{}).get('new_sha256',row['sha256'])
        if digest(dst)!=expected:raise ValueError('Different destination content: '+destination)
        if src.exists():
            if digest(src)!=row['sha256']:raise ValueError('Source changed: '+rel)
            src.unlink()  # individual verified file, never recursive deletion
        moves.append(prior_moves.get(rel,{'old_path':rel,'new_path':destination,'sha256':row['sha256'],'operation':'verified_copy_then_remove_original'}))
    # Preserve the byte-identical teaching script and repair its old macOS path
    # in the runnable documentation copy. This teaching model is never executed.
    for move in moves:
        if move['new_path']!='docs/course/lecture03/knn/knn_mixture.R' or move.get('new_sha256'):continue
        dst=local(move['new_path']);archive=local('docs/archive/course_original/knn_mixture.R');archive.parent.mkdir(parents=True,exist_ok=True)
        if not archive.exists():shutil.copy2(dst,archive)
        assert digest(archive)==move['sha256']
        text=dst.read_text(encoding='utf-8')
        original='load("/Users/hongliangzhang/Documents/MLEcon/Fall2026/datacodes/datacodes_lec3/knn/mixture.RData")'
        replacement='# Run from the MLEC repository root; teaching example only.\nload("data/archive/course_examples/lecture03/knn/mixture.RData")'
        assert original in text;dst.write_text(text.replace(original,replacement),encoding='utf-8')
        move.update(operation='verified_move_and_portable_path_update',original_archive=archive.relative_to(ROOT).as_posix(),new_sha256=digest(dst))
    empty=list(prior.get('empty_directories_removed',[]))
    for name in ['data_raw','deliverables','datacodes_lec3']:
        root=local(name)
        if not root.exists():continue
        for folder,dirs,files in os.walk(root,topdown=False):
            p=Path(folder).resolve()
            if p.is_relative_to(ROOT) and not any(p.iterdir()):p.rmdir();empty.append(p.relative_to(ROOT).as_posix())
    # Training must no longer read the research calendar from an audit folder.
    aliases=[]
    for name in ['sse_calendar.parquet','fold_manifest.parquet']:
        src=ROOT/'audit/research_v2'/name;dst=ROOT/'data/metadata/market'/name;dst.parent.mkdir(parents=True,exist_ok=True)
        if not dst.exists():shutil.copy2(src,dst)
        assert digest(src)==digest(dst)
        aliases.append({'source':src.relative_to(ROOT).as_posix(),'data_path':dst.relative_to(ROOT).as_posix(),'sha256':digest(dst),'reason':'New data-only pipeline authority; original audit snapshot retained for frozen compatibility'})
    documents=[]
    for original,archive in [('README.md','docs/archive/README_before_data_foundation_v3.md'),('docs/data_dictionary.md','docs/archive/data_dictionary_before_v3.md')]:
        p=local(archive)
        if p.exists():
            assert digest(p)==by_path[original]['sha256']
            documents.append({'original_path':original,'archive_path':archive,'sha256':digest(p),'operation':'byte_identical_original_preserved_before_v3_documentation_replacement'})
    write_json(AUDIT/'migration_manifest.json',{'files':moves,'empty_directories_removed':empty,'frozen_metadata_copies':aliases,'documentation_archives':documents})
    print('Migrated',len(moves),'files; removed',len(empty),'verified empty directories')

def verify_protected():
    baseline=inventory();checked=[]
    for r in baseline['files']:
        if r.get('protected'):
            checked.append({'path':r['path'],'unchanged':digest(ROOT/r['path'])==r['sha256']})
    write_json(AUDIT/'integrity_checks.json',{'checked_at':now(),'files':checked,'all_unchanged':all(x['unchanged'] for x in checked)})
    if not all(x['unchanged'] for x in checked):raise ValueError('Historical protected artifacts changed')
    return len(checked)
