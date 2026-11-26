# MLEC 同伴交接 · Random Forest 和 Z*

把整个 ZIP 解压到可写目录。Windows x64 使用 64 位 Python 3.11 和包内离线 wheels。Linux x64 使用 Python 3.11 与已配置的 PyPI 镜像。研究数据、Z* 重建源与模型源码随包提供。

1. 双击 CHECK_WINDOWS.cmd，或运行 bash CHECK_LINUX.sh。检查完整性、依赖、数据和运行配置。
2. 双击 TECHNICAL_WINDOWS.cmd，或运行 bash START_LINUX.sh --technical。复核单线程真实开发拟合和两组合成信号对照。
3. 双击 START_WINDOWS.cmd，或运行 bash START_LINUX.sh。一次启动完成 B、验证锁定、C、统计表和中文报告。中断后用同一命令续跑。

Windows PowerShell 可调用 .\\START_WINDOWS.cmd -CpuWorkers 4 -CpuThreads 1 -OutputRoot D:\\MLEC-results。Linux 启动器接受 --cpu-workers 4 --cpu-threads 1 --output-root /path/to/results。默认 2 个 worker 和每任务 1 个线程。调整 worker 数保持内容身份，改变线程数会生成新身份。可用 -RunId 或 --run-id 自定义名称。

## 成果与提交

正式输出在 results/random_forest/运行身份，或所选输出目录。保留整个 run 目录作为本地可复现资产，包含逐周预测和损失、B 候选、锁参、表图、日志、环境和模型。可用 python -m scripts.market_state.experiments summarize --model random_forest --run 路径 --stage test 重新导出表图及报告。

从交接提交建立关联结果分支 codex/random-forest-macro-enhanced-results，或在约定的实现分支追加。把中文 report.md、manifest.json、environment.json、selection.lock.json、关键结果 CSV 以及完整运行归档的 SHA-256 放入 reports/model_build/random_forest/formal_results，提交并推送。完整预测和权重随本地归档保留。使用 Git 仓库中的实现提交保存结果，不要把解包目录整体纳入 Git。

执行提示词见 launchers/random_forest/PEER_PROMPT.md。设计与限制见 docs/random_forest_zstar.md 和 docs/z_star.md。历史 C 的结论按历史复核报告。
