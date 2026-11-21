# RBF-SVM 修复与交付验收（2026-11-21）

结论：**READY_FOR_FORMAL_BC**。正式完整 B＋C 执行次数为 0；未 push GitHub，未改第一模型结果。

源码目录：`D:\Desktop\学习\课程\大二上\经济学中的机器学习\MLEC`。本地分支：`fix/rbf-svm-calibration-portable-20261121`。保留原有未提交的公共/Elastic Net 工作；最终身份以内容哈希为准。

实验代码哈希：`e6e581a7110ab0d59c936ebf2686985a859ce1e6ebba9d3b082b75765ae6a7fe`。校准身份：`svm-time-sigmoid-v3`。原 seal：`728d7adb6305f4951281c800c16508aa3fa1565e52dfbfd7e96f655100acce8f`，保持不变。

原始问题与根因：旧验收以求和交叉熵的绝对梯度 1e-8 单独决定最优性。三个真实任务在旧代码下全部失败；同一 OOF 在新代码下全部通过，九个 sigmoid 的 60 位 Decimal 梯度、Hessian 与完整 Newton 步复核均无可分辨改善。类支持分别为 [6,280,8]、[6,302,8]、[6,326,8]。这不是“1e-8 永远不可达”的数学结论；原补丁把精度估计称为证明的表述被拒绝。新增弱曲率方向负向控制与明显未收敛控制，仍拒绝。

原补丁处理：直接应用校准补丁的适用部分，保留曲率/目标分辨率诊断，改为必须同时满足 Hessian 全谱、弱方向梯度、Newton decrement 和稳定方向下降检查，保留原目标与截距基线。拒绝只扩大阈值作为证书。沿用有限退避的意图，拒绝重试所有 OSError，改为窄 Windows 共享/访问探测、唯一同卷临时文件、同目标跨进程互斥和异常传播。沿用 Linux CHECK 文件并映射至 RBF 包根。拒绝封版 JSON macro facade，打包真实 macro_contract 和必要声明依赖。

Windows 验证：4 个真实 spawn 写进程完成 480 次同目标提交，临界区无重叠，捕获并恢复 25 次原生暂时访问失败。完整 pytest 还覆盖同目标 JSON/Parquet 竞争、真实 Win32 占用、只读永久拒绝一次失败和磁盘不足一次失败。历史 WinError 5 的具体外部占用进程无法从补丁快照确定，不能将其归因于特定杀毒软件。微软说明 WinError 5 可与前一次删除中的文件状态有关：https://learn.microsoft.com/en-us/windows/apps/develop/files/best-practices-writing-files 。

源码完整、未过滤 pytest：**190 passed / exit 0**，由真实测试钩子生成 SOURCE_FULL_PYTEST，未编辑测试回执。便携默认 pytest：**3 passed / exit 0**，只代表 PORTABLE_SUBSET，不冒充源码全套。正式 preflight 继续核对当前代码、完整源码证明、测试源码身份和原 seal。

真实技术验收：源码和桌面各执行 6 个代表性任务的串行/Windows spawn 对比，包括原失败 3 个、正常分类 2 个候选、七目标回归 1 个。源码每组真实估计器 fit 71 次、sigmoid 15 次。预测、损失、非平凡候选排名、模型身份、OOF 计划、保存加载精确复现、重复启动复用全部通过；串并行预测最大差：[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]。额外 OS 终止恢复：真实分类提交后在下一回归 RUNNING 边界终止子进程，已完成分类不重拟合，回归恢复成功；中断期间计数保留 unknown。

便携根因是代码变更后需要新源码测试证明，而旧包缺少原始构建资产。现在在完整源码工作区签发证明并原样复制；便携另设范围，新增检查记录写 runtime_acceptance，不改变随包封存证明。真实宏观定义共 65 个 base、73 个 feature，其中 69 个 required 与原封版 JSON 逐值逐序一致，无重复追加，其余四个仍为原隔离候选。

桌面独立目录：`D:\Desktop\MLEC_RBF_SVM_Optimized_20261121_e6e581a7`。默认入口建立全新的包内 venv，使用离线 wheels，清空 PYTHONPATH/PYTHONHOME，实际导入根为交付目录。CHECK_WINDOWS.cmd、TECHNICAL_WINDOWS.cmd 和 START_WINDOWS.cmd 均实际调用；START 使用 -PlanOnly，未执行正式训练。正式同伴运行用 START_WINDOWS.cmd -CpuWorkers 4。新身份启动新 run_id，不混入 3528aa385663201452585480 的任务、权重、失败记录或锁。

原优化包保持完整；本地未找到完整失败 run 目录，补丁所附原失败记录、诊断及原始 diff 均保留为证据。当前交付不依赖 E 盘原始湖。剩余限制：本轮不提供正式 B/C 成绩、耗时保证或预测提升保证；少数类别稀疏、多类校准局限及宏观历史可得性限制仍在；未实测 Linux 训练。

逐文件 SHA256 见 package.manifest.json 与 SHA256SUMS.txt；它们覆盖静态交付与验收快照，排除运行时生成的 venv、缓存、后续结果。ZIP 信息及最终 SHA256 另存同名 .zip.sha256 和桌面 delivery.json，避免压缩包对自身哈希的循环依赖。
