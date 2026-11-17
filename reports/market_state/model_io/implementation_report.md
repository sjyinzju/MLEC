# 统一建模数据接口与输入输出契约实施报告

## 完成结论

**已完成本轮统一接口建设与全量验收，可以开始构建四模型。** 契约版本 `model-io-v1`，底层数据版本 `5d57508f09249cf50b1a2e52`。本轮监督预测模型运行数量 **0**；没有训练、调参、Benchmark、校准训练、准确率、宏观增益或预警效果结果。

封版的36项研究产物与原seal均逐项复核未变；没有采集、扩张日期、重拟合GMM或改写正式标签。原始数据验收报告保留在 `../completion_report.md`，本报告只说明新增兼容层与契约。没有阻碍本轮完成的事项。

## 复用与改造

- 保留 `framework.load_dataset` / `DataStore` 为权威读取链路，复用正式特征集、缺失裁定、样本成员和全部已有时间折。
- 扩展Dataset，分别提供keys、X_market、X_macro、组合X、y、metadata、feature_schema、target_schema、versions和context。`information_view`只投影同一输入，`target_view`复用权威主键目标读取，不另造拼接或样本。
- 复用FoldPreprocessor，补充原始及输出dtype/顺序、类别与缺失规则、内容版本、训练上下文、保存加载。`fit_inputs` / `transform_inputs` / `validate_model_input`是后续模型共用的输入边界。
- 新增 `target_adapters.py`，将既有硬标签适配为一维类别数组，将既有七项连续真值适配为五维等权的训练表达；原单位y始终保留。
- 新增 `model_contract.py`，定义训练、预测、评价上下文、模型能力协议、概率重排、严格结果校验及模型包结构模板。没有实现估计器。
- 在现有tasks调度中增加 `interface-preflight`，直接读取原data_tasks矩阵。DataStore缓存同次不可变快照、schema和连接结果，预处理逐列统计可跨信息集精确限制；未产生四套模型专用数据库或永久矩阵。
- 正式读取改为缺少seal即报错，核验全部封版产物；analysis保持显式。README和AGENTS已同步到唯一[契约文档](../../../docs/model_io_contract.md)。

## 输入与目标如何进入模型

主键仍是market_id/asof_date/horizon=20。M含历史金融信息、当前/滞后名义状态和其他市场同期历史信息；Z只含既有正式系列及派生项，不从候选池重新引入排除系列。每市场M原始99列、M+Z原始323列，自身重复cross列继续移除。正式12个信息集只改变列，不改变同折的行、真实y、标签版本和截止。

五维关系：趋势return；波动volatility；下行压力drawdown；流动性amihud/turnover；市场结构breadth/correlation。七项连续画像与固定字典联合类别表达同一未来窗口，类别编号无风险大小顺序。单位和定义来自既有field_dictionary，生成的机器表见 `target_schema.json`。

分类保留固定字典顺序、研究ID与内部ID双向映射、训练观察/缺少类别。概率列必须通过显式classes顺序重排；缺类须声明error或zero_for_absent，不从测试补类。future_state_prob_*仅为辅助已实现状态软归属，不能误接普通分类器。

回归采用本折训练中位数和IQR；IQR为零则使用总体标准差，再为零才使用1并标记常数。不使用固定小量阈值；全部七项保留。流动性及结构的双指标各除以sqrt(2)，另外三维权重1。逆变换返回原单位七列，再由regression_output保存。M/M+Z及分组使用完全相同的目标适配身份。

训练尺度与评价尺度分开：`evaluation_scales.json`由各市场initial成熟训练行固定生成；跨月不得改用本月训练尺度。预测结果在原单位评价，跨单位汇总先维度内平均再对五维等权。本轮只准备尺度和检查评价交接，没有模型成绩。

## 训练与prediction路径

训练、验证、测试严格读取既有fold_membership；训练标签必须在fit_cutoff前成熟。每次先取训练行，再拟合输入及目标变换。内部调参可通过training_partition显式从外层train选择时间子集，仍检查成熟与前推边界。

prediction使用既有月度计划，只读取历史特征和当时可得宏观信息；不打开supervised_targets或sample_manifest，y为None，资格只依据历史状态。末端每市场4个未成熟周均可通过所在月度预测路径读取；2026年11月两周仍能提供合法X，评分读取保留空结果。全部83个月度折均验证了禁止访问两张未来依赖表后，预测X和metadata不变。初始折只有既定train成员，不虚构部署月份。

## 统一输出与后续四模型边界

完整规范见 `docs/model_io_contract.md` 和导出的 `output_schemas.json`。共同身份包括主键、折、fit_cutoff、模型/信息集/质量视图，以及数据、特征、目标、字典、契约、预处理、目标适配和模型版本。

分类输出predicted_state_id与固定顺序predicted_state_prob_*；概率有限、非负、不大于1，行和容差atol=1e-8/rtol=0，类别须与argmax一致，并列取字典首项。回归固定七项predicted_*，全部原单位；不裁剪超出经济边界的值，明确记录economic_bound_violations。预测接口不接收真实y，预测完成后才按键关联成熟评分真值。

