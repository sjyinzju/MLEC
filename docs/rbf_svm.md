# RBF-SVM 构建与同伴运行

2026-11-20更新：使用semantic-inputs-v2 / experiment-runtime-v2底座。当前修复状态为 **AUDITED_PENDING_REAL_REVALIDATION**。用户随后明确要求不运行模型，因此修复后未进行真实求解、校准或桌面技术训练，不能声明RBF_SVM_READY_FOR_FORMAL_BC。停止指令之前完成的2个技术探针单独记入optimization_20261120/baseline_probe.json，不代表修复后验收。完整自查及预期行为见reports/model_build/rbf_svm/optimization_20261120/audit_report.md。

以下早期IMPLEMENTED/零训练描述属于2026-11-18构建阶段记录；本次状态以上述补记为准。

状态 **IMPLEMENTED**。本次仅构建；真实监督估计器拟合、sigmoid优化、搜索、smoke和正式BC运行均为0。数据、标签、GMM及原seal不变。Random Forest、CatBoost仍未实现。入口：

```bash
python -m scripts.market_state.experiments pipeline --model rbf_svm --config config/experiments/rbf_svm.yaml --suite full --execute --resume
```

此命令由同伴以后显式执行，自动完成预检→48候选粗搜索→前4名全36月复核→完整开发及分组→验证开发锁→47个测试月→评分、三张核心表、宏观组表、预警表、质量/覆盖/逐样本明细及报告。失败月份不从分母删除；没有合法完整候选或选定任务失败时停止。测试只按月加入已成熟标签更新权重，不重新选择规则。

## 时间校准

`TrainingPartitions`只绑定当前外层成熟train Dataset的原始X、Y及metadata，不持有DataStore或外层validation/test。以最早训练日期所属的周六至周五日历周起点为原点，先留13周，随后每26周形成验证块，末块可不足26周。内部cutoff是块起点前一日北京时间18:00。内部训练同时满足asof_time及实际label_available_at不晚于cutoff；验证日期属于该块且仍是外层train成员。全部调用既有`training_partition()`。

内部训练至少8行、每个字典类至少1行；不满足则明确跳过该块，无随机补样或算法回退。块日期与支持只取决于训练成员及标签，M/M+Z及全部信息集相同。至少2个合法块、26条不重复OOF行，每类正例和负例均至少2条；否则整个外层任务失败。少于20个正例或负例明确标为LEGAL_BUT_SPARSE_UNSTABLE，合法不等于校准可靠，不从未来补样。实际最早开发train中上涨类集中在2015年，长达两年的初始段会消耗其全部OOF支持；13周起始规则仅依据这些训练标签确定，未读取外层评分标签。所有月份支持在无训练preflight中逐一核验。

每个合法内折从原始X重新`fit_inputs()`及`fit_targets()`，拟合`SVC(kernel='rbf', probability=False, decision_function_shape='ovr', shrinking=True, break_ties=False)`。多类分数按内部类别重排到字典顺序；二类单一margin展开为`[-margin,+margin]`。不使用SVC内置概率或普通随机CV。

OOF分数逐类拟合Platt sigmoid：正例目标`(n_pos+1)/(n_pos+2)`，负例`1/(n_neg+2)`；分数除以`max(1,max(abs(score)))`以控制优化量级。以斜率0和`log((n_pos+1)/(n_neg+1))`截距初始化，最小化稳定的二元交叉熵和解析梯度。SciPy 1.17.1 L-BFGS-B，maxiter=1000、ftol=1e-12、gtol=1e-8、maxls=50，v2增加独立原目标/梯度检查（梯度上限仍为1e-8），必要时最多20步同目标阻尼Newton与每步30次有界回溯；最终未通过则整个任务失败。输出expit逐列限制至`[1e-15,1-1e-15]`后除以行和，这是校准定义的一部分。最终类别仅来自最终概率argmax，平局按字典顺序。

校准完成后在完整外层成熟train重新拟合相同输入预处理及最终SVC。最终模型包绑定时间块、内折schema、实际gamma、校准参数、优化诊断、最终SVC及版本；加载拒绝代码、依赖、schema或内容变化。预测不接收真实Y。

## 参数、回归与身份

分类与回归各预生成48个去重候选。C以geomspace覆盖1e-3..1e3，固定种子3059打乱均衡分配的gamma因子0.01/0.1/1/10/100；回归同时打乱geomspace的epsilon=0.001..1。配对信息集使用同一列表。七个SVR共享候选，依既有`fit_targets`变换分别拟合return、volatility、drawdown、amihud、turnover、breadth、correlation；原单位逆变换保留全部目标，边界违反只记录不裁剪。

每个内外训练折单独计算`gamma = factor/(n_features * population_variance(X_train))`，其中variance取预处理训练矩阵全部元素；方差精确为0时默认base=1。固定参数对照固定相对factor，输入信息集改变时重算绝对gamma。实际数值保存，不引入外层数据。

粗搜索12个月（2020—2022每年1/4/7/10月），前4名完整复核36月并复用身份相同任务。分类Log Loss、回归固定初始尺度五维等权平方损失按实际评分周平均。平局先较小C、较小gamma factor、回归再较大epsilon，最后candidate_id。tol=1e-3，max_iter按100000→400000有限重试一次，参数与种子不变；单个外层任务最多2次，数值失败不接受，失败/重试全部留存。SVC关闭内置概率且时间校准确定，分类和回归均只运行种子3060；候选及Bootstrap仍固定种子。

四市场×两任务×M/M+Z为16个retuned_core；四市场×两任务×12信息集为96个fixed_full_params，共112个带模式分析配置。plan另外列出每市场/月的内部SVC、最终SVC、3个sigmoid和7个SVR的物理fit上界及重试展开；112不是fit次数。

