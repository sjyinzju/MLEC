# MLEC：未来20个交易日的五维市场状态

同伴收到便携压缩包后先完整解压，阅读[交接入口](README_START_HERE.md)。已安装64位Python 3.11且可联网时，双击`START_WINDOWS.cmd`可自动准备环境并启动完整BC；Linux使用`bash START_LINUX.sh`。

研究唯一依据：[market-state-research-v3.0](docs/MLEC_research_protocol.md)。正式快照截止2026-11-13 18:00（北京时间）。先读[集中验收报告](reports/market_state/completion_report.md)和[data release](data/market_state/release/seal.json)。公共实验流程及Elastic Net分类/七目标回归已实现，状态 **IMPLEMENTED**；真实监督训练、参数搜索、smoke和正式实验本轮均为0，没有预测成绩。

[运行与交接说明](docs/experiments.md)包含正式配置、资源、锁、恢复、输出及便携包；[实验规划](docs/MLEC_experiment_plan.md)已同步一次启动BC。准备环境后，同伴之后执行下面一条命令即可自动完成B→锁定→C→评分/报告，无需中途改代码或选参数：

```bash
python -m pip install -r requirements-experiments.txt
python -m scripts.market_state.experiments pipeline --model elastic_net --config config/experiments/elastic_net.yaml --suite full --execute --resume
```

也可运行 `launchers/run_elastic_net.ps1` 或 `bash launchers/run_elastic_net.sh`，支持数据根、结果根和CPU线程参数。full含四市场、两任务的核心M/M+Z，以及固定M+Z开发参数的12信息集分组；默认32候选/12月粗搜索、前4全36月复核。结果为 `results/elastic_net/<pipeline_run_id>/`，自动输出分类、七指标回归、宏观增益、分组、预警、质量及覆盖表与图；开发和测试分别保存。其他三模型与信息时钟等扩展明确未实现，调用会报错。

不训练的检查与打包：

```bash
python -m scripts.market_state.experiments plan --suite full
python -m scripts.market_state.experiments preflight
python -m scripts.market_state.experiments package --destination <new_portable_directory>
```

建模入口规范见[统一输入输出契约](docs/model_io_contract.md)，本轮实施与真实批量验收见[接口实施报告](reports/market_state/model_io/implementation_report.md)。后续四模型必须复用现有数据链路和目标适配器。

本轮接口验收（不采集、不重标注、不训练预测模型）：

```powershell
$env:PYTHONPATH='.local_deps'
python -m scripts.market_state.run interface-preflight
python -m pytest -q
```

正式训练/评分使用显式fold/role；尚无未来标签的输入使用 `role='prediction'`。先 `fit_inputs(train)` 和 `fit_targets(train)`，再使用同一部件变换验证/测试/预测数据。调用下一轮建模前先执行 `assert_interface_accepted()`，防止数据或接口代码与验收身份错配。

以下为上一轮数据构建验收命令，仅在明确授权重建数据时使用；新增接口不需要重新运行GMM或改写原seal：

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
from scripts.market_state.framework import load_dataset
from scripts.market_state.model_contract import fit_inputs, transform_inputs
from scripts.market_state.target_adapters import fit_targets
train=load_dataset(market_id='000985.SH',information_set='M+Z',task='regression',fold_id='2023-01',role='train')
test=load_dataset(market_id='000985.SH',information_set='M+Z',task='regression',fold_id='2023-01',role='test')
pre=fit_inputs(train)
target=fit_targets(train)
X_train=transform_inputs(pre,train)
y_train=target.transform(train.y)
X_test=transform_inputs(pre,test)
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

RBF-SVM第二模型已实现（未训练）：[说明](docs/rbf_svm.md)，正式配置为`config/experiments/rbf_svm.yaml`，仓库一键入口为`launchers/rbf_svm/START_WINDOWS.cmd`和`START_LINUX.sh`。原Elastic Net交接包与运行结果继续独立保留。