下一轮Elastic Net、RBF-SVM、Random Forest、CatBoost只需实现ModelAdapter.fit/predict及能力声明，按需接逐目标回归、训练内校准和目标逆变换。必须复用本轮读取、时间成员、变换、schema及输出校验，无需修改数据库、重新标注或另写模型数据流程。完整模型包须保存输入预处理器、目标适配器、估计器、必要校准器、输入输出schema、版本与训练上下文；本轮只实现部件保存加载和包模板。

## 全量真实验收

覆盖四市场，每市场initial加83个月度折，共336个市场/训练折组合，4032个市场/折/信息集schema。原矩阵共 **24,048** 个任务，其中 **23,904** 个非空通过、**144** 个无成熟评分行，错误0。空任务是2026年11月评分的预期状态，不是伪造通过的标签。另有 **3,984** 个预测读取任务全部通过，覆盖1,408个不重复市场/预测周；16,896是按12个信息集重复计数的行数，不是独立样本量。

| market_id   |   正式任务 |   非空通过 |   无成熟评分行 |   预测读取任务 |   预测周_不重复信息集 |
|:------------|-----------:|-----------:|---------------:|---------------:|----------------------:|
| 000300.SH   |       6012 |       5976 |             36 |            996 |                   352 |
| 000852.SH   |       6012 |       5976 |             36 |            996 |                   352 |
| 000905.SH   |       6012 |       5976 |             36 |            996 |                   352 |
| 000985.SH   |       6012 |       5976 |             36 |            996 |                   352 |

真实批量检查包括：所有信息集的主键和真实y相同；全部训练标签成熟；分类映射、辅助软归属概率、七项回归顺序正确；每折输入/目标变换只基于训练；全行输入变换与逐列统计限制精确相同；每折输入及目标部件保存加载一致；每折/角色目标往返恢复原单位（rtol=1e-12、atol=1e-24）；所有月度预测读取无需未来表；36项产物与原seal字节不变。

测试结果：**62 passed in 15.16s**，进程退出码 **0**。无筛选的完整pytest会自动刷新test_results.json与接口代码/测试文件身份，按文档两条命令即可重建准入记录。测试额外覆盖全空/常数列、制度后新增值、新名义类别与缺失标记、修改验证/测试值不改变训练统计、修改真实y不改变预测输入、IQR为零的标准差回退、小尺度目标、固定评价尺度、内部时间子集、错版本/信息集/顺序/dtype/行、非法概率/类别及经济边界记录。输出契约只用标记为ARTIFICIAL_TEST_ONLY的人工数组验证，没有保存正式预测表。控制台退出时仍可能出现既有pyreadline析构告警，pytest退出码和通过计数单独记录。

明细：`tasks.parquet`、`prediction_reads.parquet`、`schemas.parquet`；身份：`acceptance.json`；测试：`test_results.json` / `tests.txt`；生成schema：`target_schema.json`、`output_schemas.json`、`example_input_schema.json`。

## 版本兼容关系

- 数据：`5d57508f09249cf50b1a2e52`。
- 特征：`6d50d9efbc48040f0912`。
- 目标：`f49e499c375fa557fcb0`。
- 字典：`76bf6837dc5e32262c99`。
- 契约：`model-io-v1`。
- 原数据构建代码：`310d3ab1cabf4dfb6db5d70cc6eed140af799fcbbffa8f39859cd8cd92a3ed33`。
- 本轮接口代码：`13bdc5025fb6e4bc937e6e9ba147ec9125dfc7d946cdb87bc7552078e1c4e34f`。

旧seal没有改写。本轮acceptance记录原seal哈希和全部原产物哈希，将接口扩展与原封版身份显式关联。下一轮先调用assert_interface_accepted；接口代码变化要重跑接口验收及测试，不能静默沿用旧接口准入。数据或标签变更仍须新的数据验收授权。

## 调用与重验

```python
from scripts.market_state.framework import DataStore, load_dataset
from scripts.market_state.model_contract import fit_inputs, transform_inputs
from scripts.market_state.target_adapters import fit_targets
store = DataStore()
a = dict(market_id='000985.SH', information_set='M+Z', task='regression',
         fold_id='2026-11', store=store)
train = load_dataset(**a, role='train')
predict = load_dataset(**a, role='prediction')
pre, target = fit_inputs(train), fit_targets(train)
X_train, y_train = transform_inputs(pre, train), target.transform(train.y)
X_predict = transform_inputs(pre, predict)
# predict.y is None；这里只准备变换后的矩阵，不调用预测模型。
```

```powershell
$env:PYTHONPATH='.local_deps'
python -m scripts.market_state.run interface-preflight
python -m pytest -q
```

本轮停止于可以开始构建四模型的边界，不提前运行正式实验。
