# 公共预处理与 Elastic Net 数值修复

输入实现版本 `semantic-inputs-v2`，运行底座 `experiment-runtime-v2`；研究协议、四市场、未来20交易日、三类字典、七目标、时间成员及36项封版产品不变。原seal SHA256为 `728d7adb6305f4951281c800c16508aa3fa1565e52dfbfd7e96f655100acce8f`。

## 已实际复核的输入尺度

四市场分别读取2020-01与2022-12成熟train，M/M+Z各一组，共16个输入视图。逐列统计、原概率IQR/方差/范围、变换后范数、矩阵秩、七目标变换及预测输入诊断见numerical_inputs.json。独立拟合M与从M+Z限制到M逐元素完全相同。

| 市场 | 月份 | 原M+Z最大绝对输入 | 新最大绝对输入 | 原最大行平方范数 | 新最大行平方范数 |
|---|---|---:|---:|---:|---:|
| 000985.SH | 2020-01 | 8235800.7 | 15.811388 | 2.2781504e+14 | 2140.9631 |
| 000985.SH | 2022-12 | 2276080.1 | 19.974984 | 1.9816966e+13 | 1581.6956 |
| 000300.SH | 2020-01 | 1990673.1 | 15.811388 | 1.5139523e+13 | 2140.3139 |
| 000300.SH | 2022-12 | 360188.98 | 19.974984 | 5.0258854e+11 | 1622.6585 |
| 000905.SH | 2020-01 | 1075391.5 | 15.811388 | 3.5966771e+12 | 2142.7293 |
| 000905.SH | 2022-12 | 239034.67 | 19.974984 | 2.2539853e+11 | 1578.2152 |
| 000852.SH | 2020-01 | 1052261.4 | 15.811388 | 3.2806767e+12 | 2139.9968 |
| 000852.SH | 2022-12 | 83029.865 | 19.974984 | 2.4492747e+10 | 1589.4996 |

全指初始训练窗口：原prob0 IQR为1.214211e-7，状态概率原值仍在[0,1]；旧变换最大约824万。相同技术参照C=1e-4、l1_ratio=.05下，按本地sklearn 1.8 SAGA公式，步长从约8.779e-15增至5.813892e-4。这是输入条件和公式对照，不是预测增益。

普通连续列先以当前train中位数填补，再以填补后训练均值/总体标准差变换；概率及其滞后保留自然尺度。二值列缺失使用训练众数，同频取0，避免填成0.5；二值、one-hot及缺失指示保持0/1。current_state_id及滞后仍按训练类别作名义one-hot，固定MISSING/UNSEEN，不解释为有序风险。

全空、恒定值列删除但保留缺失标记。近常数按StandardScaler浮点误差界 `var <= n*eps*var + (n*mean*eps)^2` 识别，不按绝对单位阈值删除小尺度变量。本次八个M+Z窗口识别到同一近常数宏观变化列 `macro__rmb_loan_balance_yoy__definition_loan_pre_201501__change`，因此M+Z维度比旧版少1；金融M的变换仍严格配对。所有连续极端值保持原信息，不做全局截断或按测试表现删特征。无穷输入（包括名义状态）明确拒绝。

schema记录逐列类型/策略、观测/缺失数量、填补、训练均值/方差、center/scale、例外列、dtype/列序、训练上下文及schema_version。预测不重新拟合。保存/加载同时核对JSON、实际参数及内容身份。原目标适配器的训练中位数/IQR、五维权重、原单位逆变换、固定initial评价尺度均未更改。

## 分类验收与补救

当前默认class_weight=null。独立计算每类平均训练概率减训练类别频率；同时检查零系数、按训练频率设置截距的可行解目标值，以及含L1次梯度和L2梯度的KKT残差。对balanced权重也有对应加权检查，默认研究规则不变。

与sklearn 1.8一致的目标为：`mean(weighted NLL) + [l1_ratio*sum(abs(W)) + (1-l1_ratio)*sum(W^2)/2]/(C*n)`；截距不惩罚。基准为训练加权类别频率的熵。梯度/截距阈值事先固定为max(1e-5,10*tol)，当前tol=1e-4时为1e-3；目标允许量仅max(1e-10,tol*max(1,基准目标))。这些阈值不使用验证/测试成绩。

SAGA以训练频率截距、零系数作为可行起点，随后仍优化指定C/l1_ratio的完整模型。10k首次预算后，最多一次同参数/同种子的40k暖启动续解，并把求解tol收紧10倍；独立验收标准不放宽。仍失败的候选无效，不回退为基准预测器，不因宏观负增益重调。

旧版隔离技术例已复现正常返回但截距残差0.501959873，见baseline_solvers.json；因此“无警告、系数有限”不足以确认优化合格。均匀三类概率Log Loss参考为ln(3)。

## 七目标回归验收

