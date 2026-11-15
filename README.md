# ECON3059 中国宏观信息与A股风险状态研究

当前数据版本 `unified-data-foundation-v4.0.0` 的验收为 **INCOMPLETE — DATA FOUNDATION NOT FULLY ACCEPTED**。双域数据已完成本轮补充、修复和逐项复核，但尚缺完整有效成分与权重、部分宏观原始版本/观测，以及少量未决价格、复权与股本口径证据。不能把技术测试通过理解为数据全部认证。

冻结协议 `market-research-v2.0.0` 的599个候选时点、原标签、阈值、fold及既有模型成果保留。本轮只做数据工程，未运行模型训练、Benchmark或预测。

- [统一最终验收及12项回答](reports/data_quality/final_data_acceptance.md)
- [金融市场审计](reports/data_quality/final_market_data_audit.md) · [宏观逐期审计](reports/data_quality/final_macro_data_audit.md)
- [完整数据目录](reports/data_quality/full_research_data_inventory.md) · [跨域验证](reports/data_quality/final_cross_domain_validation.md)
- [数据架构](docs/data_architecture.md) · [契约](docs/research_data_contract.md) · [字典](docs/research_data_dictionary.md)
- [来源与版本](reports/data_quality/source_and_vintage_validation.md) · [剩余限制](docs/remaining_limitations.md)
- [离线复现和统一接口](docs/data_reproducibility.md)

```powershell
python -X utf8 -m scripts.final_data_foundation.offline --run-name user_reproduction_01
python -X utf8 -m scripts.final_data_foundation.validation
python -X utf8 -m scripts.final_data_foundation.issues
python -X utf8 -m scripts.final_data_foundation.reporting
```

依赖见 `requirements-data-v4.txt`。已有运行名用于断点续作；全新重演用新的英文运行名。新权威入口由 `data/metadata/dataset_registry.json` 指定；旧v3数据保留作不可变输入，旧注册表和入口文档逐字节归档于 `data/archive/data-foundation-v3`。

大规模原始市场快照、标准化市场分区、临时文件和复现前镜像仅保留本地，不直接放入Git。异机离线复现必须同时提供清单对应的本地文件及其SHA-256；仅克隆代码不能凭空恢复来源快照。`E:/QuantData` 与 `E:/quant` 全程只读。
