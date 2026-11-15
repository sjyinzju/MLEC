# 维护与验证

本项目交付处理后的研究数据库，不保存原始 API 响应、网页、请求日志和 before/after 备份，不承诺逐字节离线重建。早期 offline 全流程需要已删除的原始依赖，不能当作当前一键重建命令。

在当前仓库根目录可运行：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m scripts.final_data_foundation.practical_validate
python -m scripts.final_data_foundation.final_delivery
```

第一条对完整标准表、派生公式、时点接口与冻结哈希复核；第二条刷新精简注册/字典/完整性资料，不训练模型。实质缺口结论另见 remaining_gaps.json，技术通过不意味着 DATA READY。

日常读取见 README 的 load_dataset 与 load_index_members 示例。维护采集/修复代码在 scripts/final_data_foundation，定向更新须先核查具体来源和统计范围，不能无条件重跑旧迁移/备份流程。联网采集需要相应数据源权限。E:/QuantData 与 E:/quant 为只读外部来源。