保留七个独立Elastic Net目标、共同alpha/l1_ratio及原目标变换。独立重算 `mean(r^2)/2 + alpha*l1_ratio*L1 + alpha*(1-l1_ratio)*L2_squared/2`，同时核对训练截距残差及仅截距可行目标。

真实小样本表明：修复输入后，原cyclic求解50k仍可出现gap约0.09659（M）/0.01409（M+Z），阈值约0.0001497。LARS单独求解也会因相关特征出现早停；因此不能把所有失败归因于IQR，或只增大迭代上限。

新版将中心化设计增广为 `[Xc; sqrt(n*alpha*(1-l1_ratio))*I]`，目标增广零行；使用sklearn LassoLars，Lasso惩罚映射为 `n*alpha*l1_ratio/N_aug`。增广Lasso目标乘N_aug/n严格等于原Elastic Net目标，截距恢复为mean(y)-mean(X)w，特征、样本语义和原正则参数不变。七目标共享同一训练设计/Gram工作区。

若LARS解未通过独立验收，含L2时在Fenchel对偶上进行最多200步半光滑Newton和有界Armijo回溯。对偶约束sum(theta)=0；w=soft(Xc.T theta, alpha*l1_ratio)/(alpha*(1-l1_ratio))；对偶gap恒等为 `||n*theta+Xc*w-yc||^2/(2*n)`。纯L1则求解最多2000步的约束对偶QP（SciPy SLSQP），约束 `abs(Xc.T theta)<=alpha`，从乘子恢复原特征系数，并重新构造严格可行证书。QP返回状态8等原始信息完整保留，只有独立原目标gap通过才接受；不凭求解器成功标志判定合格。仍未通过时有界暖启动cyclic续解，不跳过目标。

独立质量模块从原X/y/系数重新算primal及证书dual，同时保留增广Lasso gap；对偶证书与训练键绑定，可由solver_certificates.parquet和模型系数重算，不使用评分Y。初始全指M/M+Z弱正则alpha=1e-5、l1_ratio=.05的14个目标全部通过，七目标分别约0.41/0.62秒。另以原候选表中的最低纯L1 alpha=5.945570708544395e-5，在全指/沪深300初始窗口及全指2022-12的M/M+Z共42个目标全部通过，最大gap约4.08e-10；这些都是技术验证而非正式B/C。

gap阈值为 `tol*mean((y-mean(y))^2)`；浮点余量为100*eps*max(1,primal,训练中心二阶矩)，报告gap与独立gap需在10倍浮点余量内一致；截距阈值为1e-8*max(1,std(y))。记录每个目标的n_iter、实际tol、预算、gap、KKT及每次补救。候选搜索仍为32粗筛/前4完整复核，范围和种子未变。旧8个回归获胜者7个alpha=10，不据此固定新alpha；旧逐目标诊断缺失，不能断言118个失败全部由IQR造成。

公式和API依据：[sklearn ElasticNet目标函数](https://scikit-learn.org/1.8/modules/generated/sklearn.linear_model.ElasticNet.html)、[LassoLars](https://scikit-learn.org/1.8/modules/generated/sklearn.linear_model.LassoLars.html)。对偶恒等式另由解析梯度/Hessian及一维闭式解测试验证，普通pytest不执行真实监督优化。

SLSQP显式约束乘子采用先等式、后不等式的API顺序；ftol控制求解内部停止条件，不能替代原目标的独立证书验收。依据：[SciPy 1.17 SLSQP文档](https://docs.scipy.org/doc/scipy-1.17.0/reference/optimize.minimize-slsqp.html)、[固定1.17.1源码](https://github.com/scipy/scipy/blob/v1.17.1/scipy/optimize/_slsqp_py.py)。

## 模型身份与兼容性

旧真实模型的joblib对象哈希在保存/加载后不一致已复现。新版对coef/intercept/classes/n_features的规范数值内容（dtype、shape、连续字节）计算身份，并绑定训练上下文、预处理、目标适配、参数、种子和策略。模型包校验适配器/求解质量模块/接口代码哈希及sklearn、SciPy、NumPy、pandas、joblib版本；不依赖未登记的运行时hash补丁。

公共预处理升级按原机制重新验收接口与测试，不改原seal或标签。RBF-SVM继续调用同一工厂，在内部train独立拟合，训练方差gamma和时间校准规则不变；仅补充公共资源/中断异常的分类。旧输入schema/模型包和锁不得复用。本轮没有RBF-SVM、Random Forest或CatBoost真实训练。

真实求解和串并行指标在本报告最后的验收结果及technical_acceptance.md记录；技术数值不作为宏观效果证据。

最终同一24任务/模式的真实验收通过，合计48项月任务、192次估计器拟合。新版分类最大截距残差0.000986582，全部可行目标/KKT检查通过；七目标回归最大独立gap1.25654e-5，各目标均满足其训练尺度阈值。保存加载预测完全相同，串并行预测最大差0，评分与排名一致。详见real_technical.json，不以该技术样本推断正式搜索失败率或宏观预测效果。
