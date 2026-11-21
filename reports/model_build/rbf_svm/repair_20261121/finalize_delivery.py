"""Create delivery evidence from actual receipts; never edits pytest receipts."""
from pathlib import Path
import argparse,json,hashlib,shutil,subprocess,zipfile,sys
ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from scripts.market_state.experiments.runtime import experiment_code_hash
from scripts.market_state.experiments.portable import validate_source_receipt


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf8'))
def write(p,value):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


def main(package):
    package=Path(package).resolve();evidence=ROOT/'reports/model_build/rbf_svm/repair_20261121'
    relative=evidence.relative_to(ROOT);delivered=package/relative;delivered.mkdir(parents=True,exist_ok=True)
    code=experiment_code_hash();tests_path=ROOT/'reports/market_state/model_io/test_results.json'
    tests=read(tests_path);validate_source_receipt(tests)
    assert sha(tests_path)==sha(package/tests_path.relative_to(ROOT))
    before=read(evidence/'reproduction_before.json');after=read(evidence/'reproduction_after.json')
    assert len(before['rows'])==len(after['rows'])==3
    assert after['calibration_source_sha256']==sha(ROOT/'scripts/market_state/models/calibration.py')
    source=read(evidence/'source_technical.json');desktop=read(package/'runtime_acceptance/technical.json')
    entries=read(package/'runtime_acceptance/entrypoints.json');subset=read(package/'runtime_acceptance/portable_pytest.json')
    atomic=read(evidence/'atomic_probe.json')
    assert source['status']==desktop['status']==entries['status']=='PASSED'
    assert source['code']==desktop['code']==entries['identity']['code']==subset['experiment_code_hash']==code
    assert entries['source_receipt_unchanged'] and not entries['formal_BC_started']
    assert subset['exit_code']==0 and subset['collected']==subset['passed'] and subset['receipt_kind']=='PORTABLE_SUBSET'
    assert all(atomic['success']) and not atomic['overlaps']
    numerical=[]
    for a,b in zip(before['rows'],after['rows']):
        assert a['status']=='FAILED' and b['status']=='PASSED'
        assert all(a[k]==b[k] for k in ['score_hash','label_hash','class_counts','calibration_plan'])
        assert len(b['independent_decimal'])==3 and all(q['negligible_descent'] for q in b['independent_decimal'])
        assert b['probabilities']['finite'] and b['probabilities']['normalization_error']<1e-12
        for technical in [source,desktop]:
            assert not technical['formal_BC_started']
            assert technical['candidate_ranking_equal'] and technical['process_recovery']['status']=='PASSED'
            for scope in ['serial','parallel']:
                checks=technical[scope]['checks'];match=[c for c in checks if c['fold_id']==b['design']['fold']]
                assert len(match)==1 and match[0]['kernel']['oof']['score_hash']==b['score_hash']
                assert match[0]['kernel']['oof']['label_hash']==b['label_hash']
        numerical.append(dict(fold=b['design']['fold'],class_counts=b['class_counts'],OOF_unchanged=True,
            independent_decimal=b['independent_decimal'],probabilities=b['probabilities']))
    seal=ROOT/'data/market_state/release/seal.json'
    assert sha(seal)=='728d7adb6305f4951281c800c16508aa3fa1565e52dfbfd7e96f655100acce8f'
    assert sha(seal)==sha(package/'data/market_state/release/seal.json')
    macro=read(package/'macro_contract_identity.json')
    assert macro['feature_count']==73 and macro['required_count']==69
    branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()
    for name,relative_source in [('desktop_entrypoints.json','entrypoints.json'),('desktop_portable_pytest.json','portable_pytest.json'),
            ('desktop_technical.json','technical.json'),('desktop_preflight.json','preflight.json')]:
        shutil.copy2(package/'runtime_acceptance'/relative_source,evidence/name)
    for log in (package/'runtime_acceptance').glob('*.log'):
        shutil.copy2(log,evidence/('desktop_'+log.name))
    result=dict(status='READY_FOR_FORMAL_BC',ready_for_formal_BC=True,experiment_code_hash=code,
        local_branch=branch,local_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        source_state='Existing concurrent uncommitted changes preserved; content identity is authoritative',github_pushed=False,
        source_full_pytest=dict(receipt_kind=tests['receipt_kind'],collected=tests['collected'],passed=tests['passed'],exit_code=tests['exit_code'],sha256=sha(tests_path)),
        portable_pytest=dict(receipt_kind=subset['receipt_kind'],collected=subset['collected'],passed=subset['passed'],exit_code=subset['exit_code']),
        calibration_version='svm-time-sigmoid-v3',numerical_validation=numerical,
        source_technical=dict(serial_monthly_tasks=source['serial']['successful_monthly_tasks'],parallel_monthly_tasks=source['parallel']['successful_monthly_tasks'],
            serial_estimator_fits=source['serial']['estimator_fit_calls'],parallel_estimator_fits=source['parallel']['estimator_fit_calls'],
            serial_sigmoids=source['serial']['calibration_fit_calls'],parallel_sigmoids=source['parallel']['calibration_fit_calls'],
            prediction_max_differences=source['prediction_max_differences'],recovery=source['process_recovery']),
        desktop_technical=dict(prediction_max_differences=desktop['prediction_max_differences'],recovery=desktop['process_recovery']),
        windows_atomic=dict(commits=atomic['critical_sections'],overlapping_write_sections=len(atomic['overlaps']),recovered_native_errors=len(atomic['recovered_native_errors'])),
        desktop_entrypoints=entries,original_seal_sha256=sha(seal),macro_contract=macro,
        desktop_package=str(package),archive=str(package.with_suffix('.zip')),formal_BC_executed=False,
        new_default_run_id=read(evidence/'new_run_identity.json')['run_id'],
        original_version_audit=read(evidence/'original_version_audit.json'),
        original_failed_run='3528aa385663201452585480',old_delivery_modified=False,first_model_results_modified=False,
        original_run_evidence_scope='Supplied failure snapshots and diagnosis; full original run directory was not found locally',
        limitations=['START verified through actual .cmd with -PlanOnly; full B/C deliberately not executed',
            'Local float64 numerical evidence is not a rigorous global certificate',
            'Exact external process behind historical WinError 5 cannot be identified from supplied snapshots',
            'Linux training not executed; predictions need not improve'])
    write(evidence/'delivery_report.json',result)
    text=f'''# RBF-SVM 修复与交付验收（2026-11-21）

结论：**READY_FOR_FORMAL_BC**。正式完整 B＋C 执行次数为 0；未 push GitHub，未改第一模型结果。

源码目录：`{ROOT}`。本地分支：`{branch}`。保留原有未提交的公共/Elastic Net 工作；最终身份以内容哈希为准。

实验代码哈希：`{code}`。校准身份：`svm-time-sigmoid-v3`。原 seal：`{sha(seal)}`，保持不变。

原始问题与根因：旧验收以求和交叉熵的绝对梯度 1e-8 单独决定最优性。三个真实任务在旧代码下全部失败；同一 OOF 在新代码下全部通过，九个 sigmoid 的 60 位 Decimal 梯度、Hessian 与完整 Newton 步复核均无可分辨改善。类支持分别为 [6,280,8]、[6,302,8]、[6,326,8]。这不是“1e-8 永远不可达”的数学结论；原补丁把精度估计称为证明的表述被拒绝。新增弱曲率方向负向控制与明显未收敛控制，仍拒绝。

原补丁处理：直接应用校准补丁的适用部分，保留曲率/目标分辨率诊断，改为必须同时满足 Hessian 全谱、弱方向梯度、Newton decrement 和稳定方向下降检查，保留原目标与截距基线。拒绝只扩大阈值作为证书。沿用有限退避的意图，拒绝重试所有 OSError，改为窄 Windows 共享/访问探测、唯一同卷临时文件、同目标跨进程互斥和异常传播。沿用 Linux CHECK 文件并映射至 RBF 包根。拒绝封版 JSON macro facade，打包真实 macro_contract 和必要声明依赖。

Windows 验证：4 个真实 spawn 写进程完成 {atomic['critical_sections']} 次同目标提交，临界区无重叠，捕获并恢复 {len(atomic['recovered_native_errors'])} 次原生暂时访问失败。完整 pytest 还覆盖同目标 JSON/Parquet 竞争、真实 Win32 占用、只读永久拒绝一次失败和磁盘不足一次失败。历史 WinError 5 的具体外部占用进程无法从补丁快照确定，不能将其归因于特定杀毒软件。微软说明 WinError 5 可与前一次删除中的文件状态有关：https://learn.microsoft.com/en-us/windows/apps/develop/files/best-practices-writing-files 。

源码完整、未过滤 pytest：**{tests['passed']} passed / exit {tests['exit_code']}**，由真实测试钩子生成 SOURCE_FULL_PYTEST，未编辑测试回执。便携默认 pytest：**{subset['passed']} passed / exit {subset['exit_code']}**，只代表 PORTABLE_SUBSET，不冒充源码全套。正式 preflight 继续核对当前代码、完整源码证明、测试源码身份和原 seal。

真实技术验收：源码和桌面各执行 6 个代表性任务的串行/Windows spawn 对比，包括原失败 3 个、正常分类 2 个候选、七目标回归 1 个。源码每组真实估计器 fit {source['serial']['estimator_fit_calls']} 次、sigmoid {source['serial']['calibration_fit_calls']} 次。预测、损失、非平凡候选排名、模型身份、OOF 计划、保存加载精确复现、重复启动复用全部通过；串并行预测最大差：{source['prediction_max_differences']}。额外 OS 终止恢复：真实分类提交后在下一回归 RUNNING 边界终止子进程，已完成分类不重拟合，回归恢复成功；中断期间计数保留 unknown。

便携根因是代码变更后需要新源码测试证明，而旧包缺少原始构建资产。现在在完整源码工作区签发证明并原样复制；便携另设范围，新增检查记录写 runtime_acceptance，不改变随包封存证明。真实宏观定义共 {macro['base_count']} 个 base、73 个 feature，其中 69 个 required 与原封版 JSON 逐值逐序一致，无重复追加，其余四个仍为原隔离候选。

桌面独立目录：`{package}`。默认入口建立全新的包内 venv，使用离线 wheels，清空 PYTHONPATH/PYTHONHOME，实际导入根为交付目录。CHECK_WINDOWS.cmd、TECHNICAL_WINDOWS.cmd 和 START_WINDOWS.cmd 均实际调用；START 使用 -PlanOnly，未执行正式训练。正式同伴运行用 START_WINDOWS.cmd -CpuWorkers 4。新身份启动新 run_id，不混入 3528aa385663201452585480 的任务、权重、失败记录或锁。

原优化包保持完整；本地未找到完整失败 run 目录，补丁所附原失败记录、诊断及原始 diff 均保留为证据。当前交付不依赖 E 盘原始湖。剩余限制：本轮不提供正式 B/C 成绩、耗时保证或预测提升保证；少数类别稀疏、多类校准局限及宏观历史可得性限制仍在；未实测 Linux 训练。

逐文件 SHA256 见 package.manifest.json 与 SHA256SUMS.txt；它们覆盖静态交付与验收快照，排除运行时生成的 venv、缓存、后续结果。ZIP 信息及最终 SHA256 另存同名 .zip.sha256 和桌面 delivery.json，避免压缩包对自身哈希的循环依赖。
'''
    (evidence/'delivery_report.md').write_text(text,encoding='utf8')
    old_acceptance=ROOT/'reports/model_build/rbf_svm/acceptance.json'
    historic=evidence/'historical_acceptance_20261120.json'
    if not historic.exists():shutil.copy2(old_acceptance,historic)
    write(old_acceptance,dict(status=result['status'],ready_for_formal_BC=True,experiment_code_hash=code,
        source_tests_sha256=sha(tests_path),technical_report='repair_20261121/source_technical.json',
        delivery_report='repair_20261121/delivery_report.json',formal_BC_executed=False))
    files_to_copy=[p for p in evidence.iterdir() if p.is_file() and p.suffix in ['.json','.md','.log']]
    files_to_copy += list((evidence/'patch_evidence').rglob('*'))
    files_to_copy += [old_acceptance]
    manifest_path=package/'package.manifest.json';manifest=read(manifest_path)
    for path in files_to_copy:
        if not path.is_file():continue
        target=package/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target);manifest['files'][target.relative_to(package).as_posix()]=sha(target)
    manifest['delivery_status']='READY_FOR_FORMAL_BC'
    write(manifest_path,manifest)
    checks=dict(manifest['files']);checks['package.manifest.json']=sha(manifest_path)
    for relative,expected in checks.items():assert sha(package/relative)==expected
    sums=package/'SHA256SUMS.txt'
    sums.write_text(''.join(f'{value}  {name}\n' for name,value in sorted(checks.items())),encoding='utf8')
    archive=package.with_suffix('.zip')
    if archive.exists():raise FileExistsError(archive)
    names=sorted([*checks,'SHA256SUMS.txt'])
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name in names:z.write(package/name,package.name+'/'+name)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name in names:assert hashlib.sha256(z.read(package.name+'/'+name)).hexdigest()==sha(package/name)
    archive_hash=sha(archive)
    archive.with_suffix('.zip.sha256').write_text(archive_hash+'  '+archive.name+'\n',encoding='ascii')
    final=dict(status='READY_FOR_FORMAL_BC',experiment_code_hash=code,package=str(package),
        package_static_files=len(checks),package_static_bytes=sum((package/n).stat().st_size for n in names),
        package_total_bytes_including_local_venv=sum(p.stat().st_size for p in package.rglob('*') if p.is_file()),
        archive=str(archive),archive_bytes=archive.stat().st_size,archive_sha256=archive_hash,
        every_archive_file_sha256_verified=True,source_test_receipt_unchanged=sha(tests_path)==sha(package/tests_path.relative_to(ROOT)))
    write(evidence/'archive_delivery.json',final)
    write(package.with_suffix('.delivery.json'),final)
    print(json.dumps(final,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('package');main(**vars(parser.parse_args()))
