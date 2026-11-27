# MLEC 同伴交接 · Random Forest 和 Z*

把整个 ZIP 解压到短的可写路径，例如 `D:\RF`。Windows x64 使用 64 位 Python 3.11 和包内离线 wheels。Linux x64 使用 Python 3.11 与已配置的 PyPI 镜像。研究数据、Z* 重建源与模型源码随包提供，运行无需 E 盘。

1. 双击 CHECK_WINDOWS.cmd，或运行 bash CHECK_LINUX.sh。检查完整性、依赖、数据和运行配置。
2. 双击 TECHNICAL_WINDOWS.cmd，或运行 bash START_LINUX.sh --technical。复核正式执行器的小规模真实开发拟合，以及直接、条件和带噪宏观信号对照。
3. 双击 START_WINDOWS.cmd，或运行 bash START_LINUX.sh。一次启动完成 B、验证锁定、C、统计表和中文报告。中断后用同一命令续跑。

Windows PowerShell 可调用 .\\START_WINDOWS.cmd -CpuWorkers 4 -CpuThreads 1 -OutputRoot D:\\MLEC-results。Linux 启动器接受 --cpu-workers 4 --cpu-threads 1 --output-root /path/to/results。默认 2 个 worker 和每任务 1 个线程。调整 worker 数保持内容身份，改变线程数会生成新身份。可用 -RunId 或 --run-id 自定义名称。

正式预算上界为 33,288 个有监督的月度配置，含筛选、复核、未复用的所选开发与 C；分类单森林，回归七森林，折合最多 133,152 次森林拟合，另有朴素基准评分和失败重试。工作量、复用和选定树数会影响用时。若结果目录和归档同盘，以 70 GiB 空余作为磁盘预算上限参考。

## 成果与提交

正式输出在 `results/random_forest/<run_id>`，或所选输出目录。正式流程完成报告后会在同级写入 `<run_id>_results.zip` 及 SHA-256 回执。归档含逐周预测和损失、开发筛选与复核、锁参、表图、日志、环境及保留的月度模型。结果导出需要为归档另留磁盘空间。训练和续跑使用原运行目录。

结果目录已经完成时，可单独重算报告或重导归档。使用包内同一环境执行以下命令。

```powershell
python -m scripts.market_state.experiments summarize --model random_forest --run <run_dir> --stage test
python -m scripts.market_state.experiments export --model random_forest --run <run_dir>
```

从优化版交接提交创建独立结果分支，例如 `results/random-forest-final-optimization`。将中文报告、运行与环境清单、锁参、关键 CSV、导出回执与 ZIP SHA-256 保存至该分支后提交并推送。完整 ZIP 通过约定渠道交接，原结果及实现分支保留。

执行提示词见 launchers/random_forest/PEER_PROMPT.md。设计与限制见 docs/random_forest_zstar.md 和 docs/z_star.md。历史 C 的结论按历史复核报告。
