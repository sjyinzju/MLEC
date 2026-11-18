# 统一建模输入输出契约

契约版本：`model-io-v1`。本文件是监督建模数据进入与预测返回的唯一接口规范。研究语义服从 [v3.0协议](MLEC_research_protocol.md)，数据身份服从原始 [seal](../data/market_state/release/seal.json)。本轮只建设兼容层、适配层与校验；监督预测模型运行数量为0。

后续实现状态补记：公共实验流程、Elastic Net与RBF-SVM已在[实验层](experiments.md)实现，尚未真实训练。下文“本轮”描述原接口验收阶段。`DataStore(data_root=...)`可读取同内容的只读迁移数据，按原seal相对路径映射校验哈希，不改seal。空回归输出固定字符串类型，保留原字段语义；实验身份放在任务清单及显式报告扩展表，不向预测schema随意加列。

## 语义与权威来源

每条样本的主键为 `market_id + asof_date + horizon=20`，每个完整交易周最后交易日北京时间18:00预测，预测整个后续20交易日窗口。

五个经济维度由七个连续指标表达，既有共享GMM字典将这幅连续画像概括为联合状态类别。不是七个经济维度，也不是五个独立的离散标签。类别ID是名义编号，无连续风险等级含义。

<!-- generated-target-table:start -->
| 指标 | 经济维度 | 原单位 |
|---|---|---|
| return | trend | ratio |
| volatility | volatility | annualized ratio |
| drawdown | downside | nonnegative loss ratio |
| amihud | liquidity | 1/CNY |
| turnover | liquidity | ratio |
| breadth | structure | ratio |
| correlation | structure | Pearson correlation |
<!-- generated-target-table:end -->

上述表从 `model_contract.target_schema()` 生成，其单位和定义读取既有 `field_dictionary.parquet`，类别与画像读取既有状态字典和profiles。机器可读完整表见 [target_schema.json](../reports/market_state/model_io/target_schema.json)。不另行维护类别清单或正式宏观变量白名单。

输入的权威清单为 [feature_sets.json](../data/market_state/feature_sets.json)，正式纳入和排除规则为 [missing_policy.json](../data/market_state/missing_policy.json)，依赖为 [research_dependencies.json](../data/market_state/research_dependencies.json)。所有被排除候选系列及派生列继续排除。

`future_state_prob_*` 是已实现未来窗口对固定字典的辅助软归属，`predicted_state_prob_*` 是未来模型的事前预测概率。普通多分类只能接收一维硬标签；软归属视图不自动成为第三项主要训练任务。

## 唯一读取链路与对象

继续使用 `framework.load_dataset`、`DataStore` 和既有 `fold_membership`、`time_splits`。所有拼接显式使用主键，检查唯一性和一一对应；不分别拆分X和Y。

返回 `Dataset`：

| 属性 | 内容 |
|---|---|
| keys | 唯一、有序的三列主键 |
| X_market | 选定正式信息集内的历史金融输入，含当前/滞后状态及其他市场历史信息 |
| X_macro | 选定信息集内、截至预测时点实际可得的正式宏观输入；M时为空列DataFrame |
| X | 按正式顺序组合的 `X_market + X_macro`，保留原始缺失；尚未预处理 |
| y | 分类一列、回归七列或明确标识的辅助软归属；prediction时为None |
| metadata | 主键、asof_time、折/角色、fit_cutoff、数据/特征/目标/字典/契约版本；评分读取另含窗口和标签成熟信息 |
| feature_schema / target_schema | 原始列顺序及dtype / 固定类别、连续指标、单位、维度及概率规则 |
| versions / context | 数据身份及本次市场、折、角色、信息集、宏观质量视图 |

所有分量同索引、同行序、同行数。metadata和y不自动进入X；未来收益、未来覆盖、标签成熟/有效性均不属于输入。