数据seal、接口身份、实验代码身份独立核验。新增实现位于models/experiments子包，既有根接口代码未变；仍调用`assert_interface_accepted`。完整普通pytest刷新当前实验测试身份，所有真实预测估计器及sigmoid优化在pytest中被禁止，只用非学习桩。既有完整run可以显式`summarize --run <目录>`，不得跨版本恢复旧任务、修改旧manifest或自动迁移同伴结果。

## 调度、资源与恢复

串行和Windows/Linux spawn多进程共用TaskRunner。`--cpu-workers 0`按CPU和当前可用内存自动选择1..8个进程，每进程预留1.5GiB加核缓存，保留2GiB系统余量；可显式覆盖。SVM默认每进程1线程、核缓存256MiB（配置允许1..1024MiB）、变换LRU上限2个完整市场/任务/月上下文，七目标串行。每进程只读DataStore独立缓存。输入行序、候选、时间、种子、数值库和求解设置固定。

同批任务按物理fit_id去重，物理fit持有进程退出即释放的OS租约；先完整写同卷临时目录再原子提交。各任务记录由所属worker写，公共tasks.parquet、阶段状态、搜索、排名及锁仅由协调进程稳定汇总。粗搜索→复核→锁→测试保留依赖。每批及每个任务检查磁盘；并发时最多已在途批次可能超出预算，触限停止且不删除数据。中断后重做未完成任务，成功任务逐文件核验后复用；已失败估计器不在恢复时无限重试。无法确定被中断期间真实fit数时明确标unknown。

worker数量、数据/结果路径和缓存/磁盘上限是操作设置，可以恢复时改变；线程数和核缓存、模型/校准/研究规则属于身份，改变后不能混用任务。原Elastic Net配置仍默认单worker/每任务2线程，并可通过相同公共调度显式增加worker；不自动重跑或搬迁既有结果。测试桩验证调度与数值计算程序，不证明真实求解器已成功收敛或真实串并行数值完全相同。

## 交接与环境

仓库直接使用`launchers/rbf_svm/START_WINDOWS.cmd`或`bash launchers/rbf_svm/START_LINUX.sh`。SVM便携包会把这三个文件映射到包根（含README_START_HERE），不覆盖仓库原Elastic Net启动文件。Windows支持`-Python`复用合格环境，或建立独立`.venv-rbf-svm`；Linux可设`MLEC_PYTHON`。要求64位Python 3.11；首次安装需要联网访问PyPI或配置镜像，锁定依赖见requirements-experiments.txt和requirements-research.txt。已有合格环境不重复安装。

```cmd
START_WINDOWS.cmd -CpuWorkers 4 -OutputRoot "F:\MLEC_Results"
```

```bash
bash START_LINUX.sh --cpu-workers 4 --output-root /mnt/results
```

支持DataRoot/`--data-root`指向包含feature_sets.json和release/seal.json的只读数据根。默认输出`results/rbf_svm/<run_id>/`，完成标志manifest.json中的`state=EXPERIMENT_COMPLETE`。中断后保持包与研究设置相同，重开同一入口自动resume。请返还完整run目录，包括manifest、锁、任务、开发/测试、逐样本预测/损失、模型包、表图及日志。

包内包含原seal及其36项研究产物、代码、配置、锁定依赖、协议/规划/契约、测试及验收身份；不依赖原E盘或原始湖。package.manifest.json绑定每文件SHA-256、基线提交和实际实验代码内容身份。解压后的无训练preflight核验全部数据、读取与配置。包制作和验收不产生权重或研究成绩。真实smoke如将来需要，必须独立显式授权；不随安装、导入、plan、preflight、package或pytest触发。

API依据：[SVC 1.8](https://scikit-learn.org/1.8/modules/generated/sklearn.svm.SVC.html)、[SVR 1.8](https://scikit-learn.org/1.8/modules/generated/sklearn.svm.SVR.html)、[SciPy L-BFGS-B](https://docs.scipy.org/doc/scipy-1.17.0/reference/optimize.minimize-lbfgsb.html)。

## 公共输入升级兼容性（2026-11-19）

公共FoldPreprocessor已升级semantic-inputs-v2；SVM继续在每个内外训练折调用fit_inputs/transform_inputs，训练方差gamma规则及时间校准不变，自动使用新schema和接口代码身份。旧预处理/模型包因代码与schema身份不同被拒绝，不迁移旧权重或校准器。本轮只复核SVM接口、配置和既有非训练测试，不进行其正式搜索、校准训练或专项优化。

本次新增预测数值状态内容哈希，覆盖LIBSVM公共和私有预测系数、支持向量/索引、类别、截距、gamma及影响预测的参数，另绑定输入、目标、校准参数和训练上下文。诊断耗时不参与模型身份。独立训练期SVC逐OVO/SVR对偶约束与KKT检查以2*solver_tol+1e-8核验（LIBSVM停止区间加双精度核复算余量），未改变solver_tol；这不是全局泛化证明。修复后的真实LIBSVM验证仍待授权。

内部时间折矩阵来自各自原始内部train的预处理，在每个绑定训练服务内按训练/验证键与cutoff缓存，上限64MiB；每个外层上下文只保留最近2个信息集服务，外层LRU仍2个上下文，新增矩阵缓存上界256MiB。没有缓存或共用估计器权重。

桌面包CHECK_WINDOWS.cmd只检查环境/文件/seal/配置/preflight；TECHNICAL_WINDOWS.cmd将真实运行短技术训练；START_WINDOWS.cmd将真实启动完整BC。本轮仅执行CHECK，后两入口不执行。依赖优先复用MLEC_PYTHON指定的合格环境，或创建独立venv，包内wheels存在时优先离线安装。
