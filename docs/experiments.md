# 公共实验运行器与 Elastic Net

状态：**IMPLEMENTED**。本轮构建不运行真实监督训练、参数搜索、校准、smoke 或正式实验；没有预测成绩或宏观增益结论。下列带 `--execute` 的命令供同伴之后明确启动。

## 环境与一次启动

Python 3.11 或以上，使用独立环境安装锁定依赖：

```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1；Linux: source .venv/bin/activate
python -m pip install -r requirements-experiments.txt
python -m scripts.market_state.experiments preflight --config config/experiments/elastic_net.yaml
```

安装、导入、plan、preflight、普通pytest、package、summarize 都不会调用真实监督估计器拟合。正式完整启动命令：

```bash
python -m scripts.market_state.experiments pipeline --model elastic_net --config config/experiments/elastic_net.yaml --suite full --execute --resume
```

Windows 同等入口：`powershell -ExecutionPolicy Bypass -File launchers/run_elastic_net.ps1`。
Linux：`bash launchers/run_elastic_net.sh`。这两个启动器均主动授权真实运行，默认不先跑smoke。

外置数据和结果根、CPU线程可以通过配置或命令指定：

```powershell
.\launchers\run_elastic_net.ps1 -Python .venv\Scripts\python.exe -DataRoot D:\MLEC-data -OutputRoot D:\MLEC-results -CpuThreads 4
```

```bash
bash launchers/run_elastic_net.sh --data-root /mnt/research/market_state --output-root /mnt/results --cpu-threads 4
```

`data_root` 指含 `feature_sets.json` 和 `release/seal.json` 的研究数据目录；它始终只读。单外层worker、每任务线程上限通过threadpoolctl控制，回归七目标串行。首版明确拒绝 `cpu_workers != 1`，不启用嵌套并行。默认变换缓存上限2个市场/任务/月上下文、结果预算40GiB、至少2GiB空余；触限报错，不清理数据或静默减少实验。Elastic Net仅CPU，不自动切换GPU或库。

## 正式范围与预定规则

主路径读取原来的 `data_task_config` 对应市场/时间成员，通过 `DataStore`、`load_dataset`、`information_view`、`target_view`、训练折输入/目标工厂执行。没有另一套数据拼接、随机拆分、标签或状态字典。

- 初始训练2015—2019；开发2020—2022的36个月；测试2023-01至封版2026-11，共47个月。每月只加入当时已成熟标签重拟合权重，每周预测未来20交易日；未成熟末端继续预测而不评分。
- 每家族核心16组（四市场×两任务×M/M+Z）；`full`另含 `fixed_full_params` 的96组（四市场×两任务×12信息集），共112个带模式的分析配置。固定模式使用对应M+Z开发获胜参数，重新拟合所有信息集的权重。组加入对同模式M，组删除对同模式M+Z。
- 每个核心组32个预生成候选，2020—2022每年1/4/7/10月粗搜索；前4名复核全部36月。候选采用完整端点的对数均匀覆盖和固定种子的混合比例分配：分类C为1e-4至1e4，回归alpha为1e-5至10，l1_ratio为0.05/0.25/0.5/0.75/0.95/1。M/M+Z的候选和预算相同。
- 分类按Log Loss选参，回归按初始固定尺度的五维等权平方损失选参；拼接实际评分周后平均，不把各月均分等权。只用完整复核分数决定最终参数。平局先更强收缩（更小C/更大alpha），再更小l1_ratio，最后candidate_id。
- 筛选种子3060。选定分类配置用3060/3061/3062；cyclic回归确定性实现只运行3060，不重复相同结果。配对按同种子进行，再对同日期损失差平均；不把种子当额外样本或把平均损失称为概率集成。
- 某候选任一必需月份失败，整个候选无资格，不删除失败月份后改分母。粗搜索不足4个完整合法候选、完整复核没有合法候选时停止。数值错误立即失败；收敛最多按10,000→40,000迭代重试一次，外层任务最多2次固定尝试，不改种子或参数。所有失败、重试与告警保留；已锁定开发不会重新筛选失败候选。宏观增益负或分数低不触发重调。
- 类别权重默认null；缺类显式 `zero_for_absent`，只在固定字典补缺席类的零概率；单类明确失败，无过采样。分类使用一维硬标签、原生概率、不校准。1.8.0的合法API为 `LogisticRegression(solver='saga', l1_ratio=...)`，不传已弃用的penalty、多项或n_jobs参数。七回归器共享alpha/l1_ratio，不使用MultiTaskElasticNet，不删除常数/小尺度目标。

