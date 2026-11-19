# 下一轮正式实验

本轮只做技术验收；没有重新执行正式完整 B+C。研究协议、四市场、未来20交易日、三类字典、七目标、样本/时间/宏观信息集和原数据 seal 均保持不变。

先准备 **Windows x64 Python 3.11**。解压完整交付目录，双击 `CHECK_WINDOWS.cmd`，只安装独立环境、校验文件和预检，不训练。`TECHNICAL_WINDOWS.cmd` 明确执行短小真实技术检查，也不启动完整研究。Linux 检查入口为 `bash CHECK_LINUX.sh`（Linux 依赖需联网安装）。

短验证为比较串行/多进程，需要至少2个worker。若自动资源策略降为1，先释放内存，再执行 `TECHNICAL_WINDOWS.cmd --cpu-workers 2`；本机桌面已按此命令通过真实验收。正式运行的自动资源限制继续保留。

确认环境后，双击 `START_WINDOWS.cmd`，自动执行 full：完整 B 的32候选粗筛→前4名全36月复核→验证并生成新锁→C→评分与报告。中断后再次执行同一入口即可安全续跑。不得复制第一轮 run_id、锁、任务或权重到新结果目录。

可指定进程和输出位置：

```powershell
.\START_WINDOWS.cmd -CpuWorkers 4 -CpuThreads 1 -OutputRoot D:\MLEC-results
```

默认 `CpuWorkers=0` 根据 CPU、当前可用内存选择1..8进程，每任务1线程；七个回归器在各任务内串行，使用CPU，不使用GPU。不同机器以实际内存为准，不要同时开启多套完整实验。worker数可以在恢复时改变；线程、模型参数、数据和实现身份改变时必须使用新运行身份。

本优化版运行中调整workers：在原终端按一次Ctrl+C并等待工作进程退出，保留输出目录和原RunId，再用相同入口/参数恢复，仅改变CpuWorkers。不要强删锁或同时启动多个实例。该规则不允许把第一轮旧实现的任务续接到本版。

等价命令（已安装依赖后）：

```powershell
.venv\Scripts\python.exe -m scripts.market_state.experiments pipeline --model elastic_net --config config/experiments/elastic_net.yaml --suite full --execute --resume --cpu-workers 0 --cpu-threads 1
```

需要仅做 core 时明确使用 `--suite core`。core 完成不等于96个固定参数分组配置已完成。full 包含16个核心和96个固定参数分析配置；这些是分析配置数，不是估计器调用数。任务量用 `plan --suite full` 查看，耗时应结合本轮真实技术基准及目标机器估算，不能承诺与旧机8.73小时相同。

本次full计划在不计重试时最多24,368个物理月任务、71,576次估计器拟合，实际可因身份复用/无效候选而减少。测机14逻辑CPU、约31.5GiB内存，24项混合技术任务串行43.62秒、4进程23.33秒；若仅按月任务数粗线性换算约6.6小时，但正式分类/回归比例、纯L1病态程度、后续窗口、磁盘与报告成本都不同，这不是完整运行预测。资源安排建议按数小时级计算并预留一晚至一天，实际以运行日志为准；不使用GPU。默认每进程预留1.5GiB可用内存并另留2GiB系统余量，当前可用内存不足时自动减小worker。

数值规则在实现和任务诊断中登记：分类使用训练类别频率截距可行起点，并独立验收截距一阶条件、同尺度惩罚目标和KKT残差。七目标回归保持原目标，使用等价增广Lasso/LARS及有界对偶精化（含L2用半光滑Newton，纯L1用约束QP），独立验收原坐标primal/dual gap并保存证书；仍不合格才暖启动cyclic求解。所有补救保持同参数、同种子，验收阈值不放宽。不能因为得分低或宏观负增益而重调。旧锁因预处理/实现身份变化而失效。

2023年以后第一轮测试结果已被查看。后续新版结果必须标注为“已知实现问题修复后的复算”，不得称为首次未查看的独立样本外测试。不能利用这些旧测试结果选择参数、数值阈值或期望宏观增益方向。

离线依赖说明：交付中的 `wheels/` 仅对应 Windows x64 CPython 3.11，`START_WINDOWS.cmd` 会优先离线安装。不包含 Python 解释器本体。其他 Python/系统需自行联网安装锁定依赖，或在相同平台上执行 `python -m pip download -r requirements-experiments.txt --only-binary=:all: --dest wheels` 后复制。安装失败时保留终端信息，修复解释器/磁盘/依赖后重试；不要跳过预检。

公共预处理额外规则：二值缺失使用训练众数，同频选0，避免中位数产生0.5；连续/概率仍使用训练中位数填补。名义状态的正负无穷明确拒绝，缺失仍用MISSING编码。
