# MLEC：未来20个交易日的五维市场状态

研究唯一依据：[market-state-research-v3.0](docs/MLEC_research_protocol.md)。正式快照截止2026-11-13 18:00（北京时间）。先读[集中验收报告](reports/market_state/completion_report.md)和[data release](data/market_state/release/seal.json)。本轮没有监督预测模型或预测成绩。

```powershell
$env:PYTHONPATH='.local_deps'
python -m scripts.market_state.run build
python -m scripts.market_state.run accept
python -m scripts.market_state.run preflight
python -m scripts.market_state.run reproduce
python -m pytest -q
python -m scripts.market_state.run seal
```

```python
from scripts.market_state.framework import load_dataset, preprocessing
train=load_dataset(market_id='000985.SH',information_set='M+Z',task='regression',fold_id='2023-01',role='train')
test=load_dataset(market_id='000985.SH',information_set='M+Z',task='regression',fold_id='2023-01',role='test')
pre=preprocessing()  # 未拟合；只能fit(train.X)
# 分类、软归属目标：task='classification' / 'probability'
# 全时期仅描述查看：显式view='analysis'；不能把它当作一次训练集。
```

- `scripts/market_state/` 为唯一研究实现；前后向窗口共用测度函数。
- `data/market_state/` 管理对象、过去输入、未来结果、状态字典、样本和时间折；统一主键market_id/asof_date/horizon。`feature_sets.json`区分候选池、正式M/Z和五组加入/删除；`missing_policy.json`是实际执行的排除与缺失裁定。
- `data_tasks.parquet` / `data_task_config.json` 为模型无关的批量数据任务，不配置具体监督模型。选择模型后统一批量运行，不为每个模型新造数据流程。
- 缺失值、常数、训练折全空列和名义状态编码由训练折预处理确定；没有全样本提前拟合。M/M+Z及所有分组比较共用相同行和目标。
- `data/standardized/{market,macro}/v4/`及来源库保留有效历史数据、采集、身份、公司行为和修复证据；来源库不是另一套研究样本权威。E:/QuantData只读，不复制全库。
- `release/input_snapshot.json`记录起始输入，`release/seal.json`绑定正式数据/目标/特征/缺失规则/代码。新父数据或口径变化需要重新构建验收；封版后停止自动扩库。

依赖见[requirements-research.txt](requirements-research.txt)；来源库附加依赖见[requirements-data-v4.txt](requirements-data-v4.txt)。报告会明确区分制度性不适用、合法发布值持有、来源缺口、预热不足、停牌和未来标签未成熟。历史成分快照不声称精确逐日成分。