配置是JSON语法的YAML 1.2子集，因此无需增加PyYAML依赖。scipy和threadpoolctl沿用现有版本并显式锁定。`plan`列出候选、所有粗搜索任务和选定分析配置；复核与测试参数依赖开发选择，拟合量以展开后上限显示，包含七目标及收敛重试，不把112种配置称为112次fit。

`core`只包含两核心信息集；默认启动器始终为`full`。information_clock、publication_lag、market_modules、data_views、alternative_dictionary是独立未实现扩展，plan显示依赖，指定这些套件会报错；12信息集不等于已经完成所有稳健性检验。

## 自动阶段、锁定与恢复

一次明确启动自动执行预检→B搜索/复核→选定开发及12信息集分组→开发完整性检查→生成并验证锁→C时间前推测试→评分配对→表、图和报告。B与C之间没有第二次人工选择或点击。

`selection.lock.json`含完整开发证据引用、选定参数、信息集/模式、CPU后端、种子、异常处理、固定评价尺度、统计检验集合、风险映射和B期工作点、允许的月度更新及全部版本。内容自身hash和run manifest登记的文件hash双重核验；C还重新核验开发证据。开发失败、缺锁、改锁、数据/代码/契约变化均不能进入C。测试结果没有选参或工作点入口。

默认run_id由配置（不含路径）、版本及suite内容确定。相同命令加`--resume`继续同一个目录；也可事前指定`--run-id`。指定旧run_id但版本不同将报错。data_root/output_root可搬迁，但内容哈希必须相同；线程、参数或研究规则变化会形成新身份，不能混用旧任务。

任务清单保存家族、任务、市场、信息集、模式、阶段、月份、参数、种子、后端、purpose及版本。逻辑task_id包含模式；物理fit_id忽略分析模式，只允许完全相同的实际拟合被引用。原有预测表不增加实验身份列；分析元数据存于任务清单/assignments，报告扩展表按 `family/market/task/mode/information_set/seed` 分组后评分配对。重复引用不是额外独立样本。

文件先在同卷临时目录完整写入，再原子提交；成功记录验证所有文件哈希。中断的RUNNING任务可重做；成功任务只读复用；被修改/丢失的成功产物报错，不悄悄覆盖。任务固定失败尝试耗尽后保留失败，不无限重试。`tasks.parquet`和`logs/failures.json`在阶段结束、异常和定期检查点重建。

```text
results/elastic_net/<pipeline_run_id>/
  manifest.json / config.resolved.yaml / environment.json / preflight.json
  tasks.parquet / selection.lock.json
  development/
    tasks/ / fits/<fit_id>/ / selection/ / losses/ / metrics/ / tables/ / figures/ / report.md
  test/
    tasks/ / fits/<fit_id>/ / selection/ / losses/ / metrics/
  tables/ / figures/ / report.md / logs/
```

每个fit目录含原契约预测、真实评分行/逐样本损失、预警输入、上下文及内容清单；Elastic Net还含全部变换后特征名的系数。候选仅保留完整复核末月的4个候选包以支持不中断恢复和选定包复用，不保存每个候选每月的权重。选定核心测试按月保留完整模型包，其他选定分析保留末月包。模型包包括预处理器、目标适配器、七回归器/分类器、输入/输出schema、参数/版本/训练上下文、收敛记录；加载核验文件、代码和数值依赖。joblib仅加载可信本地产物。

## 评分与交付

