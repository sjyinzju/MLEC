# Elastic Net 第一轮历史审计

审计对象：`60c8639de8935d891b0e79d1`，原结果 `suite=core`，不等于 full。原始归档从 `047f76de38d726f6e2fda86b53a0fd71a2ba65f1` 读取；本轮只补交原 ZIP，归档新提交 `fe4b161`。此前六项材料没有改写或重复提交。

本机微信文件目录找到两份同内容 `MLEC_elastic_net_60c8639d(1).zip`，均为9,300,967字节；SHA256：`e05ab877cb4ab9cf09f7108c5072aab81c9f224dc9d816ee6c6c290165e69b77`。ZIP CRC、EXPORT_MANIFEST 的65/65文件大小和哈希均通过；manifest/preflight/search及原分类CSV与既有Git归档逐字节相同。原样提交到归档目录的 `export/original_export.zip`。归档之后恢复只读，优化分支直接基于 main 的 `313bb6a6d123cfd50d408097906f32f1f27cccbc`，不合并历史分支。

完整解析独立审计 JSON；`old_run_evidence.json` 记录每节内容哈希、原导出65文件核验、版本、锁与搜索证据。复核脚本 `audit_old_export.py <原ZIP路径>` 只读取历史文件，不执行历史程序。以下区分原文件复核与本轮隔离技术复现。

| 问题 | 证据与复现 | 级别 / 处理 |
|---|---|---|
| 状态概率异常缩放 | 原公共 `preprocessing.py` 对所有数值列除训练IQR；封版数据全指2020-01的prob0 IQR为1.214211e-7，输入最大8,235,800.67、最大行平方范数2.278150e14；四市场及2022-12均复现，见baseline_inputs.json | 已确认公共预处理缺陷；按语义处理 |
| SAGA假成功 | baseline_solvers.json：同一初始窗口C=1e-4、l1_ratio=.05，真实旧求解返回8734迭代且无告警；平均概率与类别频率残差最大0.501959873，截距接近0。官方步长公式在旧尺度下约8.779e-15 | 已确认该技术例的求解失真；不能外推为每个旧fit的最优性证据。新版用独立一阶/目标/KKT验收 |
| 概率类别或分数对应 | 原开发/测试 selected_scores 逐样本 Log Loss、Brier、argmax重新计算，最大差0，类别字典3类；均匀概率参考ln(3) | 未发现映射/评分算术缺陷；接近均匀概率下argmax跳变不证明概率质量改善 |
| 回归失败 | 原 search.json：118/256回归粗筛组内候选无效；原质量表1240失败回归记录；8个回归获胜者7个alpha=10。隔离弱正则技术例10k/40k均耗尽，dual_gap约.0155/.0144 | 失败已确认；不能把所有候选失败都归为IQR，旧逐目标诊断未导出。新版保留候选覆盖，独立检查七目标primal/dual和补救路径 |
| 负重试与失败耗时 | 原development及test质量表共10756行：4158条负重试，1240失败行耗时缺失。旧 `reports.analysis_frames` 用attempts-1，复用记录attempts=0；旧TaskRunner失败分支不记录elapsed | 已确认报告/运行缺陷；重试按物理历史计且非负，所有尝试记真实墙钟时间和原因 |
| 模型哈希 | 本轮隔离真实旧拟合保存/加载后joblib.hash不同并报weights mismatch，见baseline_solvers.json；HOW_TO_APPLY记有内存修补 | 已确认旧库组合的序列化身份问题；新版对预测相关数值状态作规范内容哈希，不依赖数组stride/对象pickle结构 |
| 并行来源 | 原说明记载外部8进程×2线程及运行时哈希修补，但未附实现/一致性证据 | 旧外部源码仍不可审计；不凭空复原。本轮复用main原生spawn调度并做新真实一致性测试 |
| 宏观增益和覆盖解释 | 原full分组未执行；全指部分概率增益为浮点数级，类别失衡明显 | 数值等价需单独标识、保留原分数；联合呈现概率损失/平衡指标/各类召回/混淆。修复core/full文案 |

仍缺：各fit原始预测、系数与模型包；tasks.parquet/逐任务日志诊断；外部并行源码和验证记录。这些不在原导出中，本机项目目录亦未找到。原ZIP恢复了完整**导出包**，不等于恢复原约3.4GB全量运行目录。不得以汇总审计结论冒充重新核验过的每次模型最优性。未重跑旧B/C、旧选参或生成替代旧产物。

官方数值定义核对：[sklearn 1.8 Logistic Regression](https://scikit-learn.org/1.8/modules/linear_model.html#logistic-regression)、[ElasticNet](https://scikit-learn.org/1.8/modules/generated/sklearn.linear_model.ElasticNet.html)、[SAGA步长源码](https://github.com/scikit-learn/scikit-learn/blob/1.8.0/sklearn/linear_model/_sag.py)。实际运行使用锁定的本地1.8.0源码；技术复现只看训练数据。

独立重算原沪深300测试逐样本证据：M与M+Z的平均种子Accuracy差为 0.118556701（M+Z减M），Log Loss差为 6.871329149e-05（M减M+Z）。这是旧结果核算，不是新版测试或选参依据。
