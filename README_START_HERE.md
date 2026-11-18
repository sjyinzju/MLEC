# 同伴运行入口

这个包包含 Elastic Net 分类、七目标回归的完整 B→自动锁定→C→报告代码，以及该路径需要的全部封版数据。不需要访问 E:\QuantData，不需要补数据、改参数或拼结果表。其他三个模型家族尚未实现，不属于本包已完成范围。

## Windows：解压后双击 START_WINDOWS.cmd

需要已安装 **64 位 Python 3.11**（推荐版本，安装时启用 PATH）。首次安装依赖需要联网；本包不包含 Python 安装程序或离线依赖轮子。

1. 将压缩包完整解压至一个可写目录；不要在压缩软件内直接启动。
2. 双击 `START_WINDOWS.cmd`。
3. 脚本自动创建独立 `.venv`、安装锁定依赖，再启动完整 BC 实验。B 结束后自动核验并锁定参数，继续 C 和报告，无需中途确认。

**启动脚本会真实训练。** 包的制作与验收没有运行真实监督训练、smoke 或正式实验。

默认使用 CPU，每任务2线程，不需要显卡。核心为四市场×分类/回归×M/M+Z，另有12信息集固定参数分组；32候选粗搜索、前4候选全36月复核。完整实验计算量较大，请保持足够磁盘空间。

如需指定资源或结果盘，在包根目录终端执行：

```cmd
START_WINDOWS.cmd -CpuThreads 4 -OutputRoot "F:\MLEC_Results"
```

中断或报错后保留结果目录，修复环境后重新启动同一个脚本，会核验并复用已成功任务。请保持数据、研究配置和代码版本一致。

## Linux

需要 Python 3.11+、venv 模块及首次联网安装依赖的条件。从包根目录运行：

```bash
bash START_LINUX.sh
```

## 结果与完整性

默认结果在 `results/elastic_net/<run_id>/`，包括开发、测试、锁文件、逐周预测、损失、模型包、CSV/Markdown研究表、图和 `report.md`。具体入口、资源和恢复说明见 `docs/experiments.md`。

`package.manifest.json` 列出每个交付文件的 SHA256；原 `data/market_state/release/seal.json` 和36项研究产物保持原始内容。运行前会校验数据、接口、实验代码及成功测试身份，缺文件或版本不符即停止。

如果只需要检查环境和数据，在准备好依赖的 Python 环境中运行（不会训练）：

```bash
python -m scripts.market_state.experiments preflight
```

交付前已进行非训练测试和从压缩包解压目录启动的预检；这不代表真实求解器收敛或全量训练耗时已验证。
