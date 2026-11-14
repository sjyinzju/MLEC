# 复现入口与环境

在当前仓库根目录执行；无需恢复 E:\MLEC。所有新文件写入当前项目。Python 3.11；本轮实际依赖版本见 `requirements-research.txt` 和实验 registry。建议在仓库独立虚拟环境安装，不修改 `E:\quant` 环境。当前全局环境缺 DuckDB，项目 `.local_deps` 已只读复制原环境的 DuckDB 1.5.5 运行依赖供本地审计/旧测试使用，该目录不提交。

## 从已缓存证据离线重建

```powershell
python -X utf8 scripts/experiment_framework/cli.py audit
python -X utf8 scripts/experiment_framework/cli.py govern-macro
python -X utf8 scripts/macro_pipeline/quality.py
python -X utf8 scripts/check_macro_full_gaps.py
python -X utf8 scripts/experiment_framework/cli.py build-dataset
python -X utf8 scripts/experiment_framework/cli.py validate-data
python -X utf8 -m pytest tests/research_v2 tests/experiment_framework -q --junitxml=audit/framework/tests.xml
python -X utf8 scripts/experiment_framework/cli.py benchmark --stage development
python -X utf8 scripts/experiment_framework/cli.py evaluate
python -X utf8 scripts/experiment_framework/report.py
```

同配置、同数据、同代码、同依赖再次 benchmark 时，程序要求已有预测表逐值相同；模型写入后也立即加载核对概率。registry 保留随机种子、数据/特征/代码身份、依赖、训练 ID、内层选择和权重哈希。最终期入口被锁定，不能用一个参数打开 2023+ 选择。

缓存正文在 `.gitignore` 中，保留本地数据包才能离线重建。`data/metadata/raw_source_registry.json` 给出逐文件 SHA256；只有 Git 仓库而没有缓存时需执行下列公开采集命令。网络重采的时间、内容和源站修订可能变化，应生成新版本并重新审计，不能宣称跨时间网络下载逐字节相同。

## 重新采集公开来源

```powershell
python -X utf8 scripts/macro_pipeline/collect.py local
python -X utf8 scripts/macro_pipeline/extend.py nbs --start 2014 --end 2026
python -X utf8 scripts/macro_pipeline/extend.py nbs --start 2014 --end 2017 --topic '非制造业商务活动指数'
python -X utf8 scripts/macro_pipeline/extend.py pages
python -X utf8 scripts/macro_pipeline/extend.py pboc
python -X utf8 scripts/macro_pipeline/extend.py eastmoney
python -X utf8 scripts/macro_pipeline/financial.py rates
python -X utf8 scripts/macro_pipeline/financial.py fx
```

`collect.py local` 使用只读 DuckDB、校验 canonical_parts 的文件哈希，只提取研究相关小表。数据库修改时间/大小与每个源文件哈希记录在 `audit/framework/quant_extraction.json`。NBS/PBOC 保存索引和原 HTML，外汇与利率保存原响应；无 API Key 或账户配置依赖。采集器默认复用已有缓存；如需要更新到新时点，应新建版本目录并更新截至日期，不能覆盖历史证据。

## 市场兼容与迁移

89 个冻结协议/数据/审计产物逐哈希核验，路径适配仅修改根目录定位。旧宏观数据迁移遵循逐文件复制、哈希验证、再移除原副本；`migration.json` 与 `package_migration.json` 可恢复。旧文档原版在不可变快照，旧入口改为指向新数据。课件示例及课题设计文件未迁移。

原市场测试另可单独运行 `python -X utf8 -m pytest tests/research_v2 -q`。新增测试从冻结日度清洗数据重建连续观测、状态/事件、周度特征、目标、映射和时间折，并与原件比较；还验证历史截断和未来价格扰动。没有重新执行全量外部原始行情采集及全部市场审计脚本，不能声称这一层全量重跑。

真实测试结果、重跑对比、完整性验收见 `audit/framework/tests.xml`、`reproducibility.json`、`acceptance.json`。模型权重和原始 HTML 不提交；预测、配置、来源清单和可复现代码保留。未推送远程。

本机测试结束时第三方 pyreadline3 控制台析构有非致命 Windows 清理警告；pytest 实际退出码为 0，JUnit 记录零失败。该警告不影响数值检验，未修改系统控制台库。
