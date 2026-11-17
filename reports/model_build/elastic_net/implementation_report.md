# 公共实验流程与 Elastic Net 构建验收

状态：**IMPLEMENTED**，日期2026-11-17。不是TRAINED或EXPERIMENT_COMPLETE。本轮没有真实预测成绩、最优参数、宏观增益结论或正式选参锁。

## 实现范围

公共流程包含四家族注册与能力声明、正式配置展开、月度执行、训练折变换复用、任务身份、原子保存、内容核验、恢复和失败摘要、B→自动锁定→C、评分/配对/同步日历Bootstrap、预警工作点与完整曲线、表图报告、明确run_id的跨模型汇总和清单式便携包。其余三家族调用明确报未实现，无替代算法。

Elastic Net分类使用锁定scikit-learn 1.8.0的saga/l1_ratio API、一维硬类别和原生概率；回归为共享alpha/l1_ratio的七个ElasticNet。输入/目标适配、固定初始评价尺度、概率对齐、原单位逆变换均复用既有契约。收敛、数值问题、各目标迭代和系数、经济边界违反保留；失败不以零预测替代。完整模型包保存加载并核验代码、schema、部件和版本。

四市场、分类/回归、核心M/M+Z为16配置；full另有fixed_full_params的96配置，共112个含模式的分析配置。32候选在12个季度开发月粗搜索，前4在全部36月复核；分类三种子、确定性回归一种子。实际拟合数按月份、七目标、种子、任务复用和重试另行展开，见plan.json。既有2015—2019初始期、2020—2022开发和2023年起测试不变。

M/M+Z可独立调参；固定参数消融统一引用M+Z开发获胜参数。同一实际拟合以fit_id复用，逻辑task_id仍包含模式；不重复计独立样本。开发完整性和锁在C前核验，测试结果没有选择参数或预警工作点的入口。日志和任务表保留失败候选，不能删失败月份改变评分分母。

## 本轮实际检查

- 导入/compileall、配置及未拟合估计器API检查、正式计划展开、两种启动器静态语法检查、git diff --check。
- 完整接口复验：24,048数据任务，3,984预测读取任务；144项无成熟评分行仍是原封版预期状态。
- 完整pytest：**131 passed**，退出码0。真实监督估计器fit/partial_fit在普通pytest中被禁止；只有不学习数据的测试桩及人工输出。覆盖分类/七目标、原单位及五维损失、配对、同步区块区间、宏观组、预警、表图报告、保存加载、B→锁→C、无execute保护、缺锁/改锁/版本变化阻断、恢复及混合任务诊断保存。
- 临时非E盘运行包真实预检通过：从包内代码启动、92项清单文件、36项封版研究产物（11,175,390字节），不依赖E盘原始湖或复制.local_deps。该子进程还禁止真实监督和GMM拟合，实际调用0次。临时包已清理；portable_package_manifest.json和portable_preflight.json保留复核证据。
- 原seal及36项研究产物内容哈希全部不变。数据、目标、字典和时间折没有修改；原始数据构建身份保留，新增接口和实验代码分别管理。

人工预测、测试桩模型和结果只在临时测试目录，不进入正式results。没有调用真实smoke、参数搜索、监督/校准训练或正式B/C执行。

## 同伴启动与交付

先准备Python环境并安装requirements-experiments.txt，再主动执行一次：

```bash
python -m scripts.market_state.experiments pipeline --model elastic_net --config config/experiments/elastic_net.yaml --suite full --execute --resume
```

也可使用launchers/run_elastic_net.ps1或run_elastic_net.sh；数据根、输出根、CPU线程均可指定。默认不先跑smoke，B后不需要再次手工确认。说明见[运行文档](../../../docs/experiments.md)。

结果根为results/elastic_net/<pipeline_run_id>/。development和test独立保存逐周预测、成熟评分损失、选参/任务身份和必要模型包；根目录包含selection.lock.json、tables、figures和report.md。自动输出core_classification、core_regression、macro_increment、macro_groups、warning_value的CSV/Markdown，以及runtime_quality.csv、coverage_status.csv和类别、可靠性、预警曲线明细。图表可由已有结果重建，summarize/package不会补训练。

便携命令：

```bash
python -m scripts.market_state.experiments package --destination <new_portable_directory>
```

包固定代码、依赖、配置、启动器、文档、原seal、接口验收及实际读取依赖；不复制整个原始湖。按包内字节交接，不改seal来接受不同内容。

后三家族以后补充fit/predict适配器、能力与候选配置、保存加载/解释产物及必要的时间校准或后端实现，复用同一编排与评价。信息时钟、滞后、市场模块、数据视图及替代字典仍为明确未实现扩展；Elastic Net单家族结果不得伪造跨模型Holm值。

## 身份、限制与停止点

- 数据：5d57508f09249cf50b1a2e52。
- 原seal SHA256：728d7adb6305f4951281c800c16508aa3fa1565e52dfbfd7e96f655100acce8f。
- 接口代码：f9ee345ef0af8b95aa11535f4fbcec7dc90da4a6328375356593f2668625e93b。
- 实验代码：86b7ec4bd9805b403c8ea570a83e204c3708e147d4eca256e03f167c5cb52713。

当前没有已知核心代码阻断项。真实求解器收敛、完整规模实际耗时/空间及跨操作系统的真实训练尚未验证；测试桩通过不等于真实模型已拟合或证明预测效果。默认外层worker为1、每任务线程2、缓存2个上下文、空间预算40GiB，触限明确停止。

**本轮真实监督训练=0；参数搜索=0；smoke=0；正式实验执行=0。** 非训练验收已完成，停止在IMPLEMENTED。