支持四市场及正式12个信息集：M、M+Z、五组加入、五组删除，名称从feature_sets读取。按市场移除自身cross重复列。同一拟合实例固定市场、信息集、质量视图、折、训练截止和版本。`information_view(ds, info, store=store)` 只允许从已读取的超集按同一清单投影，不重新拼接或筛选行。`target_view(ds, task, store=store)`复用同一输入并通过权威主键目标读取逻辑切换目标视图。

`validate_pair(a,b)` 验证行、真实y、版本、市场、角色、折和训练截止一致。加入宏观只改变列；不改变行或目标，不在评分时才取交集。

## 时间角色与预测路径

正式读取必须指定fold/role，并存在有效正式seal；校验全部封版产物，缺少seal时明确报错。2015—2019初始训练与既有2020年起月度折保持不变；初始折仅有train，没有另造初始预测期。

- `role='train'`：既有折训练成员，所有标签在fit_cutoff前成熟。
- `role='validation'` / `'test'`：既有相应月度评分成员，不含未成熟窗口，也不改变开发/测试边界。
- `role='prediction'`：使用既有月度计划的预测日期，仅从market_features、当时可得宏观、固定字典schema和time_splits构造；不打开supervised_targets或sample_manifest。`prediction_eligible`只依据已存在的历史当前状态，默认返回合格行；不要求未来y存在。末端2026年11月的两周、每市场均可返回X，尽管该月没有成熟评分行。
- `view='analysis'`：显式描述性查看，可配合eligible_only=False查看缺失；不能用于fit_inputs或fit_targets。无seal时也能分析，但data_version为空，不能静默成为正式训练。

预测资格与训练/评分资格分开表达。prediction的metadata不携带未来成熟时间或未来有效性；目标/字典版本是固定定义的身份，无须读取未来真值。

宏观按available_at <= asof_time校验。合法已公布值持有、信息年龄、制度性不适用、真实缺失及定义切换继续沿用封版规则。不取所有宏观值完整案例的交集。

## 输入预处理与schema

正式调用 `fit_inputs(train)`，随后只调用 `transform_inputs(pre, validation_or_prediction)`。返回有序、float64、有限值的二维具名DataFrame。后续模型适配器在接收变换后X时复用 `validate_model_input(X, pre.schema_, keys=...)`，检查实际模型矩阵的列、dtype、有限性与行身份。底层仍是既有 `FoldPreprocessor`，没有每模型一套预处理。

先按时间折取行，再逐列学习训练统计：数值中位数填补、IQR缩放（IQR非正则使用1）、数值全空及常数值列删除，所有原始数值列仍保留固定缺失标记。名义状态按训练观察类别one-hot编码，并固定MISSING/UNSEEN列；不把状态ID当风险连续数值。制度后新增列在早期训练全空时不学习未来数值。

schema保存原始列/dtype、输出列/dtype、删除列、类别、填补及尺度参数、缺失规则、训练上下文和schema_version。不同折可不同，同一次拟合的验证、测试、预测必须相同。错顺序、错dtype、错版本、错信息集、错折、未拟合及非有限输出均报错。

全部统计逐列计算，输入预处理不依赖y值。M/M+Z共享金融列的变换完全相同；可独立拟合核对，或用 `restrict_inputs(full_pre, train_view)` 精确复用同一训练样本的统计。不能复用其他训练行、截止或版本的统计。

内部调参同样遵守这一规则。`training_partition(outer_train, keys, role=..., fit_cutoff=...)` 只允许显式选择外层训练成员，拒绝不成熟训练标签、截止之后的训练信息或截止之前的内部验证行；不产生随机拆分，不使用外层验证/测试拟合。然后在内部train调用fit_inputs/fit_targets，在对应内部validation调用变换。

保存 `pre.save(directory)` 同时产生本地joblib部件和input_schema.json；`FoldPreprocessor.load`检查一致性。joblib只加载可信本地产物。正式训练上下文只通过fit_inputs绑定，直接调用底层fit适合独立单元测试，不能替代正式边界校验。

## 目标适配与评价尺度

