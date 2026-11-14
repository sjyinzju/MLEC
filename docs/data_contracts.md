# 数据契约

版本：data-foundation-v3.0.0。source_record_id唯一；同一series_id/period_end允许多个来源与vintage。三个时点字段使用Asia/Shanghai时区，统计区间字段是自然日期。发布日未知的版本禁止倒填历史日期。日期明确、时刻不明时统一23:59:59，当日18:00周度预测不得使用该公告。

结构性缺失只在有制度依据时标记：工业/零售不拆1—2月当月值，累计类不虚构1月；旧/新M1按制度期分开；新LPR实施前、DR设立前不造值；早期社融存量按公布制度。海关合并快讯不等于独立月份不存在，因此贸易1—2月未按该理由抹去缺口。

质量等级由 config/data/quality_levels.json 给出。blocked不进入任何特征；latest_at_retrieval也必须满足真实可得约束，因采集晚于冻结研究末期，未认证历史表不会突然成为历史特征。strict指公告证据准入，不声称历史修订全集已完整。

按预测时点先筛available<=asof，再在每观察期选择最新已知版本，最后选最近两个不同观察期。同一时刻先按质量、再按稳定ID处理重复；同一时刻已认证值冲突则隔离。过期阈值：日10天、月75天、季150天，按观察期末距asof计算。没有未来回填、零填补、全样本插补或标准化拟合。

所有数据集保留原599行市场样本；标签与71,544行时间折使用冻结权威路径。M与M+Z必须复用同一信息集资格掩码和原fold_membership，不能分别dropna。存储2023+冻结标签是数据保全，不是执行最终实验。特征文件不含目标列，构造宏观特征不读取标签。

来源冲突有EXACT_MATCH、ROUNDING_ONLY、DATED_PUBLICATION_VERSION_DIFFERENCE、SEMANTIC_ERROR、VALUE_CONFLICT。不同日期的官方公告差异保留为各自可得版本；未证明的差异不自动当作修订。人民币贷款当月流量不能由舍入累计数强行相减，社融人民币贷款分项也不能替代金融机构贷款当月总额。

社融四次扩围分为五段独立series_id，以concept_id关联；跨段不会选择previous或计算change。旧期现行汇编或跨制度晚发转载若不能认证统计范围，则进入scope_unverified候选，不能用于历史特征。尚未构造恒定范围回溯面板。定义证据：[央行统计说明](https://app.www.gov.cn/govdata/gov/202212/14/495284/article.html)，原文快照见tsf_scope_evidence.json。
