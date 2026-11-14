"""Evidence-driven data acceptance reports. A functioning pipeline is not G4."""
import json
import xml.etree.ElementTree as ET
from collections import Counter
import pandas as pd
from .common import ROOT,STANDARD,FEATURES,DATASETS,METADATA,AUDIT,CONFIG,VERSION,read_json,write_json,write_text
from .requirements import specifications

FIELDS={
 'series_id':'经济指标标识；月度/累计、币种、M1制度及社融统计范围分别建序列。社融未认证旧汇编独立为scope_unverified。',
 'concept_id':'经济概念标识；把不同社融统计范围映射回原需求，但不拼接数值或跨范围计算变化。',
 'statistical_scope_id':'社融四次扩围的五段定义、scope_unverified或as_registered；证据见tsf_scope_evidence.json。',
 'extraction_method':'数值提取方式；assistant_visual_review表示逐图核对表头、币种、正负号和期间，未直接采用OCR输出。',
 'extraction_evidence':'图像转录快照路径，逐张绑定原图SHA256和页面日期证据，可离线重建。',
 'series_name':'中文指标名称；精确口径见 series_catalog 与逐条 adjustment_note。',
 'series_group':'growth/prices/credit/rates/external 五个事先声明的经济信息组。',
 'value':'float64 标准化数值；百分比 7 表示 7%，不是 0.07；原缺失不填零。',
 'unit':'标准化单位：%、index、亿元、万亿元、亿美元、CNY/USD、percentage_points。',
 'currency':'USD/CNY/NA；人民币与美元贸易同比是不同序列。',
 'frequency':'D/M/Q，保留原始统计频率；LPR 为按月报价制度，实际报价日在 observation_date。',
 'measure_type':'level/yoy/mom/ytd_yoy/stock/flow/ytd_flow/spread，禁止累计值冒充单月流量。',
 'period_start':'统计区间开始日，日期而非发布时刻；累计指标为当年1月1日。',
 'period_end':'统计区间结束日；月末、季末或报价日。',
 'observation_date':'原始观察日/报价日；与公告可得时刻分离。',
 'release_at':'已核查公告日期按日终解释的时区时间；未知可为空，不声称日终是实际首发钟点。',
 'research_available_at':'研究使用闸门，Asia/Shanghai；必须不晚于预测 asof_time。未认证版本只能从采集时起使用。',
 'release_time_basis':'发布时间规则及证据类型；原始公告、转载日终、报价日终和采集时点分开。',
 'vintage_id':'来源版本标识；同一观察期多个版本同时保留。',
 'revision_status':'公告版本、转载或事后观察等状态；不同数值不自动解释为真实统计修订。',
 'source_id':'来源URL的稳定标识；来源登记表使用复合键保留类别。',
 'source_name':'机构/来源说明；官方历史报价与原始公告不是同一种证据。',
 'source_url':'事实所在原文或附件URL；附件的公告页由 publication_date_evidence 指向。',
 'source_record_id':'每条来源、指标、观察期、值/版本的唯一键；不因多源同值而删除证据。',
 'retrieved_at':'来源快照取得时刻，Asia/Shanghai；旧档案的取得时刻由固定映射保存。',
 'value_quality':'数值核查方式：原文、表头、提供商字段映射等。',
 'time_quality':'公告日期或时刻的证据等级。',
 'vintage_quality':'原公告、转载、报价无更正日志或仅现行历史汇编等等级。',
 'quality_status':'strict_pit_eligible/conservative_release_reconstructed/latest_vintage_reconstructed/blocked；不是完整率状态。',
 'certification_status':'ACCEPTED/SEMANTIC_ERROR/VINTAGE_UNVERIFIED/VALUE_CONFLICT 等准入状态。',
 'adjustment_note':'原文口径、单位换算、修正与使用限制；不得忽略。',
 'original_series_id':'旧交付指标标识（如存在）；用于追溯错误映射。',
 'original_value':'旧交付数值（如存在）；修正后仍保留原始证据。',
 'claimed_available_at':'原交付声称或被拒绝的可得日期；不用于历史筛选。',
 'evidence_path':'仓库内不可变原始内容路径；哈希见 source_manifest。',
 'source_class':'dated_official_bulletin、official_quote_history、contemporaneous_reprint、dated_official_republication、historical_candidate_archive 等。',
 'publication_date_evidence':'证明本条日期的目录、原文或转载快照路径。',
 'reported_quantum':'原文最小舍入单位（可空），仅用于解释合理舍入差异；不会改写原值。',
 'extracted_text':'具体匹配的原文字段（可空）；原始完整内容始终保留。',
 'parent_record_ids':'派生记录的父来源ID JSON列表；一月累计恒等式1个父项，期限利差2个父项。',
 'data_foundation_version':'本次治理版本 data-foundation-v3.0.0。'
}


