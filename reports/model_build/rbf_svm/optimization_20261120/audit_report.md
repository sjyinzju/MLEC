# RBF-SVM 全面自查与交付报告（2026-11-20）

## 结论与授权边界

**AUDITED_PENDING_REAL_REVALIDATION**，不是RBF_SVM_READY_FOR_FORMAL_BC。用户随后明确要求“完成前自查，包括模型构建和预期效果，不要运行模型”。此后不执行真实估计器fit、校准优化、smoke、技术训练或正式B/C；修复后的真实端到端、Windows spawn、取消恢复及新进程保存加载仍待以后明确授权。普通测试以非学习桩/解析样例验证，不能替代这些实测。

停止指令前，按此前真实验收授权完成2个初始全指M技术探针：10次SVC（内部9＋最终1）、7次SVR、3次sigmoid，均在2019年底成熟train上运行；没有搜索或正式B/C。拟合及同进程保存加载均通过，未复现真实joblib往返失败。证据baseline_probe.json属于旧实现探针，不是修复后验证，也不是宏观效果证据。临时权重已随自建TemporaryDirectory清理。

## A. 架构、口径与原本正确的部分

追踪DataStore/load_dataset → information_view → fit_inputs/transform_inputs、fit_targets → MonthlyExecutor → TaskRunner/TaskScheduler → RBF适配器 → 输出校验 → 保存预测后显式关联成熟评分Y → B选参/锁/C报告。没有第二套数据或评分系统。基线含semantic-inputs-v2、experiment-runtime-v2；未修改公共预处理、七目标适配、原seal、GMM、标签、研究成员或Bootstrap。

分类先从绑定原始外层train中用training_partition构造13周起始、26周验证块；内部asof_time和实际label_available_at均不晚于cutoff，验证行在cutoff后。每块自己的预处理及gamma仅拟合内部train，最终才拟合完整成熟train。M/M+Z块边界及OOF成员仅依训练标签和日期，不依输入信息。外层验证/测试Y不进入校准。

## B. 问题分类与修复

| 项目 | 状态 | 证据/处理 |
|---|---|---|
| 旧公共IQR概率爆炸是否仍使用 | 已排除 | SVM实际复用semantic-inputs-v2，24视图最大绝对输入19.974984；M金融列逐元素配对 |
| sigmoid仅凭result.success，未按原gtol复核 | 已确认并修复实现；真实复验待做 | 旧探针梯度最大1.1663e-7却被接受，原gtol=1e-8；新v2独立重算目标/梯度及仅截距可行目标，最多20步同目标阻尼Newton，不放宽1e-8阈值 |
| 极少OOF类别被误当可靠校准 | 已确认诊断缺口并修复 | 332范围中329个最小正/负支持不足20，最少正例4；保留原最低2门槛，但明确LEGAL_BUT_SPARSE_UNSTABLE，不伪造可靠性 |
| 仅求解状态码，缺少独立最优性证书 | 已确认诊断缺口并修复实现 | 新增逐OVO SVC及SVR对偶盒约束/等式/KKT、primal/dual/gap；解析二类、三类、SVR闭式例通过；真实解证书验证未运行 |
| 极端有限X方差上/下溢影响gamma | 已确认数学边界并修复 | 先按最大绝对值缩放计算方差，再分步恢复gamma；不可表示gamma显式拒绝，不把下溢伪装成零方差 |
| 真实对象级joblib哈希不稳定 | 本轮未复现 | 两探针同进程往返通过；改为规范数值状态作为身份加固，覆盖公共/私有预测数组与参数，排除耗时；跨进程实测待做 |
| 候选间重复内折预处理 | 已确认并实现有界复用 | 每训练服务64MiB LRU，外层2上下文、每上下文2信息集服务；不共用权重；桩测试精确矩阵及上限 |
| 少数类、分布漂移、OVR统计语义 | 研究限制 | 不重采样、不改Y、不替换历史频率或随机CV |
| 正式泛化、最优边界、失败率和耗时 | 尚需正式B/C验证 | 未运行搜索，不能从短探针推断完整候选成功率和宏观增益 |

## C. 核几何、概率与七目标预期行为

