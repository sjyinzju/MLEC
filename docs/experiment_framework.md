# v5 数据与实验框架接口

唯一研究数据入口为 `scripts.final_data_foundation.research_inputs.load_dataset()`。实验框架仅作薄适配，不保存第二份研究数据，不重新生成标签、市场状态或时间折。

```python
from scripts.experiment_framework.dataset import feature_registry, load_dataset

sets = feature_registry(quality="historical_reconstructed")
cohort = sets["M_plus_Z_core"]["sample_version"]
z = load_dataset(cohort, "M_plus_Z_core", 20, "dev-2020", "train")
m = load_dataset(cohort, "M", 20, "dev-2020", "train")
assert m.metadata.sample_id.tolist() == z.metadata.sample_id.tolist()
assert m.y.equals(z.y)
```

`Dataset` 返回 `X`、`y`、样本元数据、特征顺序、逐系列可得时间、时间折与内容哈希。`X` 只包含冻结市场白名单和所选宏观列；标签及其成熟时间不进入特征。H5/H20/H40、combined/vol/drawdown 读取冻结目标，不重算阈值。

14 个注册特征集覆盖 M、原核心七变量、增长/价格/信用/利率/外部组、全部变量及核心删组。核心删组共享完整核心样本掩码；每个 M 与 M+Z 配对必须使用同一个 `sample_version`。完整组与制度前不适用序列按 v5 掩码处理，不能自行删掉缺数据的必需变量。

样本版本为 `v5:<quality>:<cohort>`，旧 `main_v1`、`common_core_v1` 不再接受。可选择 strict、conservative、quote_reconstructed、historical_reconstructed、latest_at_retrieval 五种质量视图。适配器默认 historical_reconstructed；底层通用入口默认 conservative，调用者应显式指定。历史重建不等于完整原始版本 PIT。

599 个候选时点全部保留在权威数据中；适配器仅返回资格掩码与冻结时间折交集。`eligible` 只要求最新合法观测满足契约，上一期和变化列可能为空；若需要所有转换齐全，显式设置 `require_complete_transforms=True`。没有隐式插值或填零。

适配器只开放 `dev-2020`、`dev-2021`、`dev-2022` 的 train/validation。训练标签必须在对应 cutoff 前成熟；宏观来源时钟不能晚于样本 asof；2023+ 保持隔离。模型方法和超参数配置未在本轮运行。既有正式结果及 `experiments/registry/latest.json` 仍指向旧冻结成果，不能解释为 v5 实验结果。

数据维护后依次运行：

```powershell
python -m scripts.final_data_foundation.practical_readiness
python -m scripts.final_data_foundation.research_inputs
python -m scripts.final_data_foundation.completion_status
python -m scripts.final_data_foundation.practical_validate
python -m scripts.final_data_foundation.final_delivery
python -m scripts.experiment_framework.validate_interface
python -m pytest -q -p no:cacheprovider tests/experiment_framework/test_v5_data_interface.py
python -m scripts.final_data_foundation.final_report
```

这些命令不训练模型或生成预测。完整检查和接口结果分别写入 `data/metadata/final_validation.json` 与 `experiment_interface_validation.json`；它们的 PASS 不会覆盖 `remaining_gaps.json` 的 UNRESOLVED 数据状态。`build-dataset` 只更新框架绑定和特征注册表；旧 `govern-macro` 写入入口已禁用。

维护代码按缺口使用 `scripts/final_data_foundation/` 的定向修复器。2014 深交所、官方中证1000、PB、IPO自由流通股、存托凭证单位和价格修复均保留精简数值父记录。已删除的原始响应或中间表不属于当前读取依赖。

PB的发行人复核先调用`pb_alternative_repair.apply()`，再调用`pb_issuer_repair.apply_remaining()`；不要仅为重应用已有父值重新运行下载收集器。追加限售和分立上市自由流通量分别由`restricted_share_repair`、`demerger_free_share_repair`维护。4条更正财报PB仅为历史重建，其后置可得时间不允许进入早于更正披露的预测特征。
