# 统一模型与实验接口

```python
from scripts.experiment_framework.dataset import load_dataset
from scripts.experiment_framework.models import RiskModel
d = load_dataset('common_core_v1', 'M_plus_Z_core', 20, 'dev-2020', 'train')
model = RiskModel('logistic', {'C': .1, 'penalty': 'l2'})
model.fit(d.X, d.y, {'fit_cutoff': d.fold_metadata['fit_cutoff']})
```

Dataset 返回 X、y、样本元数据、特征名、真实特征可得时间、时间折元数据、数据/特征/协议哈希。读取时核验所有注册产物哈希，核对标签成熟、特征可得时间及 2023+ 隔离。元数据不混入 X。

`RiskModel.fit/predict_proba/save/load` 对历史概率、Logistic、Random Forest、Gradient Boosting 共用。保存模型保留特征顺序；加载后预测逐值验证。单类别训练折及全常数输入回退训练期历史概率，并记录原因。没有 XGBoost 依赖，使用 sklearn GradientBoostingClassifier。

时间划分完全读取原 `fold_membership`。外层是 2020/2021/2022 三个年度扩展开发折；内层为外层训练集最近三个可行年度扩展折，训练标签必须在内层 cutoff 前完全成熟。超参按内层样本加权 Brier 选择，每个可调模型固定 4 个配置；随机种子 3059、CPU 单线程、RF 浅树。禁止随机拆分和 2023+ 参数选择。

主要概率是原生未校准概率。另在外层训练集的所选参数内层 OOF 上训练 sigmoid 校准器，仅作诊断列；这与超参选择共用了内层折，不应解释成完全独立校准验证。模型比较不能事后挑选哪个概率列更好。

`experiments/registry/<run_id>.json` 记录配置、依赖、代码哈希、超参/每折选择证据、训练 ID、模型哈希和预测哈希。权重在 `artifacts/models/<run_id>/`，概率在 `experiments/predictions/`，指标/逐事件/可靠性/解释性结果在 `experiments/metrics/`。run_id 由配置、数据、代码和依赖身份构成；同身份重跑要求预测表逐值相同。不同版本结果保留，`latest.json` 指向当前交付。

配置入口 `config/experiments/development.json`，FeatureSet Registry 独立于算法。更换组和算法不需另写处理流水线。外层运行自动为每个共同样本版本训练 M 基准，配对比较强制相同样本键、标签、cutoff、asof、协议和样本版本。