真实输入审计：4市场×3月度train（2020-01、2021-10、2022-12）×M/M+Z，共24视图。逐列范围/方差、删列/缺失、范数、全部gamma因子、非对角核分位数、距离、重复/近重复/不相似比例和谱参与秩见nontraining_audit.json。gamma因子1时M约0.01139645—0.01141350，M+Z约0.00422067—0.00430718。同factor代表相同训练尺度规则，不意味着加入宏观后的距离或绝对gamma相同。缺失指示/one-hot的自然尺度参与几何，不用全期统计改变比例。

因子100时许多非对角核趋近0是注册大gamma的数学极限，意味着接近局部记忆；因子0.01及强正则可能近常数。保留原范围和48候选，不把极限行为直接判为代码错误，也不承诺有预测信息。C×gamma的6个C数量级×5因子单元中4个未覆盖；有限设计有联合覆盖限制，无开发搜索证据且本轮禁止运行模型，所以不改候选分配或夸大覆盖。

SVC多类实际OVO；OVR返回是投票加有界置信修正（不是独立OVR超平面距离）。同类别列按固定字典映射，二类margin展开[-margin,+margin]；内外折分数仍可能漂移。保留训练期OOF逐类Platt再归一化，未改随机CV、未用同样本预测替代OOF、未从评分标签补类。三sigmoid归一化是定义，不能保证多类校准；当前少数类支持尤其不足，不宣称概率可靠。v2数值最优性只验证拟合的凸目标，不是样本外校准有效性证明。

七项回归完整保留：return、volatility、drawdown、amihud、turnover、breadth、correlation。沿用训练目标中位数/IQR及五维权重后各拟合SVR，共享C/gamma_factor/epsilon；原单位逆变换后评分，边界违反只记录不裁剪。小单位amihud不因绝对量级删除；大epsilon或强正则的合法常数预测须由训练期KKT/支持量诊断区分。修复后实际预测随状态的变化、基准对比、OOF Log Loss/Brier/可靠性与少数类排序尚未测量，不能声称优于历史频率、持续性或Elastic Net。

## D. 运行、计数、性能与恢复

公共TaskRunner/TaskScheduler/MonthlyExecutor/TaskJournal及物理fit_id、OS租约、原子提交、spawn池、固定种子、稳定汇总原样复用。RBF配置仍16个retuned_core＋96个fixed_full_params＝112；48候选/任务，12月粗筛，前4全36月复核，47测试月；计划按内部SVC、最终SVC、sigmoid、七SVR和重试展开，完整预算见nontraining_audit.json。

缓存仅原始内折成员推导的变换矩阵与目标编码；M/M+Z不同服务，不缓存估计器。模型身份使用规范dtype/shape/连续数值字节，绑定实际gamma、训练/输入/目标/校准规则与参数。各组件耗时保留在诊断而不进入权重身份。当前修改未进行真实吞吐、内存、cold/warm池或取消恢复测量，因此不报告提速倍数，不推算整轮时长。原有Elastic Net速度实测不能当作SVM性能证据。

## E. 验收与协作边界

新普通pytest禁止真实SVC/SVR、sigmoid optimize和新增Newton polish。测试与无训练preflight记录见acceptance.json、接口test_results.json；桌面CHECK记录见delivery_report.json。后续TECHNICAL_WINDOWS.cmd是显式真实短验收入口，本轮不运行；START_WINDOWS.cmd明确调用rbf_svm配置和完整pipeline，本轮只核对连接与无执行计划。

工作期间观察到其他工作的Elastic Net及公共评分/调度改动，保留原状、不回滚、不归功于本轮。交付内容身份以逐文件哈希为准，不通过修改旧manifest复用历史任务。独立数值优化分支本轮不推送GitHub。历史探针与修复后待验收状态严格分开。

## F. 交付与限制

包中含代码、配置、中文README、CHECK/TECHNICAL/START三入口、锁定依赖及Windows x64 Python3.11离线wheel、原seal和36项数据，不含原始湖、虚拟环境、预测研究结果或虚构权重。Windows系统实际桌面路径和校验见delivery_report.json。桌面仅运行无训练CHECK；真实模型训练、校准、新进程保存加载、真实串并行数值等价、取消后resume和正式B/C均不在本次最终认证范围。

方法核对：[sklearn 1.8 SVM](https://scikit-learn.org/1.8/modules/svm.html#multi-class-classification)、[OVR映射源码](https://github.com/scikit-learn/scikit-learn/blob/1.8.0/sklearn/utils/multiclass.py)、[SciPy停止条件](https://docs.scipy.org/doc/scipy-1.17.0/reference/optimize.minimize-lbfgsb.html)。
