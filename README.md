# MLEC：未来20个交易日的多维市场状态

研究内容以 [新版协议](docs/MLEC_research_protocol.md) 为唯一依据。本轮完成数据处理、监督标签准备与统一研究接口；尚未运行监督预测实验。

**先读 [A—C 集中执行报告](reports/market_state/completion_report.md)**：包含实际覆盖、缺口、状态字典、清理遗留项、复算与测试结果。报告明确区分已执行产物与未完成的数据认证/清理事项。

## 唯一入口

```powershell
$env:PYTHONPATH='.local_deps'  # 常规安装依赖时无需此行
python -m scripts.market_state.run collect  # 定向补缺，需要网络
python -m scripts.market_state.run build    # 实际重建四市场、五维标签、GMM、宏观、时间折
python -m scripts.market_state.run verify
python -m pytest -q
```

标准依赖见 `requirements-research.txt`；来源库的附加依赖见 `requirements-data-v4.txt`。`--reuse-dictionary` 可使用已固定字典重建视图；`--force-sources` 强制刷新紧凑股票缓存。

```python
from scripts.market_state.framework import load_dataset, preprocessing
d = load_dataset(market_id='000985.SH', information_set='M+Z',
                 task='regression', fold_id='2023-01', role='train')
# d.X / d.y / d.metadata；task 还支持 classification 和 probability。
# preprocessing() 返回未拟合接口；必须仅在对应训练折内拟合。
```

## 目录与契约

- `scripts/market_state/`：唯一研究实现，前后向窗口共用 `measure.py`。
- `data/market_state/`：市场定义、历史身份/成分、输入、连续结果、固定字典、监督目标、共同样本、月度时间折、字段字典和数据版本。
- `data/standardized/{market,macro}/v4/`：保留的修复后来源层；`scripts/final_data_foundation/`、`scripts/data_foundation_v3/`、`scripts/macro_pipeline/` 为来源采集/标准化库，不提供另一套研究样本入口。
- `data/metadata/`：注册表及来源/字段/公司行为/修复证据；活动研究绑定为 `dataset_registry.json`。
- `reports/market_state/`：集中报告、实际覆盖、缺口、稳定性、复算和验证结果。

主键为 `market_id + asof_date + horizon=20`。四市场为中证全指、沪深300、中证500、中证1000；整体价格与全A横截面分别定义。预测周截止北京时间18:00，未来窗口完整后才有标签。2015—2019初始训练、2020—2022开发、2023年起测试；训练仅用当时已成熟标签，M/M+Z共用相同行。宏观缺失保留，预处理在未来监督模型的训练折内拟合。

E:\QuantData 仅为只读来源；项目保留必要投影，不复制整个数据库。大股票缓存和来源补充可在本机重建，不提交全库。旧研究实验及大备份已移除，其已追踪历史仍由 Git 保存。
