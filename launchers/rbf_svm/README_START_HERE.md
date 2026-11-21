# RBF-SVM 独立运行包（2026-11-21）

交付验收结论见 reports/model_build/rbf_svm/repair_20261121/delivery_report.md。源码完整 pytest 的真实回执原样保存在 reports/market_state/model_io/test_results.json，不能编辑。该回执与当前运行代码一致，便携包无需重新构建原始研究数据。

需要 Windows x64 Python 3.11。双击入口会自动建立包内 .venv-rbf-svm，优先使用 wheels/ 离线安装锁定依赖。也可通过 -Python C:\环境\Scripts\python.exe 或 MLEC_PYTHON 指定合格环境。无需 E 盘原始数据湖，完整解压后运行。

- CHECK_WINDOWS.cmd：核对依赖、逐文件 SHA256、封版数据、源码完整测试证明和正式 preflight；不训练。
- TECHNICAL_WINDOWS.cmd -CpuWorkers 2：少量真实 SVC、七目标 SVR、三个 sigmoid、保存加载、Windows spawn、串并行评分排名及中断恢复；仅 SMOKE_ONLY，不启动正式研究。
- START_WINDOWS.cmd -CpuWorkers 4：由同伴决定执行完整 B→开发验证→参数锁→C→评分报告；本轮未执行正式 B＋C。
- START_WINDOWS.cmd -PlanOnly：只核对正式运行设计和入口，不训练。本次对 START 的实测使用此选项。

源码测试与便携测试分别记身份：tests/ 是源码参考，部分测试依赖未打包的采集资产；不要在便携包重发源码证明。包内默认 python -m pytest -q 仅运行 portable_tests/，生成独立 PORTABLE_SUBSET 回执。普通 pytest 禁止真实拟合；真实拟合仅通过 TECHNICAL 或 START 显式入口。

默认结果为 results/rbf_svm/<新run_id>/。可传 -OutputRoot F:\MLEC_Results。保持配置、代码与数据不变时可重复 START 恢复成功任务；请返还完整 run 目录。正式完成标志为 manifest.json 的 EXPERIMENT_COMPLETE。新代码和校准身份必须启动新 run，不得复用旧失败运行 3528aa385663201452585480 的任务、权重、参数锁或日志。

原始数据 seal、标签、信息集、超参数搜索范围及训练 OOF 成员保持不变。校准精度估计附带 Hessian、Newton 下降和独立高精度审计，不能作为严格全局数学证书。少数类别稀疏、逐类 sigmoid 归一化的多类校准局限和宏观历史可得性限制仍在；不保证预测成绩提升。正式 B/C 的耗时、磁盘需求和预测表现由同伴实际运行确定。

package.manifest.json 是逐文件 SHA256 清单。运行时新生成的 preflight、便携测试和技术验收记录在 runtime_acceptance/，不修改封存的源码证明和交付证据。提供 Linux CHECK/START 脚本，本轮 Windows 验收，未实测 Linux 训练。
