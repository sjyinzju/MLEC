"""Human-readable delivery generated from executed evidence, not success slogans."""
from .common import *
from .archive_prior import archive
from .macro_contract import specifications


def table(df,columns=None):
    if columns:df=df[columns]
    def cell(x):return str(x).replace('|','/').replace('\n',' ')
    return '| '+' | '.join(df.columns)+' |\n| '+' | '.join(['---']*len(df.columns))+' |\n'+'\n'.join('| '+' | '.join(cell(x) for x in row)+' |' for row in df.itertuples(index=False,name=None))+'\n'


def build():
    version=VERSION;reg=read(ROOT/'data/metadata/dataset_registry.json')['datasets'];datasets=pd.DataFrame(reg)
    validation=read(AUDIT/'validation_results.json');checks={x['check']:x for x in validation};matrix=pd.read_parquet(META/'data_requirements_matrix.parquet')
    macro=pd.read_parquet(MACRO/'macro_facts.parquet');eligibility=pd.read_parquet(AUDIT/'temporal_validation/sample_eligibility_summary.parquet')
    issues=pd.read_parquet(AUDIT/'issue_closure/issues.parquet');status=pd.read_parquet(AUDIT/'market_coverage/stock_status_after_repair.parquet')
    factor=read(AUDIT/'issue_closure/factor_repairs.json');official_factor=read(AUDIT/'issue_closure/official_factor_repair.json')
    catalogue=pd.read_parquet(AUDIT/'market_coverage/external_catalogue.parquet');fields=pd.read_parquet(ROOT/'data/metadata/field_dictionary.parquet')
    bad=matrix[~matrix.status.isin(['ACCEPTED','STRUCTURAL_NA'])];gaps=bad.groupby(['series_id','status']).agg(periods=('period_end','size'),first=('period_end','min'),last=('period_end','max')).reset_index()
    grid=matrix.groupby(['series_id','status']).size().unstack(fill_value=0).reset_index()
    unknown_fields=fields[fields.required&fields.quality_status.eq('UNVERIFIED_FIELD_DEFINITION')]
    executed=lambda n:checks.get(n,{}).get('execution_status')=='PASS'
    gates=[
      ('G1','PASS','双域需求、必需字段、键、频率、覆盖、可得性和例外规则已登记；不以模型表现筛选需求。'),
      ('G2','QUALIFIED','外部全目录与研究依赖已核查；独立历史证券全目录、全部指数有效成分与若干字段定义仍未认证。'),
      ('G3','PASS' if executed(2) and executed(3) else 'FAIL','七指数交易日与已登记历史证券—交易日逐条核查；全证券池独立穷尽性另列 G4。'),
      ('G4','FAIL','缺行情解释和四组代码变更已修复；仍有复权口径问题及历史证券目录独立认证缺口。'),
      ('G5','FAIL','399001 的 38 次官方调整已重建；完整公告目录、其他指数全历史有效成分和逐日权重仍缺。'),
      ('G6','PASS' if executed(7) else 'FAIL','全部真实概念及制度范围逐期检查；未认证范围保留候选池，不冒充新观测。'),
      ('G7','FAIL','仍有应有的原始公告/版本、国债预热历史、人民币贸易单月和信用累计数据缺口。'),
      ('G8','QUALIFIED','已发现的错误数值被修复或隔离；若干市场字段仍是条件候选，未获全域正式认证。'),
      ('G9','FAIL','两日中证1000价格冲突及若干复权/股本分母差异仍未完全裁决。'),
      ('G10','QUALIFIED','公告、转载、后期汇编和下载版本分开；下载历史不回填成首次可得版本。'),
      ('G11','QUALIFIED','统一ID、Schema、字段和单位字典已建立；部分来源字段定义仍待认证并明确标记。'),
      ('G12','QUALIFIED' if executed(12) and executed(17) else 'FAIL','保留599个冻结时点，可按组和质量版本对齐；市场历史报价属于明确声明的重建。'),
      ('G13','QUALIFIED' if all(executed(n) for n in [13,14,15]) else 'FAIL','声明的信息策略通过未来信息、真实截断及扰动测试；不宣称联合严格原始版本PIT。'),
      ('G14','QUALIFIED' if executed(16) and executed(20) else 'FAIL','来源和转换血缘已登记；离线重建结果见检查20，旧证据部分提取定位仅到文档级。'),
      ('G15','PASS' if executed(18) and executed(19) else 'FAIL','原标签、状态、阈值、样本、fold、模型和外部数据库哈希保持；替换的旧注册表逐字节归档。'),
      ('G16','QUALIFIED','新数据在data下按层组织；旧版本保留，唯一新权威路径由注册表给出，供应商中间快照不作为第二权威。'),
      ('G17','FAIL','仍有未关闭的强制问题；不能以程序检查通过替代数据问题关闭。'),
      ('G18','PASS','本轮仅采集、清洗、数据特征与认证；未训练模型、运行Benchmark或生成预测。')]
    gate_df=pd.DataFrame(gates,columns=['gate','status','evidence_or_limitation']);frame(AUDIT/'acceptance_gates.parquet',gate_df)
    write(AUDIT/'final_acceptance.json',{'version':version,'status':'INCOMPLETE — DATA FOUNDATION NOT FULLY ACCEPTED','gates':gate_df.to_dict('records'),
      'technical_checks_passed':sum(executed(n) for n in range(1,21)),'technical_checks_expected':20,'macro_unaccepted_periods':len(bad),'open_or_partial_issues':int((~issues.status.str.startswith('CLOSED')).sum())})
    header=f'# MLEC 统一研究数据基础 {version}\n\n**INCOMPLETE — DATA FOUNDATION NOT FULLY ACCEPTED**\n\n本报告由实际交付数据和已执行验证生成。技术测试通过不等于全部数据已认证。原 market-research-v2.0.0 的样本、标签、状态定义和实验成果冻结。\n\n'
    source_policy='''观察期、市场交易日、公告时间、实际版本可得时间、下载时间和成分生效时间分别保存。只有 `research_available_at <= asof_time` 的许可版本可进入对应视图。`quote_reconstructed` 对 DR007 明确使用另存的历史收盘可得假设；其真实版本可得时间仍保留，不能称为严格PIT。市场 v2 和 v4 连续扩展均明确为历史报价重建。\n\n公告日期未知时不得由 URL 年份、文件名或观测月猜测。官方后期年报只能在年报发布日期后使用；同一时刻上载的海关月报按已证明的刊期顺序保存。LPR 月末是归档月份，实际定盘在 `observation_date`；春节前发布的 PMI 按原公告日期使用。\n\n'''
    market_text=header+f'''本轮检查了 {len(catalogue)} 个外部已注册数据源，逐项标明 REQUIRED / CANDIDATE / OUT_OF_SCOPE 及理由。研究期为2015-01-05至2026-09-22，独立预热从2014年开始。\n\n'''+table(datasets[datasets.domain.eq('M')],['dataset_id','rows','actual_data_start','actual_data_end','quality_status'])+'\n'
    market_text+='七个指定指数均有3095个应有交易日，共21665行。中证1000在2014-10-17发布前的191条回溯行情单独标记，不能解释为当时可投资信息。基础估值表在发布后完整覆盖，共21474行；其字段非空不构成独立精度认证。\n\n'
    market_text+=table(status)+'\n'
    market_text+='字段级未认证/缺失/冲突计数（可追溯至逐证券逐日期质量表）：\n\n'+table(pd.read_parquet(AUDIT/'market_coverage/field_quality_summary.parquet'))+'\n'
    market_text+='涨跌停及资金流逐证券—交易日复核：\n\n'+table(pd.read_parquet(AUDIT/'market_coverage/secondary_stock_source_summary.parquet'))+'\n'
    market_text+=f'''48个原始公告证实的区间关闭11882条缺行情问题，未添加任何虚构价格或零收益。跨代码别名被归并到历史证券身份，保留源代码及证据。证券目录保留333只退市证券；对已出现代码的覆盖通过，但历史上市目录的独立穷尽认证仍未完成。\n\n7条 daily_basic 收盘价错误经独立未复权报价核正，依赖市值/换手可透明重算，无法核实的估值分母字段隔离。复权侧重取76个证券的完整一致版本，更新{factor['total_changed_values']}个因子值；另按原公告修复000545在2015-03-26遗漏的10转3，影响{official_factor['affected_rows']}条后续因子。全量剩余差异按量化精度、股改特殊口径和未决事项分开，未把它们自动认证。\n\n'''
    market_text+='五维支持：趋势、波动压力和下行损失具备七指数5/20/60日连续指标；活跃度/流动性具备成交、换手原始池和Amihud代理；结构具备历史全A股涨跌广度、未报价比例及60日完整交易面板平均相关。流动性与结构仍是明确条件的代理层，不能与精确指数成分指标混称正式认证。未报价比例不等于停牌比例；停牌终止公告的事后信息未进入历史特征。\n\n'
    flow=read(AUDIT/'issue_closure/moneyflow_supplement.json')
    market_text+=f"资金流补入{flow['supplement_rows']}条此前缺失的提供商记录；对所有后续缺口证券范围重新请求后，仍有{flow['unfilled_observed_dates']}个已交易日未返回资金流记录，保留真实缺口，不填零。66条涨跌停异常通过48家IPO原始公告及股改/恢复上市/吸收合并公告核实，形成70个特殊规则日期（包括天宜上佳上市前五个交易日）。普通日涨跌停字段留空，保留原提供商值及规则证据；新股分时竞价申报范围单独说明，不冒充普通固定日涨跌停。\n\n"
    market_text+='历史成分：399001重建38次公告、39个500成员组合、19500条有效期记录；其他六指数未获得完整有效成分历史。现有576892行权重保留快照语义，不向前铺满月份。\n\n主要证据：`audit/final_data_foundation/market_coverage/`、`source_reconciliation/`、`issue_closure/issues.parquet`。\n'
    macro_text=header+f'''完整候选定义为{len(specifications())}个制度范围ID，覆盖{len({s['concept_id'] for s in specifications()})}个经济概念。当前事实池{len(macro)}行、{macro.series_id.nunique()}个有值范围；保留继承事实和所有新公告版本，未用全表dropna删样本。\n\n'''+table(grid)+'\n'
    macro_text+='其中4个 `__scope_unverified` ID 是来源统计范围无法认证的隔离桶，不是4条额外经济概念；保留其中全部来源记录，但不能为未知制度伪造有效区间。逐期需求网格覆盖61个已声明制度范围，其对应概念的缺口仍正常计入。\n\n'
    macro_text+='尚未达到许可质量的逐期缺口：\n\n'+table(gaps)+'\n'
    macro_text+='DR007新增2947条真实DR007.IB加权利率，30个官方重叠日期完全一致；它们补全数字历史，不补造原始公布版本。外汇储备通过SAFE年报和2016年历史表增加晚期可验证版本，全部月份已有可追溯值；年报精度和版本差异仍保留。2025年1月M2、2026年5—6月贷款等补入有明确日期的原文或当期转载。\n\n'
    macro_text+='社融自2023年1月新增报告机构范围，四个社融概念各增加独立scope ID；2019年12月范围截至2022年12月。人民币贷款累计不能用社融中人民币贷款分项替代，也不将不同版本当月流量相加后冒称官方累计值。人民币贸易缺失月份仍标记真实缺口，未因合并新闻发布而自动豁免。\n\n'+source_policy
    macro_text+='新增贷款、贷款累计与贷款余额同比另保留2015年纳入非银行金融机构拆放、2023年扩展报告机构的逐条scope；周度previous/change遇口径边界留空，父记录口径写入特征血缘。2026年3月与6月社融单月按有日期的报道补入保守版本，六月万亿元报道的舍入精度为100亿元。商务部未标版本API的三月值52240与当期报道52260不同，候选原始返回保留且不倒填成当期版本。\n\n'
    checktable=pd.DataFrame([{'check':r['check'],'name':r['name'],'execution':r['execution_status'],'data_status':r.get('data_status','see_detail'),'seconds':round(r['seconds'],2)} for r in validation])
    cross=header+table(checktable)+'\n'+source_policy+'统一输入资格（H20 combined风险集）：\n\n'+table(eligibility)+'\n'
    cross+='样本从未因缺失被删除。450是冻结H20标签与风险集的共同资格上限，并非599行被删成450行。信用组原先被互斥社融范围共同非空要求压缩，本轮按概念选择已公布的合法范围；M1新旧口径互斥选择。2015年季度社融存量使用既有季度150日陈旧期限。利率组的保守版本仍受DR007历史原始版本和LPR制度生效前不适用限制；显式报价重建视图单列。增长组因1—2月合并公布和预设陈旧期限仍存在间隔，不为增加样本数任意放宽期限。\n\n'
    cross+='资格表中的eligible默认要求各概念最新值合格；previous/change的首期、跨年累计重置或口径切换缺失另列active_transforms_complete与eligible_with_complete_transforms。接口参数require_complete_transforms=True可收紧准入；逐单元feature_lineage保留缺失原因，未生效scope列是明确的结构空列，不能全表dropna或静默填充。\n\n'
    cross+='截断与扰动测试使用真实全候选事实、三个历史时点、七指数完整前缀；市场广度/Amihud/离散度对全部3095日独立重算，平均相关在三个真实完整截面以全部证券两两相关直接复核。结果详见 `audit/final_data_foundation/validation_results.json`，检查失败时以该文件为准。\n'
    inventory=header+table(datasets,['dataset_id','domain','authority_path','rows','quality_status'])+'\n外部目录分域：\n\n'+table(catalogue[['source_dataset','scope','registered_rows','reason']])+'\n'
    sources=header+source_policy+'来源登记：`data/metadata/source_registry.parquet`；原始成功/失败请求、编码、内容哈希、采集时刻保存在原始层。复核会检查成功快照的SHA-256。`data_lineage.parquet` 给出记录父项和文件转换；宏观特征血缘保存每个单元格所用记录、当时可得时间与真实版本可得时间。\n\n'
    sources+='指数三源复核保留两处中证1000未决差异（2015-11-23与2016-01-04）；已证明的真实创业板极端上涨不删除。Tencent个别无效OHLC不覆盖主源；成交量的指数成分口径与全市场口径不得互换。海关月报各刊期及SAFE后期汇编保留原值和精度，不把未经证实的差异一概叫舍入。\n\n严格原始版本的完整修订日志仍不可取得。连接器/API“请求成功”、全表字段非空、两家供应商一致都不单独构成严格原始版本认证。\n'
    answers=[
      '金融市场并非全面完整：七指数日历完整，已登记证券缺行情全部解释；仍缺独立全历史身份认证、精确成分/权重及若干复权、股本/估值字段认证。',
      '五维都有连续数据支持，流动性和结构只达到声明的条件代理精度，尚未达到精确指数成分口径。',
      '四组旧代码、退市保留和11882条缺行情已处理；复权已修复混合版本及遗漏转增，仍有未决差异，整体未认证完成。',
      '历史成分仅部分认证：399001的已收集公告可重演，目录穷尽性及其余六指数完整有效期未通过。',
      '全部宏观概念已逐期核查，但没有全部补齐或认证；具体缺口见宏观审计和逐期问题表。',
      '新数据具有统一入口、键、版本、时钟和字典；来源字段单位不明或语义未核实的部分仍不准自动使用。',
      '已有公告、转载、后期汇编与下载版本可区分；无法保证拥有每个历史首次公布版本及所有修订。',
      '仍有未完全解释的数值/口径冲突，已保留原始证据并列出；未以平均数或静默覆盖解决。',
      '不能声称所有可解决问题已关闭；现有公开路径的补救和未决权限/档案需求均逐项留痕，G7/G17保持FAIL。',
      '统一接口支持M、任意宏观组/变量、时间范围、四种质量策略、冻结H5/H20/H40标签及可选市场代理；返回完整行和显式资格掩码。',
      '复现范围和结果以检查20为准；离线流程不连接外部库、不联网，利用保留快照重建v4数据层。原始信息不存在的问题不会因复现通过而关闭。',
      '已关闭原问题包括11882条未解释缺行情、四组旧代码映射与三组重复别名观测、七处基础行情收盘价矛盾、金浦钛业遗漏转增；M2/美元贸易/外储等保守逐期覆盖改善，DR007数字缺口转为版本限制。证据逐项在issue_closure中。']
    acceptance=header+table(gate_df)+'\n'+ '\n\n'.join(f'{i}. {s}' for i,s in enumerate(answers,1))+'\n\n剩余强制阻断见 `issue_closure/issues.parquet` 和 `final_macro_data_audit.md`。需要取得完整官方/授权有效成分及历史证券目录、原始公告版本或提供商纠错/口径档案；本轮没有购买数据、绕过权限或擅自联系外部人员。\n'
    contract=header+'市场契约：`config/data/market_requirements.json`；宏观契约：`config/data/macro_requirements.json`；统一矩阵：`data/metadata/research_data_requirements.parquet`。必需与可选依据经济研究用途和冻结协议确定，未因缺数删除变量。\n\n'+source_policy
    contract+='价格为未复权原始报价；复权因子另列并保留修复前值。指数为价格指数，不含现金分红再投资。股票成交额由千元转为元，成交量由手转为股；指数daily_basic市值原单位为元、股本为股，不能套用个股daily_basic万元/万股单位。实际字段定义由保存的供应商说明与 `field_dictionary.parquet` 绑定。\n\n结构性缺失须有制度/上市/日历证据。真实缺失、过期、未认证、冲突、结构性不适用分别保留。停牌不填零收益。未知未来成分和事后停牌终止日不进入过去特征。\n'
    dictionary=header+'机器可读字段字典为 `data/metadata/field_dictionary.parquet`，包含全部物理字段、类型、源单位、解释、必需标记、全量空值数与定义证据。宏观value的单位与measure_type按series_id定义。\n\n'+table(pd.DataFrame([{'file':'dataset_registry.json','purpose':'唯一权威路径、主键、行数、范围和整体限制'},{'file':'schema_registry.json','purpose':'每个权威表完整物理Schema'},{'file':'field_dictionary.parquet','purpose':'逐字段类型、单位、解释、空值与证据'},{'file':'source_registry.parquet','purpose':'来源、快照、成功/失败请求与哈希'},{'file':'data_lineage.parquet','purpose':'原始证据、记录父项和转换边'},{'file':'quality_registry.parquet','purpose':'数据集认证状态，须连同逐行质量和问题表读取'}]))+'\n必需字段中仍待补充的来源单位/定义：\n\n'+table(unknown_fields,['dataset_id','field','unit','definition'])
    architecture=header+'''`data/raw` 保存不变供应商/公告快照；`standardized/market/v4` 与 `standardized/macro/v4` 保存新标准层；`data/research_v2` 保持冻结；`data/features/{market,macro}/v4` 保存连续扩展及四种时点视图；`data/datasets` 保存特征集配置与资格掩码，避免重复复制整张矩阵。\n\n股票行情三张正式观测入口是 `stock_daily_observations`、`stock_daily_basic_observations`、`stock_adjustment_observations`；涨跌停正式入口为 `stock_limits_observations`，特殊规则证据为 `stock_limit_rule_evidence.parquet`。同目录下不带 `_observations` 的表是可追溯供应商中间层，不是第二权威。最终消费路径以dataset_registry为准。既有路径不被删除，v3注册表和被替换文档在 `data/archive/data-foundation-v3` 按原字节保存。\n\n来源失效时离线重建仍用已保存快照；源信息本身不足时保留QUALIFIED/FAIL。没有把整个QuantData复制进项目，也没有修改外部目录。\n'''
    reproducibility=header+'''在项目根目录使用现有Python环境执行：\n\n```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
python -m scripts.final_data_foundation.offline
python -m scripts.final_data_foundation.validation
python -m scripts.final_data_foundation.issues
python -m scripts.final_data_foundation.reporting
```
\n`offline` 从保留raw重建供应商标准层、身份/停牌、证据修复、连续市场指标、宏观事实、时点视图和注册表，运行时禁用socket连接。它保留检查点并比较重建前后文件字节/完整逻辑行，结果在 `audit/final_data_foundation/reproducibility/`。继续运行会跳过已成功阶段；重新做一轮使用 `python -m scripts.final_data_foundation.offline --run-name 独立英文运行名` 创建新的检查点目录，不删除旧证据。\n\n单纯重新下载不是复现。初次收集所用授权接口并不赋予历史原始版本认证。模型训练与预测命令不属于本流程。\n\n配置读取示例：\n\n```python
from scripts.final_data_foundation.research_inputs import load_dataset
result = load_dataset(groups=['growth', 'prices'], quality='conservative',
                      start='2015-01-05', end='2026-09-22', horizon=20,
                      label='combined', include_market_extensions=True)
# result: features, eligibility, targets, folds, selected_series, feature_lineage
# require_complete_transforms=True 可要求当前生效口径的四项变换全部非空
# 不删除不合格行；比较M与M+Z时须复用相同eligibility。
```
\n严格原始版本市场输入不可用，请求非注册市场策略会报错；不静默切换为重建。\n'''
    limitations=header+table(gaps)+'\n'+ '\n\n'.join(answers[:9])+'\n\n所有逐期/逐证券证据、尝试和剩余阻断位于 `audit/final_data_foundation/issue_closure/issues.parquet`，不是用含糊的UNKNOWN替代问题说明。所有未认证市场代理和原始来源候选均须显式准入。\n'
    readme=f'''# ECON3059 中国宏观信息与A股风险状态研究

当前数据版本 `{VERSION}` 的验收为 **INCOMPLETE — DATA FOUNDATION NOT FULLY ACCEPTED**。双域数据已完成本轮补充、修复和逐项复核，但尚缺完整有效成分与权重、部分宏观原始版本/观测，以及少量未决价格、复权与股本口径证据。不能把技术测试通过理解为数据全部认证。

冻结协议 `market-research-v2.0.0` 的599个候选时点、原标签、阈值、fold及既有模型成果保留。本轮只做数据工程，未运行模型训练、Benchmark或预测。

- [统一最终验收及12项回答](reports/data_quality/final_data_acceptance.md)
- [金融市场审计](reports/data_quality/final_market_data_audit.md) · [宏观逐期审计](reports/data_quality/final_macro_data_audit.md)
- [完整数据目录](reports/data_quality/full_research_data_inventory.md) · [跨域验证](reports/data_quality/final_cross_domain_validation.md)
- [数据架构](docs/data_architecture.md) · [契约](docs/research_data_contract.md) · [字典](docs/research_data_dictionary.md)
- [来源与版本](reports/data_quality/source_and_vintage_validation.md) · [剩余限制](docs/remaining_limitations.md)
- [离线复现和统一接口](docs/data_reproducibility.md)

```powershell
python -X utf8 -m scripts.final_data_foundation.offline --run-name final
python -X utf8 -m scripts.final_data_foundation.validation
python -X utf8 -m scripts.final_data_foundation.issues
python -X utf8 -m scripts.final_data_foundation.reporting
```

依赖见 `requirements-data-v4.txt`。已有运行名用于断点续作；全新重演用新的英文运行名。新权威入口由 `data/metadata/dataset_registry.json` 指定；旧v3数据保留作不可变输入，旧注册表和入口文档逐字节归档于 `data/archive/data-foundation-v3`。

大规模原始市场快照、标准化市场分区、临时文件和复现前镜像仅保留本地，不直接放入Git。异机离线复现必须同时提供清单对应的本地文件及其SHA-256；仅克隆代码不能凭空恢复来源快照。`E:/QuantData` 与 `E:/quant` 全程只读。
'''
    outputs={'README.md':readme,'reports/data_quality/final_market_data_audit.md':market_text,'reports/data_quality/final_macro_data_audit.md':macro_text,
      'reports/data_quality/final_cross_domain_validation.md':cross,'reports/data_quality/full_research_data_inventory.md':inventory,
      'reports/data_quality/source_and_vintage_validation.md':sources,'reports/data_quality/final_data_acceptance.md':acceptance,
      'docs/research_data_contract.md':contract,'docs/research_data_dictionary.md':dictionary,'docs/data_architecture.md':architecture,
      'docs/data_reproducibility.md':reproducibility,'docs/remaining_limitations.md':limitations}
    archive(list(outputs))
    for p,text in outputs.items():
        path=ROOT/p;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')
    print('Reports/documents',len(outputs),'overall INCOMPLETE',flush=True)


if __name__=='__main__':build()
