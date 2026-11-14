# 数据重建与复现

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -X utf8 -m scripts.data_foundation_v3.cli audit
python -X utf8 -m scripts.data_foundation_v3.cli migrate
python -X utf8 -m scripts.data_foundation_v3.cli standardize
python -X utf8 -m scripts.data_foundation_v3.cli reconcile
python -X utf8 -m scripts.data_foundation_v3.cli build-features
python -X utf8 -m scripts.data_foundation_v3.cli build-datasets --all
python -X utf8 -m scripts.data_foundation_v3.cli register
python -X utf8 -m pytest tests/data_foundation_v3 -q
python -X utf8 -m scripts.data_foundation_v3.cli validate
python -X utf8 -m scripts.data_foundation_v3.cli verify-lineage
python -X utf8 -m scripts.data_foundation_v3.cli reproduce
python -X utf8 -m scripts.data_foundation_v3.cli register
python -X utf8 -m scripts.data_foundation_v3.cli report
```

联网补数使用 `collect --source snapshot-requests` 重放保存的请求计划；或选择 nbs-directory、financial、pboc-legacy-tsf、pboc-attachments、safe-releases、credit-reprints、mofcom-history。失败请求可重试，成功缓存先校验哈希；线上响应改变时保留新对象，不能声称它与封存快照相同。

任意组合例：`python -X utf8 -m scripts.data_foundation_v3.cli build-datasets --quality conservative --groups growth,prices --series m2_yoy,shibor_1w --name custom_growth_prices_credit`。该命令只组合数据，不做拟合。不要运行旧的全量pytest或benchmark来验证本轮，它们可能包含模型拟合。
定向数据测试：28 项，失败 0、错误 0；证据 audit/data_foundation_v3/data_tests.xml。
实际字节复现状态：**PASS**；比较文件数 87，原始输入文件数 11548。详见 audit/data_foundation_v3/reproducibility.json。

需要Python及requirements-research.txt中的固定版本。旧报价/第三方档案原先依赖文件mtime，现由legacy_retrieval_times.json固定取得时刻。离线重建不会联网，也不会写旧冻结产物。审计运行时刻和registry.created_at不属于字节一致契约；事实、版本、特征、资格表及数据集JSON需要完全相同。

大体积objects、原始交付包和部分旧公告被Git忽略；应按source_manifest列出的路径和哈希整体备份。成功缓存不自动重下，失败重试写独立attempt。每个v3响应上限20MB，v3缓存预算2GB、剩余磁盘低于5GB停止，既有缓存不自动删除。
