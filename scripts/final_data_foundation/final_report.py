"""One concise delivery report from current validation and completeness tables."""
from .common import *


def build():
    meta=ROOT/'data/metadata'
    validation=read(meta/'final_validation.json');interface=read(meta/'experiment_interface_validation.json')
    assert validation['technical_checks_passed'] and all(x['passed'] is True for x in validation['checks'])
    assert interface['status']=='INTERFACE_PASS'
    c=pd.read_csv(meta/'data_completeness.csv');macro=c[c.domain.eq('macro')]
    groups=macro.groupby('group')[['expected_periods','available_periods','missing_periods']].sum()
    total=groups.sum();basic=c.set_index('indicator')
    gaps=read(meta/'remaining_gaps.json');assert gaps['status']=='UNRESOLVED_REQUIRED_DATA'
    missing={'pb':next(r['remaining_missing'] for r in gaps['closed_or_reduced'] if r['issue']=='PB'),'turnover_rate_f':next(r['remaining_missing'] for r in gaps['closed_or_reduced'] if r['issue']=='free turnover')}
    denom=next(r['field_exceptions'] for r in gaps['required'] if r['dataset']=='stock_daily_basic' and r['gap_type']=='INCONSISTENT_SOURCE')
    pb=next(r for r in gaps['closed_or_reduced'] if r['issue']=='PB')
    selections=pd.DataFrame(interface['paired_development_selections'])
    core=selections[selections.feature_set.eq('M_plus_Z_core')].pivot(index='fold',columns='role',values='samples')
    empty=selections[selections.samples.eq(0)]
    text=f'''# MLEC 最终数据修复与框架交付

版本：`practical-research-data-v5`。整体结论：**UNRESOLVED_REQUIRED_DATA**。

本轮已实际补数、修复权威标准表、重建宏观视图和资格掩码，并完成数据与实验框架衔接。未训练模型、调参、运行 Benchmark 或生成预测。完整性未达到全字段 DATA READY；已合格的指标可按质量与样本掩码独立使用。

## 本轮已关闭或缩小的缺口

| 项目 | 实际结果 |
|---|---|
| 中证1000价格冲突 | 2015-11-23、2016-01-04 的3个冲突字段已由中证官方 OHLC 裁决；保留与官方显示精度一致的主值，恢复依赖窗口 |
| 深交所2014年数量 | 5类股票×245日×3个数量字段，共3675个直接观测完成核对；原有部分四舍五入派生量被直接量替代。规定的股票总量、创业板成交量与股本缺口关闭 |
| PB | 补入{pb['numeric_values_added']}个数值；另{pb['additional_structural_nonpositive']}个原缺口取得非正普通股净资产依据。结构性PB共{pb['structural_total']}条；真实数值缺口{missing['pb']}。其中4条为后来更正财报支持的历史重建，必须遵守其更正发布时间 |
| 自由流通换手率 | 补入16条：6条从源补回父值、8条依据IPO公告、2条依据上海环境分立上市公告的公众/战略锁定股结构；数值缺口{missing['turnover_rate_f']}条。累计保留39条可复算派生记录 |
| 九号公司CDR单位 | 发行人明确1股基础股票对应10份存托凭证；纠正117个股本字段和242个换手率字段，关闭393项质量冲突 |
| 权威表旧收盘价错误 | 查明旧7条修复只写入已淘汰的中间表；本轮将7条正确收盘价及相关公式落实到权威表，关闭另14项换手率冲突。600079.SH的1条PB已用原半年报净资产复算，与独立来源吻合 |
| 森马服饰追加限售 | 发行人公告明确7000万股无限售、6亿股限售至2015-03-11；修正219日的438个流通股/市值字段，关闭219项换手分母冲突 |
| 人民币贸易 | 原40期缺口补入26期：18期商务部转载海关表、8期注明海关来源的有日期第三方全国人民币统计；仍缺14期 |

股票价格修复保留原字段、数值父项和公式于精简元数据。价格比率重建保持原报告分母；TTM比率与独立源核对，PB分母再与发行人财报核对；4条邦讯技术数据采用2020-05-11更正财报，标记`QUALIFIED_RESTATED_PB_RECONSTRUCTION`，不得用于此前预测。当前冻结研究特征不使用这些个股PB。IPO自由流通量是有公告支持的首日/次日历史重建，不将任意流通股等同自由流通股。贸易转载采用自身发布日期日末作为保守可得时间，不倒填首次发布时间。

## 完整率与真实限制

| 范围 | 完整情况 |
|---|---|
| 七个指数行情 | 21665/21665个指数交易日，100%；中证1000发行前回溯段单独标记 |
| 个股行情与基本指标主键 | 各11981370条，主键对齐；实际行情日正复权因子覆盖100% |
| 深交所规定股票数量/金额系列 | 股票总量、创业板各6字段均3095/3095日，100%；非股票类别数量单位仍不冒称已认证 |
| PB（剔除已证明结构性不适用） | {int(basic.loc['stock_daily_basic:pb','available_periods']):,}/{int(basic.loc['stock_daily_basic:pb','expected_periods']):,}，{basic.loc['stock_daily_basic:pb','completeness']*100:.6f}% |
| 自由流通换手率非空率 | {basic.loc['stock_daily_basic:turnover_rate_f','completeness']*100:.8f}%；另有分母质量例外，非空率不等于正确率 |
| 宏观合法统计期 | {int(total.available_periods):,}/{int(total.expected_periods):,}，{total.available_periods/total.expected_periods*100:.4f}%；缺{int(total.missing_periods)}期，其中245期为缺父值导致的派生利差 |

| 宏观组 | 应有合法期数 | 已有合格期数 | 未解决 |
|---|---:|---:|---:|
'''
    for group,name in [('growth','增长'),('prices','价格'),('credit','信用'),('rates','利率'),('external','外部')]:
        row=groups.loc[group];text+=f'| {name} | {int(row.expected_periods):,} | {int(row.available_periods):,} | {int(row.missing_periods):,} |\n'
    text+=f'''
仍无法可靠取得或裁定：

- 2014年CFETS 11:30均值国债曲线：1Y、10Y各245日，导致利差缺245日。同一官方接口2014年返回0条、2015年1月返回21条；本地、CFETS、财政部/中债渠道未取得同口径日值，不能改用中债收盘曲线。
- 人民币进出口：2020、2022年各缺1月/2月单月进出口同比及1月累计同比（各6期）；2025年缺2月单月进出口同比（2期）。海关中文旧表受访问阻断，英文档案主要为合并表或美元表；商务部目录、可信转载、国家数据、hgsj与cndatatrading仍未提供可验证同口径余值。已拒绝一份混用累计和当月增速的第三方表。
- {denom}项股本分母相关字段冲突：市值、流通市值、普通/自由流通换手率分别按字段质量掩码排除。另460960项只满足来源显示精度解释，属于有限质量认可。
- PE与PE_TTM分别有1764333、2208514个源空值，非空率85.2744%、81.5671%；包含经济上不适用和不可取得，尚不能逐条准确分解，未把它们全部豁免为结构性空值。
- 既定可选资金流仍缺2558个实际交易日，82个无行情日的资金流排除。历史成分公告不穷尽；七指数各140个月度权重快照可用，不声称精确逐日权重或已补2014权重。

具体日期、渠道和原因见 [remaining_gaps.json](../../data/metadata/remaining_gaps.json)；逐指标分母、非空率和质量排除数量见 [data_completeness.csv](../../data/metadata/data_completeness.csv)。市场证券日与宏观统计期不能相加成一个“总体完整率”。

## 统一读取与接口验证

```python
from scripts.final_data_foundation.research_inputs import load_dataset
data = load_dataset(groups=["prices", "credit"],
                    quality="historical_reconstructed", horizon=20)
```

返回 `features`、`eligibility`、`targets`、`folds`、`selected_series`、`feature_lineage`。599个候选时点保留；实际使用必须筛选资格掩码。默认质量为 conservative，使用历史重建时应显式指定。物理路径继续沿用 `v4`，当前版本与唯一权威路径以 [注册表](../../data/metadata/dataset_registry.json) 为准。

`scripts.experiment_framework.dataset.load_dataset()` 已成为上述入口的薄适配。旧main_v1入口禁用；14个特征集、五种质量视图、M/M+Z配对、标签与冻结时间折统一。框架只开放2020/2021/2022开发折；2023+保持隔离。核心七变量的H20资格数量如下，未把所有599行视为可训练样本：

| 开发折 | train | validation |
|---|---:|---:|
'''
    for fold,row in core.iterrows():text+=f'| {fold} | {int(row.train)} | {int(row.validation)} |\n'
    text+=f'''
84个逐折信息组选择中有{len(empty)}个返回空样本。每组实际可用数量取决于资格、制度范围和标签成熟时间；不能通过删掉必需概念或更改研究划分扩充样本。详见 [接口检查](../../data/metadata/experiment_interface_validation.json) 与 [使用文档](../../docs/experiment_framework.md)。

## 验收与保留范围

- 全量数据验收：{len(validation['tables'])}张表、870字段、{len(validation['checks'])}项检查通过。主键缺失/重复、交易日、价量非有限值、身份和复权覆盖、修复父值、宏观派生和可得时间均检查；全年份市值/换手率恒等式没有未登记的例外。未裁定冲突仍明确屏蔽，不算验证正确。
- 接口验收：84个M/M+Z逐折配对、五种质量视图、9种期限/标签组合；10项专项测试覆盖未来事实扰动、修订截断、延迟发布、口径切换、样本匹配和旧入口拒绝。
- {interface['frozen_artifacts_verified']}个冻结文件哈希一致；原599个候选时点、市场状态、风险标签、时间划分及已有正式成果未改动。已有模型结果不是v5结果。
- 标准化数据库、研究特征、数值派生父项、来源链接、维护代码与本报告保留。无本轮原始下载、复现备份、请求日志或运行记录；探索中间量已删除。原始资料仍由用户和同伴保管。体积见 `data/metadata/delivery_storage.json`。
- `E:/QuantData`、`E:/quant`仅作读取。大型金融标准分区、本地依赖与既有模型二进制按既有规则排除GitHub；当前本地仓库保有完整已处理数据，GitHub克隆不是全部金融数据副本。
'''
    from .database_inventory import section
    text+=section(validation)
    path=ROOT/'reports/data_quality/final_database_report.md';path.write_text(text,encoding='utf-8')
    print('FINAL_REPORT',path.relative_to(ROOT),flush=True)


if __name__=='__main__':build()
