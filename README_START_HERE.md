# Elastic Net 优化版：同伴运行说明

本包包含分类、七目标回归的完整 B→新开发锁→C→评分/报告代码、统一接口和36项封版研究数据；不依赖 E:\QuantData。RBF-SVM保留公共接口兼容性，本包正式入口只运行Elastic Net。Random Forest、CatBoost仍未实现。

需要先安装 **64位 CPython 3.11**（启用PATH）。包不含Python解释器；`wheels/`提供Windows x64 Python3.11所需完整离线依赖。其他系统或Python版本需要联网安装相同锁定依赖，不能直接使用Windows wheels。

1. 完整解压到可写目录，先双击 **CHECK_WINDOWS.cmd**：自动建立独立`.venv`，优先离线安装，检查文件哈希、数据、环境和代码验收身份。**该入口不训练。**
2. 如需自行确认真实求解链路，双击 **TECHNICAL_WINDOWS.cmd**：明确授权少量真实拟合、模型保存加载和串并行一致性检查。它不执行正式完整B+C，临时预测/权重会清理。
3. 准备好耗时计算后，双击 **START_WINDOWS.cmd**：明确授权正式full实验，自动完成B的32候选粗筛、前4名全36月复核、验证新锁、C和报告。B与C之间无需再次确认。

短验证需要至少2个进程来比较执行方式。若可用内存不足导致自动选择1进程，它会在拟合前停止；先释放内存，再在终端运行 `TECHNICAL_WINDOWS.cmd --cpu-workers 2`。本次桌面已实际验证该命令通过。正式实验仍自动按资源选择进程，不应在内存紧张时盲目开满。

默认使用CPU，自动根据CPU/可用内存选择1..8个外层进程，每任务1线程，不使用GPU。指定资源/结果路径：

```cmd
START_WINDOWS.cmd -CpuWorkers 4 -CpuThreads 1 -OutputRoot "F:\MLEC_Results"
```

中断后保留原结果，再启动同一入口即可核验并复用成功任务。worker数可以改变；数据、线程、模型参数或实现身份改变时应新建运行。不要复制第一轮run_id、selection.lock.json或旧权重到新版结果中。新预处理和数值验收使旧锁失效。

若本优化版已在运行，需要增加进程：在原运行终端按一次Ctrl+C，等待Python工作进程结束，再用相同目录、输出位置、RunId和CpuThreads重新启动，只调整CpuWorkers。不要同时启动第二套实例或强删锁文件；已成功产物会校验复用，未完成任务按固定尝试预算恢复。第一轮旧实现需另开新版运行，不能跨实现身份续跑。

结果位于 `results/elastic_net/<run_id>/`。core只含M/M+Z，full另含96个固定参数分组配置；完整性和报告明确区分范围。不减少候选、月份或目标来提速。规模与预算可执行 `python -m scripts.market_state.experiments plan --suite full` 查看。技术小任务耗时不能直接当作整轮耗时承诺。

Linux先执行 `bash CHECK_LINUX.sh`（只检查，需要联网安装Linux依赖）；正式启动为 `bash START_LINUX.sh`，可追加 `--cpu-workers 4 --cpu-threads 1 --output-root /path/results`。

`package.manifest.json`列出交付全部文件的SHA256；原seal和研究产品不变。代码、接口、配置或成功产物被改动时会停止，不绕过版本检查。离线安装失败时检查Python是否为3.11 x64、目录可写及磁盘余量，保留错误信息后修复重试。

历史审计、数值修复、真实技术测试与性能/一致性结果见 `reports/model_build/elastic_net/optimization_20261119/technical_acceptance.md` 及同目录其他报告；下一轮命令见 `NEXT_EXPERIMENT.md`。本轮没有重跑正式完整B+C。2023年以后旧测试结果已查看，后续新版结果须披露为“已知实现问题修复后的复算”，不能称为首次未查看的独立测试。