`fit_targets(train)` 自动区分两项主任务；辅助软归属明确拒绝进入此工厂。

分类适配器从固定字典取得类别全集和顺序，保存研究ID与内部0..K-1映射，输出一维整数数组。记录本折实际出现与缺少类别，缺类处理由后续估计器显式声明，不能从验证/测试补类。类别不缩放。`align_probabilities(p, model_classes, class_space=..., missing_policy=...)` 将任意合法内部概率列顺序返回研究顺序；缺列默认应声明error，只有显式zero_for_absent才补零，无静默归一化。

回归适配器固定七项及原单位真值不变。逐目标训练中位数中心、训练IQR尺度；IQR精确为0时使用训练总体标准差，仍为0时用1并标记常数。无任意固定小量阈值。趋势、波动、下行的权重为1，流动性两个指标与结构两个指标各为1/sqrt(2)：

`z_j = (y_j - median_train_j) / scale_train_j / sqrt(该维指标数)`。

逆变换严格对应，输出按七项顺序排列的原单位DataFrame。七项始终保留，包括常数、小尺度或难预测目标。M/M+Z和分组任务的y、适配版本和参数相同。监督回归尺度与GMM标签字典尺度相互独立，不重拟合字典。

训练用本折尺度；跨月评价固定使用同市场initial成熟训练行的尺度，由 `evaluation_scale(market_id=..., store=...)` 提供，记录版本与来源截止。评价在原单位预测还原后进行，原单位误差同时保留；跨单位误差除以固定初始尺度，先维度内平均再对五维等权。不能将月度训练尺度直接替代评价尺度。`EvaluationContext`与`prepare_evaluation`检查固定尺度的市场/版本/来源身份，不在本轮计算模型成绩。

目标适配器JSON保存schema、上下文、参数和内容版本；`TargetAdapter.load(path, context=...)`校验身份。往返容差统一为rtol=1e-12、atol=1e-24；Amihud不会因为量级小而被当成零尺度。

## 模型边界与结果格式

`ModelAdapter` / `Evaluator` 为结构协议：

```python
fit(X_train, y_train, fit_context)
predict(X_predict, prediction_context)  # 无y_true参数
evaluate(predictions, y_true, evaluation_context)
```

`FitContext`记录市场、折、训练截止、信息集、宏观视图、版本及训练主键/真值身份。`PredictionContext`只含预测主键、拟合/模型/部件身份，不含真实y。`ModelCapabilities`声明模型家族、任务、容器、原生多输出或逐目标封装、缺类与校准方式。未来校准只能使用训练内按时间顺序产生的结果。

Elastic Net、RBF-SVM、Random Forest、CatBoost后续只需实现fit/predict及能力声明，必要时接入逐目标回归、训练内校准器和目标逆变换。内部可使用不同容器；对外不得改变经济定义、样本、特征或目标顺序。下一轮不再准备专用数据库、不另写宏观拼接或时间拆分。

统一输出共同身份：主键、fold_id、fit_cutoff、model_id、information_set、quality、data_version、feature_version、target_version、dictionary_version、contract_version、preprocessing_version、target_adapter_version、model_version。

机器可读输出格式由 `prediction_schema` 产生并导出为 [output_schemas.json](../reports/market_state/model_io/output_schemas.json)，模型包模板同时保存输入和输出schema。

分类由 `classification_output` 构造：predicted_state_id及固定字典顺序的predicted_state_prob_*。概率必须有限、在[0,1]内、K列、每行和1（atol=1e-8、rtol=0）；不允许负数容差、不自动修正。类别必须等于argmax；并列取字典顺序最前者。

回归由 `regression_output` 构造：七项predicted_*列，全部原单位、有限值。默认保留原始预测；经济边界违反记录在economic_bound_violations，禁止隐式裁剪。边界来自机器schema，换手率不武断设置最大值1。output_units固定为original。分类与回归分开构造，不强迫同一估计器兼做。

