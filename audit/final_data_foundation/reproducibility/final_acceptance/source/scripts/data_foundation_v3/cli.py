"""Explicit data-only command surface. No experiment runner is imported."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

def main():
    p=argparse.ArgumentParser(description='MLEC data foundation v3 — data engineering only')
    p.add_argument('command',choices=['audit','migrate','collect','reconcile','standardize','validate','build-features','build-datasets','verify-lineage','register','report','reproduce'])
    p.add_argument('--source',choices=['nbs','nbs-directory','financial','pboc-legacy-tsf','pboc-attachments','safe-releases','credit-reprints','mofcom-history','snapshot-requests'],default='nbs')
    p.add_argument('--start-year',type=int,default=2014);p.add_argument('--end-year',type=int,default=2026)
    p.add_argument('--topics',default='固定资产投资,国民经济')
    p.add_argument('--quality',choices=['strict','conservative','latest_at_retrieval'],default='conservative')
    p.add_argument('--series');p.add_argument('--groups');p.add_argument('--name');p.add_argument('--all',action='store_true')
    a=p.parse_args()
    if a.command in ['audit','migrate']:
        from scripts.data_foundation_v3.audit import inventory,migrate
        (inventory if a.command=='audit' else migrate)()
    elif a.command=='collect':
        from scripts.data_foundation_v3.collect import nbs,nbs_directory,financial,pboc_legacy_tsf,pboc_attachments,safe_releases,manifest,credit_reprints,snapshot_requests,mofcom_history
        if a.source=='nbs':nbs(a.start_year,a.end_year,a.topics.split(','))
        elif a.source=='nbs-directory':
            nbs_directory();nbs_directory('https://www.stats.gov.cn/sj/xwfbh/fbhwd/')
        else:{'financial':financial,'pboc-legacy-tsf':pboc_legacy_tsf,'pboc-attachments':pboc_attachments,'safe-releases':safe_releases,'credit-reprints':credit_reprints,'mofcom-history':mofcom_history,'snapshot-requests':snapshot_requests}[a.source]()
        manifest()
    elif a.command=='standardize':
        from scripts.data_foundation_v3.standardize import build
        build()
    elif a.command=='reconcile':
        from scripts.data_foundation_v3.quality import reconcile,completeness
        reconcile();completeness()
    elif a.command=='build-features':
        from scripts.data_foundation_v3.features import build_features
        build_features()
    elif a.command=='build-datasets':
        from scripts.data_foundation_v3.features import all_datasets,build_datasets
        if a.all:all_datasets()
        else:print(build_datasets(a.quality,a.series.split(',') if a.series else None,a.groups.split(',') if a.groups else None,a.name))
    elif a.command=='register':
        from scripts.data_foundation_v3.quality import register
        register()
    elif a.command=='reproduce':
        from scripts.data_foundation_v3.reproduce import rebuild_and_compare
        result=rebuild_and_compare();print(result['status'],result['output_files_compared'],'output files compared')
    elif a.command in ['validate','verify-lineage']:
        from scripts.data_foundation_v3.validate import validate,lineage_check
        result=(validate if a.command=='validate' else lineage_check)()
        print({k:v for k,v in result.items() if k not in ['validated_output_hashes','causality']})
    else:
        from scripts.data_foundation_v3.report import build_reports
        build_reports()

if __name__=='__main__':main()