预测接口只有X和PredictionContext；保存并校验预测后，才按既有成熟评分键关联Y。概率保护统一1e-15且记录触底次数，Brier不除K；分类还有Accuracy/Macro-F1/Balanced Accuracy、各类P/R、混淆矩阵、可靠性图。缺类不可定义的指标和无事件对照明确缺失及原因。回归在原单位计算七项MAE/RMSE和经济边界违反，再用固定initial尺度维度内平均、五维等权；不重复训练适配器中的维度权重，不裁剪预测。

复用已修复的 `paired_losses`，先按任务/模式/种子/指标/信息对照严格分组；核验所有共同版本、时间折、截止和真值。差值正数有利于右侧模型。按同步日历时间移动区块Bootstrap，8周为主、4/12周敏感性、2000次；包含空日历周，区间用未中心化差，单侧p值用零均值中心化差并作有限次数修正。跨模型主检验集合是全指分类Log Loss的RBF-SVM/Random Forest/CatBoost三个非线性家族；未齐备不生成Holm值，Elastic Net保持线性参照。

预警复用固定画像的下行/流动性/广泛下跌类别概率、概率加权回撤和回归回撤。5/10/20/30%负担目标事前固定，B期选不超过目标的最大可达报警负担（含并列）；锁到C。完整检出—误报、P–R、回撤覆盖—负担曲线与窗口指标、连续日历报警段、重复周数分别保存。不训练第五模型，不凭窗口虚构危机起点/提前天数或唯一最优成本阈值。

自动输出以下CSV/Markdown：`core_classification`、`core_regression`、`macro_increment`、`macro_groups`、`warning_value`；另有 `runtime_quality.csv`、`coverage_status.csv`、类别P/R、混淆矩阵、可靠性和预警曲线明细。逐周预测、逐样本损失、逐样本配对差、种子均值差与锁都是可重算基础。开发报告在development内，测试主报告在run根；方向、区间、年度和限制来自实际保存结果，不预设宏观有效。

```bash
# 均不补跑训练
python -m scripts.market_state.experiments plan --suite full --plan-output reports/model_build/elastic_net/plan.json
python -m scripts.market_state.experiments summarize --run results/elastic_net/<run_id> --stage test
# 一个明确run_id目录/家族；其余家族实现并运行后才加入
python -m scripts.market_state.experiments summarize --run <elastic_run_dir> --run <other_run_dir> --destination results/summary/<summary_id>
```

单阶段排错入口仍保留；B单阶段完成后可调用lock，再调用C，也可用pipeline自动衔接：

```bash
python -m scripts.market_state.experiments run --stage development --suite full --execute --resume
python -m scripts.market_state.experiments lock --suite full --resume
python -m scripts.market_state.experiments run --stage test --suite full --lock results/elastic_net/<run_id>/selection.lock.json --execute --resume
```

独立真实smoke入口为 `python -m scripts.market_state.experiments smoke --config config/experiments/smoke.yaml --execute`，本轮调用次数0。它只保留简短技术检查摘要，临时权重/预测自动清理，无成绩表、排名或研究证据。正式报告拒绝SMOKE_ONLY/ARTIFICIAL_TEST_ONLY。

## 便携交接与后续模型

```bash
python -m scripts.market_state.experiments package --destination <new_portable_directory>
```

包内固定代码、依赖、配置、启动器、协议/契约/运行文档、原seal、接口验收/测试身份及seal的36项研究产物；`package.manifest.json`绑定全部文件内容，包含基线提交及未提交实现的内容身份。不包含.local_deps、整个原始湖或E盘数据库。复制目录后不重写seal，安装同样依赖即可从包根执行上述启动命令。数据可另放只读目录，用`--data-root`指定。验收将同内容复制至非E盘临时路径并核验读取、变换及预检。

另外三家族在registry中明确未实现，调用直接报错。以后补充 `ModelAdapter.fit(X, y, FitContext)`、`predict(X, PredictionContext)`、能力声明、参数候选及保存加载/解释产物即可复用公共运行、评分、锁和报告；SVM时间校准和CatBoost训练内早停仍须按契约接入，不能复用外层评分Y。正式环境/真实求解器收敛、实际耗时与磁盘需求需同伴显式运行后确认；测试桩通过不证明真实模型效果或求解器已经跑通。
