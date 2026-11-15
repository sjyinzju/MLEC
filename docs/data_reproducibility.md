# MLEC 统一研究数据基础 unified-data-foundation-v4.0.0

**INCOMPLETE — DATA FOUNDATION NOT FULLY ACCEPTED**

本报告由实际交付数据和已执行验证生成。技术测试通过不等于全部数据已认证。原 market-research-v2.0.0 的样本、标签、状态定义和实验成果冻结。

在项目根目录使用现有Python环境执行：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
python -m scripts.final_data_foundation.offline --run-name user_reproduction_01
python -m scripts.final_data_foundation.validation
python -m scripts.final_data_foundation.issues
python -m scripts.final_data_foundation.reporting
```

`offline` 从保留raw重建供应商标准层、身份/停牌、证据修复、连续市场指标、宏观事实、时点视图和注册表，运行时禁用socket连接。它保留检查点并比较重建前后文件字节/完整逻辑行，结果在 `audit/final_data_foundation/reproducibility/`。继续运行会跳过已成功阶段；重新做一轮使用 `python -m scripts.final_data_foundation.offline --run-name 独立英文运行名` 创建新的检查点目录，不删除旧证据。

单纯重新下载不是复现。初次收集所用授权接口并不赋予历史原始版本认证。模型训练与预测命令不属于本流程。

配置读取示例：

```python
from scripts.final_data_foundation.research_inputs import load_dataset
result = load_dataset(groups=['growth', 'prices'], quality='conservative',
                      start='2015-01-05', end='2026-09-22', horizon=20,
                      label='combined', include_market_extensions=True)
# result: features, eligibility, targets, folds, selected_series, feature_lineage
# require_complete_transforms=True 可要求当前生效口径的四项变换全部非空
# 不删除不合格行；比较M与M+Z时须复用相同eligibility。
```

严格原始版本市场输入不可用，请求非注册市场策略会报错；不静默切换为重建。

最近完成的离线复现：PASS，比较360个产物。逐字段比较路径：`audit/final_data_foundation/reproducibility/final_acceptance/product_comparison.json`。示例运行名应在新重建时换成未使用名称，已完成名称仅继续检查点。旧失败记录及源代码快照保留，未通过放宽容差或忽略差异获得通过。