def optional(name,default=None):
    p=AUDIT/name
    return read_json(p) if p.exists() else ({} if default is None else default)


def table(frame):return frame.to_markdown(index=False)


def build_reports():
    f=pd.read_parquet(STANDARD/'macro_facts.parquet');m=pd.read_parquet(METADATA/'data_requirements_matrix.parquet')
    specs=pd.DataFrame(specifications());base=read_json(AUDIT/'baseline.json');migration=read_json(AUDIT/'migration_manifest.json')
    validation=optional('validation_results.json');lineage=optional('lineage_validation.json');repro=optional('reproducibility.json')
    from .reproduce import output_hashes
    current_hashes=output_hashes()
    for result,key in [(validation,'validated_output_hashes'),(lineage,'validated_output_hashes'),(repro,'output_sha256')]:
        if result.get('status')=='PASS' and result.get(key)!=current_hashes:
            result['status']='STALE'
    rec=optional('reconciliation_summary.json');integrity=optional('integrity_checks.json')
    test_path=AUDIT/'data_tests.xml'
    tests=ET.parse(test_path).getroot().find('testsuite').attrib if test_path.exists() else {}
    test_summary=f"定向数据测试：{tests.get('tests','未运行')} 项，失败 {tests.get('failures','NA')}、错误 {tests.get('errors','NA')}；证据 audit/data_foundation_v3/data_tests.xml。"
    tree=['MLEC/']
    for p in sorted(ROOT.iterdir()):
        if p.name in ['.git','.local_deps','.pytest_cache']:continue
        tree.append('  '+p.name+('/' if p.is_dir() else ''))
        if p.is_dir():
            tree.extend('    '+c.name+('/' if c.is_dir() else '') for c in sorted(p.iterdir()))
    write_text(AUDIT/'project_tree.txt','\n'.join(tree)+'\n')
    coverage=[]
    for s in specs.to_dict('records'):
        sid=s['series_id'];m1=m[m.series_id.eq(sid)];facts=f[f.series_id.eq(sid)];counts=Counter(m1.status)
        denominator=len(m1)-counts['STRUCTURAL_NA']
        coverage.append({'指标':sid,'组':s['series_group'],'全部来源观察起止':str(facts.period_end.min().date())+' — '+str(facts.period_end.max().date()),
            '应有期数':denominator,'准入期数':counts['ACCEPTED'],'结构性期数':counts['STRUCTURAL_NA'],'准入完整率':f"{counts['ACCEPTED']/denominator:.1%}" if denominator else 'NA',
            '严格公告期数':int(m1.strict_status.eq('ACCEPTED').sum()),'其他状态':('统计范围未认证的候选层，不作为独立应有序列' if not s.get('required',True) else '; '.join(f'{k}:{v}' for k,v in counts.items() if k not in ['ACCEPTED','STRUCTURAL_NA']) or '无')})
    cover=pd.DataFrame(coverage);qualified=cover.loc[cover['其他状态'].eq('无')&cover['应有期数'].gt(0),'指标'].tolist()
    gaps=m[~m.status.isin(['ACCEPTED','STRUCTURAL_NA'])].groupby(['series_id','status']).agg(期数=('period_end','size'),开始=('period_end','min'),结束=('period_end','max')).reset_index()
    q=f.groupby('quality_status').agg(记录数=('value','size'),指标数=('series_id','nunique')).reset_index()
    shared='本轮仅做数据工程。市场协议 market-research-v2.0.0、阈值、状态、标签、599 个周度样本与原时间折保持冻结；未运行模型、调参或预测实验。\n\n'
    limits='''全量验收尚未通过，不能把数据管线成功运行等同于全候选池完整。ACCEPTED 表示至少一个允许等级的观察记录，不表示严格 PIT，更不表示该数据及时到达每个历史预测周。

1. DR007 只有近期真实成交加权报价，2014—2026 长历史仍受阻；R007、FDR007、Shibor 均未代换。国债曲线研究区间数据保留，但2014预热历史仍缺。
2. 美元进出口已增加商务部Word简报和47张逐图核对的历史图片，仍有公告版本缺口。图像转录绑定原图哈希，OCR仅作诊断，不作为数字来源。2020—2021部分简报统一在2021年7月重发，不能倒填早期可得日；部分附件文件日期晚于页面日期，转为采集时点才可用。
3. 贷款2026年5、6月当月额见到的是由舍入后的累计数计算的报道，未把该差额冒充精确原始流量。早期非季末贷款累计、社融累计、近期部分社融当月，以及外储早期月份仍待公告或表格认证。
4. M1旧、新口径分列；LPR只纳入2019年8月起新机制。社融按2018年7月、2018年9月、2019年9月、2019年12月四次扩围分成五段独立series_id；范围无法确认的旧汇编另列scope_unverified，仅采集后可用。不会跨段计算变化；尚未提供恒定范围的全历史回溯序列，其他统计调整仍须结合原文脚注理解。
5. 官方历史报价缺完整更正日志，属于 conservative；具名日期公告为 strict_pit_eligible，但“存在当时公告”不等于已取得所有修订，也不保证网页从未静默更新。仅现行历史表的值均在采集时点以后可用。
6. 日频缺口矩阵以SSE开放日为研究所需报价日代理，不是完整银行间营业日认证；冻结市场区间之外没有扩展市场样本。月、季应有期网格截止2026年9月，采集可保留更晚公告。
7. full_candidate_pool 同时保留互斥的M1和社融定义，完整案例数可为0。按时期/组选择变量是未来研究设计工作；不自动拼接口径或填缺失。qualified_stable_pool排除制度分段系列，只按覆盖筛选，未读取模型成绩。

没有任何缺口被标成 VERIFIED_UNAVAILABLE。请求失败和缺少版本证明不足以证明永久不可获取；下一步应继续核查同期转载、海关月度表与银行间官方长历史渠道。已认证子集可供独立的方法准备，完整五组、全期的正式比较仍受G4和统计范围限制，不能视为已经获准启动最终期实验。
'''
    commands='''```powershell
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
'''
    write_text(ROOT/'docs/remaining_data_limitations.md','# 尚存的数据限制\n\n'+limits+'\n逐指标阻断：\n\n'+table(gaps))
    write_text(ROOT/'docs/project_structure.md',f'''# 项目目录与权威路径

{shared}迁移前记录 {len(base['files'])} 个文件、{sum(x['bytes'] for x in base['files']):,} 字节。此次迁移 {len(migration['files'])} 个文件，逐一核对哈希后处理旧路径；移除 {len(migration['empty_directories_removed'])} 个已核验的空目录。完整清单在 audit/data_foundation_v3/baseline.json 和 migration_manifest.json。

|路径|职责|
|---|---|
|README.md、requirements-research.txt、.gitignore|项目入口、依赖和版本控制规则|
|data/raw/macro|原交付包、官方/第三方原文、请求与响应快照|
|data/raw/market|市场来源证据；原冻结依赖继续按旧清单保留|
|data/standardized/macro/v3|事实、版本、发布日期事件；未准入候选仍保留并分级|
|data/research_v2|原冻结市场数据，权威值不改写|
|data/features/v3|三个质量等级的周频宏观特征和逐单元格lineage|
|data/datasets/foundation_v3|每等级8组数据集及资格表；共享原标签、时间折|
|data/metadata/foundation_v3|需求矩阵、序列字典、来源和数据集注册|
|data/metadata/market|SSE日历和时间折清单的新增权威数据路径；旧审计副本保留|
|data/archive/course_examples/lecture03|课程RData等数据，不作为本研究输入|
|docs/course、docs/research_design、docs/archive|课程代码、课题Word、旧交付指针及原始课程脚本|
|scripts/data_foundation_v3|本轮纯数据CLI；旧模块只复用数据变换|
|config/data|41个经济概念、分口径序列需求、质量政策、组配置、公开请求计划|
|audit/data_foundation_v3|迁移、来源、缺口、测试、完整性和复现证据；不是特征入口|
|reports/data_quality|本轮质量报告及之前历史报告；以final_data_acceptance.md为当前结论|
|experiments、artifacts/models、reports/benchmark|历史开发期探索成果，保留位置和字节，不作为本轮筛选依据|

datacodes_lec3 与 deliverables 的迁移不删除原始数据证据。课程knn脚本的旧macOS路径已修复，原脚本另存 docs/archive/course_original，课程模型未执行。尚未删除用途不明文件或外部项目文件。忽略的原始大文件仍需随快照备份，不能仅凭Git克隆复现。
''')
    unknown=set(f)-set(FIELDS)
    if unknown:raise ValueError('Undocumented fields: '+str(unknown))
    dictionary=[{'field':c,'dtype':str(f[c].dtype),'meaning':FIELDS[c]} for c in f]
    write_json(METADATA/'field_dictionary.json',dictionary)
    write_text(ROOT/'docs/data_dictionary.md','# 数据字段与指标字典\n\n'+table(pd.DataFrame(dictionary))+'\n\n完整候选指标（未据模型结果筛选）：\n\n'+table(specs[['series_id','series_name','series_group','unit','currency','frequency','measure_type','required_start','original_regime_start']])+'\n\n特征名为 `macro__{series_id}__{latest|previous|change|days_since_release}`。previous 是前一个不同观察期，不是同一期前一个修订。change 是上述两期可得数值之差；累计流量跨年为NA，社融不同范围各自取前值，禁止跨段差分。days_since_release按秒除86400。资格表保留 sample_id/horizon、risk_set、target_valid、label_available_at 和缺失系列JSON；eligible要求所选latest齐备，eligible_all_features进一步要求所有派生字段齐备。\n')
    write_text(ROOT/'docs/data_contracts.md',f'''# 数据契约

版本：{VERSION}。source_record_id唯一；同一series_id/period_end允许多个来源与vintage。三个时点字段使用Asia/Shanghai时区，统计区间字段是自然日期。发布日未知的版本禁止倒填历史日期。日期明确、时刻不明时统一23:59:59，当日18:00周度预测不得使用该公告。

结构性缺失只在有制度依据时标记：工业/零售不拆1—2月当月值，累计类不虚构1月；旧/新M1按制度期分开；新LPR实施前、DR设立前不造值；早期社融存量按公布制度。海关合并快讯不等于独立月份不存在，因此贸易1—2月未按该理由抹去缺口。

质量等级由 config/data/quality_levels.json 给出。blocked不进入任何特征；latest_at_retrieval也必须满足真实可得约束，因采集晚于冻结研究末期，未认证历史表不会突然成为历史特征。strict指公告证据准入，不声称历史修订全集已完整。

按预测时点先筛available<=asof，再在每观察期选择最新已知版本，最后选最近两个不同观察期。同一时刻先按质量、再按稳定ID处理重复；同一时刻已认证值冲突则隔离。过期阈值：日10天、月75天、季150天，按观察期末距asof计算。没有未来回填、零填补、全样本插补或标准化拟合。

所有数据集保留原599行市场样本；标签与71,544行时间折使用冻结权威路径。M与M+Z必须复用同一信息集资格掩码和原fold_membership，不能分别dropna。存储2023+冻结标签是数据保全，不是执行最终实验。特征文件不含目标列，构造宏观特征不读取标签。

来源冲突有EXACT_MATCH、ROUNDING_ONLY、DATED_PUBLICATION_VERSION_DIFFERENCE、SEMANTIC_ERROR、VALUE_CONFLICT。不同日期的官方公告差异保留为各自可得版本；未证明的差异不自动当作修订。人民币贷款当月流量不能由舍入累计数强行相减，社融人民币贷款分项也不能替代金融机构贷款当月总额。

社融四次扩围分为五段独立series_id，以concept_id关联；跨段不会选择previous或计算change。旧期现行汇编或跨制度晚发转载若不能认证统计范围，则进入scope_unverified候选，不能用于历史特征。尚未构造恒定范围回溯面板。定义证据：[央行统计说明](https://app.www.gov.cn/govdata/gov/202212/14/495284/article.html)，原文快照见tsf_scope_evidence.json。
''')
    write_text(ROOT/'docs/data_sources.md',f'''# 来源与证据

{shared}来源路径、原始内容SHA256、URL、请求参数、取得时刻及每次失败证据统一在 audit/data_foundation_v3/source_manifest.json 和 data/raw/macro/official_sources/v3/attempts/。来源表为 data/metadata/foundation_v3/sources.parquet。先复用同伴交付、现有官方快照和只读QuantData，再定向采集。

|来源|用途与认证边界|
|---|---|
|国家统计局历史发布目录和官方检索|PMI、价格、工业、零售、GDP、固定资产投资及人民币贸易；按正文区分单月/累计和美元/人民币|
|人民银行金融/社融目录与附件|按旧目录原始日期识别公告，避免把2025网站迁移日期当首发日；存量/流量/贷款分项分开|
|中国货币网/CFETS|Shibor、11:30国债曲线、新LPR；LPR参数为strStartDate/strEndDate逐年查询；DR007取组件明确指向的第8列成交加权值|
|外汇局|人民币中间价、外储年月表和有发布日期的月度公告；美元列与SDR列分开，Excel月度日期归月末|
|海关/商务部|现行美元月度表仅作为事后历史候选；同期商务部简报提供额外版本证据；合并快讯不等于月度数据不存在|
|CCTV、人民网、政府转载、公开财经报道|有日期原文按转载日可得，不能假定等于央行首发；公开摘要只提取明确写出的实际值，不取预测值或舍入累计差额|
|只读QuantData/TuShare及同伴包|保留不同来源数值作交叉核对；无历史版本证明的记录在采集时点才可用|

关键修复：2025年1月M2使用2025-02-14的CCTV同期全文（7%）；2025年1月社融存量415.2万亿元使用上海2025-02-17转载。2014年11月进口同比美元-6.7%、人民币-6.5%来自商务部不同币种段落，不能混合。LPR从2019-08-20的4.25%开始；DR007 2026-11-13成交加权1.3723%，不是当日末笔1.3800%。

外部数据库以DuckDB read_only=True打开，前后大小与mtime一致；检查证据见 external_read_only_check.json。未发现可直接补满DR007的本地表。未修改E盘文件，未读取或输出凭据。
''')
    write_text(ROOT/'docs/data_reproducibility.md','# 数据重建与复现\n\n'+commands+test_summary+f'\n实际字节复现状态：**{repro.get("status","NOT_RUN")}**；比较文件数 {repro.get("output_files_compared",0)}，原始输入文件数 {repro.get("raw_files_verified",0)}。详见 audit/data_foundation_v3/reproducibility.json。\n\n需要Python及requirements-research.txt中的固定版本。旧报价/第三方档案原先依赖文件mtime，现由legacy_retrieval_times.json固定取得时刻。离线重建不会联网，也不会写旧冻结产物。审计运行时刻和registry.created_at不属于字节一致契约；事实、版本、特征、资格表及数据集JSON需要完全相同。\n\n大体积objects、原始交付包和部分旧公告被Git忽略；应按source_manifest列出的路径和哈希整体备份。成功缓存不自动重下，失败重试写独立attempt。每个v3响应上限20MB，v3缓存预算2GB、剩余磁盘低于5GB停止，既有缓存不自动删除。\n')
    datasets=[]
    for path in sorted(DATASETS.rglob('dataset.json')):
        d=read_json(path);datasets.append({'等级':d['quality_level'],'数据集':d['dataset_id'],'变量数':len(d['series']),'样本行':d['rows'],'H20合格行':d['eligible_h20']})
    reports={
      'full_data_inventory.md':'# 全量数据清单\n\n'+shared+f'{specs.concept_id.nunique()}个经济概念、{len(specs)}个分口径候选序列（{f.series_id.nunique()}个有来源记录），5个经济组；{len(f):,}条来源版本记录。原有数据、模型和实验目录不删除。\n\n'+table(cover)+'\n\n统一数据集：\n\n'+table(pd.DataFrame(datasets)),
      'macro_completeness.md':'# 逐期完整性验收\n\n'+shared+'主检查网格为2014-01至2026-09；日频截止冻结市场末日2026-09-22，使用SSE开放日代理。结构性缺失从应有期分母中剔除，原始候选存在不等于准入。\n\n'+table(cover)+'\n\n达到本轮允许等级的完整覆盖（不等于全严格PIT）：\n\n'+', '.join(qualified)+'\n\n逐期矩阵：audit/data_foundation_v3/missing_periods.csv/parquet；完整状态与具体source_record_id可追溯。尚无VERIFIED_UNAVAILABLE认定。\n',
      'macro_semantic_validation.md':'# 宏观语义验证\n\n'+shared+'已修正或重新验证：GDP单季/累计、工业和零售当月/累计及负号、人民币贷款当月/累计与社融分项、M1新旧、贸易币种、外储USD/SDR、LPR参数与频率、DR007字段和收益率同源期限利差。新增5条旧零售候选可得日期继承错误已清除，证据见legacy_availability_corrections.json。\n\n每个准入指标的unit/currency/frequency/measure_type与声明一致；检查结果见semantic_validation.json。社融四次主要扩围已分列独立序列，跨范围变化不再生成；范围不明的旧汇编单列候选。尚未构造恒定范围面板，统计制度的其他调整仍需逐公告脚注解释，G3保留QUALIFIED。\n',
      'macro_pit_and_vintage_validation.md':'# 历史可得性与版本验证\n\n'+shared+table(q)+'\n\nstrict为具日期的官方公告值；conservative含官方历史报价、同期转载和具日期官方重刊；latest为仅现行历史汇编或附件版本不明；blocked为口径未通过。四类都保留原始来源。未认证不等于缺数，真实PIT不等于简单按月平移。\n\n2022Q3 GDP实际公告2022-10-24，PMI可能月末前发布；2025-02-14日终M2不得进入当日18:00样本。实际历史截断及未来值扰动检查见validation_results.json，逐单元格检查见lineage_validation.json。不存在所有历史修订均已取得的声明。\n',
      'source_reconciliation.md':'# 多来源冲突与版本核对\n\n'+table(pd.DataFrame([{'类别':k,'对数':v} for k,v in rec.get('counts',{}).items()]))+f'\n\n同一可得时刻的已认证冲突记录数：{len(rec.get("same_time_certified_conflict_ids",[]))}。全部配对证据见source_reconciliation.csv/parquet。没有用简单来源优先级覆盖冲突；舍入量子解释差异，原文值不改写。SEMANTIC_ERROR涉及候选定义不符，不当作普通统计修订。其他VALUE_CONFLICT仍需判断，保留在候选或版本层，不证明所有来源完全一致。\n'
    }
    for name,content in reports.items():write_text(ROOT/'reports/data_quality'/name,content)
    status=lambda ok:'PASS' if ok else 'FAIL'
    gates=[('G1','目录规范','PASS','已按清单安全迁移；历史依赖保留原位并说明'),
      ('G2','数据契约','PASS',f'{specs.concept_id.nunique()}个概念、{len(specs)}个分口径序列、{len(f.columns)}个事实字段及注册表已生成'),
      ('G3','宏观语义','QUALIFIED','准入基础口径通过，社融四次主要扩围已分列；不提供恒定范围全历史回溯'),
      ('G4','历史覆盖','FAIL','逐期核查完成，但DR007、贸易版本、部分累计流量与外储等仍有可继续处理的缺口'),
      ('G5','发布时点','QUALIFIED','严格约束available<=asof；转载/报价/日终政策明确，完整首发时刻并非全部获得'),
      ('G6','历史版本','QUALIFIED','版本分级保存；修订全集和报价更正日志尚不完整'),
      ('G7','来源核对','QUALIFIED','原始证据和全部冲突保留；部分差异未证明成因'),
      ('G8','样本一致性',status(validation.get('status')=='PASS' and validation.get('checks',{}).get('joint_samples_and_upstream_hashes',False)),'冻结599样本、标签、时间折与每组资格表核验'),
      ('G9','无泄漏',status(validation.get('status')=='PASS' and lineage.get('status')=='PASS'),'真实日期截断、未来扰动与逐单元格lineage'),
      ('G10','可复现',status(repro.get('status')=='PASS'),'从保存原始快照重建并比较字节；忽略文件必须随快照提供'),
      ('G11','旧成果保护',status(integrity.get('all_unchanged',False)),'保护文件逐一SHA256核对，外部数据只读检查'),
      ('G12','研究范围','PASS','纯数据工作；没有模型训练、调参、预测或效果结论')]
    write_json(AUDIT/'acceptance_gates.json',[dict(gate=g,name=n,status=s,evidence=e) for g,n,s,e in gates])
    final='# 最终数据验收\n\n**总体状态：FAIL（全量数据尚不能封版为已完成）。** 工程产物按 data-foundation-v3.0.0 保存并可核验，完整性不合格不被测试通过掩盖。\n\n'+shared+table(pd.DataFrame(gates,columns=['门槛','名称','状态','依据']))+'\n\n'+f'当前记录数 {len(f):,}；经济概念{specs.concept_id.nunique()}，分口径序列{len(specs)}；质量记录数见下表。数据重建 {repro.get("status","NOT_RUN")}，比较 {repro.get("output_files_compared",0)} 个文件；lineage核对 {lineage.get("nonmissing_feature_lineages_verified",0):,} 个非缺失单元格。受保护文件核对 {validation.get("protected_files_verified",0):,} 个。\n\n'+test_summary+'\n\n'+table(q)+'\n\n'+limits+'\n\nG4逐项覆盖：\n\n'+table(cover)+'\n\n当前数据集：\n\n'+table(pd.DataFrame(datasets))+'\n\n交接：结构治理与候选池逐期审计已交付；不是所有合理可获取历史均已补齐，仍有未认证版本。已认证子集可供后续独立方法设计，全候选池全期正式比较的前置条件尚未全部满足。本轮没有提交/推送Git或改变原研究协议。\n'
    write_text(ROOT/'reports/data_quality/final_data_acceptance.md',final)
    write_text(ROOT/'docs/historical_exploration.md','# 历史开发期探索成果\n\nexperiments/、artifacts/models/、reports/benchmark/ 及旧工程交接均是此前开发期探索的历史记录。本轮原字节保留，不重跑、不用于候选变量筛选，也不代表本轮数据验收通过。当前入口是 scripts/data_foundation_v3/cli.py，当前结论以 reports/data_quality/final_data_acceptance.md 为准。\n')
    write_text(ROOT/'README.md',f'''# ECON3059 中国宏观信息与A股风险状态研究

当前阶段仅建设研究数据基础，冻结协议为 `market-research-v2.0.0`。本轮数据版本 `{VERSION}` 的**全量验收仍为FAIL**：{specs.concept_id.nunique()}个经济概念及{len(specs)}个分口径候选序列已核查，重大历史缺口和未认证版本见[最终验收](reports/data_quality/final_data_acceptance.md)，不能因管线可运行而认为全部数据已齐备。

入口是 `python -X utf8 -m scripts.data_foundation_v3.cli`，只处理采集、标准化、核对、特征、样本、验证和报告。本轮禁止模型训练、调参、benchmark和2023+最终实验。

- [项目结构与迁移](docs/project_structure.md)
- [逐期完整率](reports/data_quality/macro_completeness.md)
- [字段字典](docs/data_dictionary.md)与[数据契约](docs/data_contracts.md)
- [来源证据](docs/data_sources.md)与[剩余限制](docs/remaining_data_limitations.md)
- [完整复现命令](docs/data_reproducibility.md)
- [历史探索成果说明](docs/historical_exploration.md)

快速数据检查：

```powershell
python -X utf8 -m pytest tests/data_foundation_v3 -q
python -X utf8 -m scripts.data_foundation_v3.cli validate
python -X utf8 -m scripts.data_foundation_v3.cli verify-lineage
```

权威数据均在data/：raw保存不可变来源；standardized/macro/v3保留所有分级事实；research_v2保存冻结市场；features/v3保存周度特征和lineage；datasets/foundation_v3保存24套可组合数据集；metadata保存注册表、字典、日历和资格依据。数据目录中的候选值必须按quality_status和certification_status使用。

仓库从实际路径解析根目录；E:/QuantData、E:/quant仅只读。课程材料已移至docs/course，课题Word在docs/research_design，旧交付指针在docs/archive；完整迁移证据在audit/data_foundation_v3。旧市场数据、模型与实验成果保留。大原始快照部分被Git忽略，离线复现必须提供来源清单中的实际文件及哈希。
''')
    print('Six quality reports, six data documents, dictionaries and README generated; G4 remains FAIL',flush=True)