`validate_output` 拦截列/顺序/概率/决策/身份/行数/主键错误，包括丢行、重复行、跨市场或折错配。预测完成后，`prepare_evaluation`或`evaluation_pairs`才按键关联真实y，要求相同角色、折、截止、版本和评分成员。若预测集合含未成熟行，应另按既有成熟评分成员显式取对应预测子集再评价；不能为评分而改变训练样本。

逐样本评分复用 `evaluation.multiclass_losses` / `continuous_losses`，在 `evaluation_pairs` 关联真值后，将所选同口径逐行损失放入loss列，再调用 `framework.paired_losses(left, right, task=...)`。配对按完整主键集合一一连接，允许两表行顺序不同，不取交集；必须保留正式输出全部共同身份和真实目标列。分类及其Log Loss/Brier使用task='classification'和future_state_id；回归要求固定七项原单位真值全部一致，即使当前loss只评价其中一项。task='probability'仍只表示辅助软归属真值视图，不自动成为主要预测任务。

配对共同身份来自机器契约的IDENTITY与OUTPUT_CONTEXT_FIELDS：data_version、feature_version、target_version、dictionary_version、contract_version、fold_id、fit_cutoff、model_id、quality、target_adapter_version必须一致。feature_version是正式特征定义的全局版本，信息集仍可选不同列。information_set、model_version（各自拟合的模型权重身份）、preprocessing_version允许不同，其字段必须存在但不要求值相等。不接收label_version代替dictionary_version；缺列、空身份/目标、重复键、样本不同、真实目标或共享身份不同、非有限损失均报错。损失差固定为loss_M-loss_MZ，正值表示右侧损失更低。人工输出只在测试内使用，不保存为正式预测结果。

未来完整模型包必须包含：输入预处理器、目标适配器、估计器、必要校准器、输入输出schema、版本、训练上下文和能力声明。`package_manifest`只提供结构模板，本轮不创建估计器或训练后的完整模型包。

## 版本与兼容性

原始seal、研究数据、特征、标签与GMM文件保持内容不变；原数据代码哈希描述当时的数据构建。新增接口代码身份单独记录在 [接口验收](../reports/market_state/model_io/acceptance.json)，保留其与原seal及36项数据产物哈希的关系。不能修改旧seal以绕过代码变化，也不因只增接口重新打标签。

`assert_interface_accepted()` 是下一轮开始建模前的准入检查：正式数据身份、契约版本、原seal和本次接口代码哈希必须一致。接口代码变化后重新运行接口验收及测试；完整pytest的session钩子会刷新test_results.json及当前接口/测试代码身份（有筛选的单项运行不刷新正式记录）；数据变化需要新的数据验收，不在本轮隐式进行。DataStore仅缓存本次不可变读取，不生成模型专用数据文件。

## 最小调用

```python
from scripts.market_state.framework import DataStore, load_dataset
from scripts.market_state.model_contract import fit_inputs, transform_inputs, fit_context
from scripts.market_state.target_adapters import fit_targets
from scripts.market_state.interface_acceptance import assert_interface_accepted

assert_interface_accepted()
store = DataStore()
args = dict(market_id='000985.SH', information_set='M+Z',
            task='regression', fold_id='2026-11', store=store)
train = load_dataset(**args, role='train')
predict = load_dataset(**args, role='prediction')  # y为None
pre = fit_inputs(train)
target = fit_targets(train)
X_train = transform_inputs(pre, train)
y_train = target.transform(train.y)
X_predict = transform_inputs(pre, predict)
# 到此只拟合数据变换。下一轮才实现 ModelAdapter.fit/predict。
# target.inverse_transform(transformed_predictions) -> 原单位七列
```

```powershell
$env:PYTHONPATH='.local_deps'
python -m scripts.market_state.run interface-preflight
python -m pytest -q
```

完整结果与阻断项见 [集中实施报告](../reports/market_state/model_io/implementation_report.md)。本轮没有模型训练、调参、Benchmark、校准训练或预测效果结论，停止在可以开始构建四模型的边界。
