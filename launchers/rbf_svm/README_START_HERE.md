# RBF-SVM 审计修复交付（2026-11-20）

当前状态：**AUDITED_PENDING_REAL_REVALIDATION**。按用户后续“不运行模型”要求，本次修复后只做非训练验证，没有完成真实SVC/SVR、校准、保存加载和spawn实测验收，不能宣称已达到RBF_SVM_READY_FOR_FORMAL_BC。停止指令前2个基线技术探针的记录随包保留，不是修复后效果证明。

完整解压后，先运行 **CHECK_WINDOWS.cmd**：环境、逐文件哈希、原seal及36项研究产物、接口、配置和全量无训练preflight。这个入口不会训练模型。

以下两个入口会训练，本轮没有运行：

- TECHNICAL_WINDOWS.cmd：显式短真实验收，仅SMOKE_ONLY，不进入正式B/C。建议参数 -CpuWorkers 2。
- START_WINDOWS.cmd：RBF-SVM完整B→开发验证→锁→C→评分报告。当前仍建议先完成前述真实技术验收再正式启动。

需要Windows x64 Python3.11。可设置MLEC_PYTHON为已有合格环境python.exe，或传入-Python；否则自动建立.venv-rbf-svm。存在wheels目录时使用离线wheel安装锁定依赖，否则首次安装需联网访问PyPI/镜像。Linux入口为bash START_LINUX.sh（启动后会训练；本轮仅检查语法）。

Windows参数示例（以后明确训练时使用）：

```cmd
TECHNICAL_WINDOWS.cmd -CpuWorkers 2
START_WINDOWS.cmd -CpuWorkers 4 -OutputRoot "F:\MLEC_Results"
```

默认结果为results/rbf_svm/<run_id>/，支持-DataRoot、-OutputRoot、-CpuWorkers、-CpuThreads、-RunId。中断后保留完整目录，原包/研究设置不变时resume，成功任务按哈希核验后复用；不要改写锁或旧manifest。

请返还完整run目录（配置、环境、preflight、任务、selection.lock.json、development/test、逐样本预测和损失、模型包、表图和logs）。完成标志是manifest.json的EXPERIMENT_COMPLETE；当前包的构建状态不是正式运行成功标志。

没有原始E盘数据库依赖，不包含原始A股数据湖、虚拟环境或训练权重。文件清单为package.manifest.json。代码身份与原始数据seal独立管理。真实求解成功、概率可靠性和宏观增益不得从普通pytest推断；细节见docs/rbf_svm.md和reports/model_build/rbf_svm/optimization_20261120/audit_report.md。

主要研究限制：训练和OOF中极少的下跌/上涨类别、OVO投票映射得到的OVR分数并非独立几何距离、逐类sigmoid再归一化不保证多类校准、历史重建宏观可得性限制。正式B/C未执行，也未据测试期成绩调参。
