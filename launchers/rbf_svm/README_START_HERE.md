# 同伴：RBF-SVM 一键运行

本包处于 **IMPLEMENTED**：含RBF-SVC时间校准、七目标SVR和完整B→自动锁→C→评分表图报告。制作时真实监督拟合、校准优化、搜索、smoke、正式BC均为0。启动文件会真实训练，无需中途手工选参。请完整解压至可写目录后启动。

需要 **64位Python 3.11**。首次安装锁定依赖须联网访问PyPI或预先配置镜像；包内不含Python安装程序、离线wheel或虚拟环境。Windows安装Python时启用PATH；Linux安装Python 3.11及venv模块。

Windows双击包根`START_WINDOWS.cmd`；Linux执行`bash START_LINUX.sh`。脚本检查环境，默认建立独立`.venv-rbf-svm`，安装缺失锁定依赖，执行预检再自动运行。合格环境可通过Windows的`-Python "C:\env\Scripts\python.exe"`或Linux的`MLEC_PYTHON=/path/to/python`复用。环境失败会提示修复方法，修复后重新启动即可。

默认CPU并发按CPU与内存选择1..8个进程，每进程1线程、256MiB核缓存。四市场、两任务、112个分析配置；48候选粗搜索、前4名全36月复核；每次分类含训练内多折SVC与逐类sigmoid，因此实际拟合远多于112次。请准备充足运行时间、内存和磁盘，不需要GPU。

```cmd
START_WINDOWS.cmd -CpuWorkers 4 -OutputRoot "F:\MLEC_Results"
```

```bash
bash START_LINUX.sh --cpu-workers 4 --output-root /mnt/results
```

支持Windows的`-DataRoot`/`-CpuThreads`/`-RunId`，Linux的`--data-root`/`--cpu-threads`/`--run-id`。数据根应含feature_sets.json与release/seal.json；默认包内数据齐全，不需要访问E:\MLEC或E:\QuantData。

默认结果在`results/rbf_svm/<run_id>/`，可指定外置结果盘；与Elastic Net分开。`manifest.json`中`state=EXPERIMENT_COMPLETE`表示完整成功。中断后保留整个目录，使用相同包和研究设置重新启动，自动核验成功任务并恢复；不要改旧manifest或锁。失败月份不会被删除后冒充完整结果。

**请返还整个run目录**：manifest/config/environment/preflight、selection.lock.json、tasks.parquet、development和test全部子目录、逐样本预测/损失、保留模型包、tables、figures、report.md及logs。不能只返还截图或几张成绩表。

只做无训练检查（先准备依赖）：

```bash
python -m scripts.market_state.experiments preflight --model rbf_svm --config config/experiments/rbf_svm.yaml --suite full
```

package.manifest.json逐文件绑定SHA-256、原seal、验收身份、基线提交与实际内容身份。制作方已用独立非E盘解压目录检查清单、原seal、读取、配置展开和无训练preflight。人工桩验收不表示真实求解器已收敛或已证明真实串并行数值一致。详细规则见docs/rbf_svm.md。
