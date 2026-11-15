"""Assemble Chinese reports from actual completed audit artifacts; no market computations."""
import collections
import csv
import hashlib
import json
from pathlib import Path
import pyarrow.parquet as pq

BASE=Path(__file__).resolve().parents[1];A=BASE/'audit';R=BASE/'reports'
def load(name):return json.loads((A/name).read_text(encoding='utf-8'))
def readcsv(name):return list(csv.DictReader((A/name).open(encoding='utf-8-sig',newline='')))
def writecsv(name,rows):
    if not rows:return
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with (A/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
def table(headers,rows):
    def s(x):return str(x if x is not None else 'UNKNOWN').replace('|',' / ').replace('\n',' ')
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(s(x) for x in r)+' |' for r in rows])
def fmt(d):
    d=str(d or '')
    return f'{d[:4]}-{d[4:6]}-{d[6:8]}' if len(d)==8 and d.isdigit() else d or 'UNKNOWN'

summary=load('dataset_summary.json');by={r['dataset']:r for r in summary};run=load('audit_run.json')
assert all(r['status'] in ('SCANNED','MISSING') for r in summary),'Unresolved query errors must be investigated before reporting'
assert len(summary)==len(load('catalog_definitions.json'))
files=load('filesystem_summary.json');lineage=load('lineage_summary.json');raw=load('raw_integrity_summary.json');hashes=load('active_hash_summary.json');dates=load('research_date_eligibility.json');bench=readcsv('benchmark_quality.csv');code=load('index_code_request_summary.json');q=load('quarantine_summary.json');stock=readcsv('stock_dependency_gap_by_exchange.csv');stale=load('staleness.json')
weights=readcsv('index_weight_snapshots.csv');months=readcsv('index_weight_months.csv');db=readcsv('database_inventory.csv');sample=readcsv('sample_file_decode.csv')
definitions={r[0]:r for r in load('catalog_definitions.json')}
docs=json.loads(Path(r'E:\quant\config\official_api_schema.json').read_text(encoding='utf-8'))
coverage=readcsv('dataset_coverage.csv');inventory=[r for r in readcsv('dataset_inventory.csv') if r['layer']=='canonical']
for r in coverage:
    ep=r['dataset'];scope=r['scope'];r['completeness']='UNKNOWN'
    if by[ep]['status']=='MISSING':r['completeness']='MISSING'
    elif ep=='index_daily' and scope in {x['code'] for x in bench if x['missing_days']=='0' and x['invalid_ohlcv_rows']=='0'}:r['completeness']='COMPLETE_WITHIN_REQUESTED_DATES_FOR_THIS_CODE'
    elif ep=='index_dailybasic' and scope=='000300.SH':r['completeness']='COMPLETE_WITHIN_REQUESTED_DATES_FOR_THIS_CODE; ALL_BUSINESS_FIELDS_NON_NULL'
    elif ep=='trade_cal' and scope=='dataset':r['completeness']='SSE_SZSE_INTERNAL_CHECKS_PASS; BSE_MISSING; TAIL_AFTER_20261101_UNKNOWN'
    elif ep in ('daily','daily_basic','adj_factor','stk_limit','index_daily','index_dailybasic','index_weight','shibor_quote','shibor_lpr'):r['completeness']='PARTIAL_OR_SCOPED; SEE_REPORT'
    r['requested_start']='20150101';r['requested_end']='20260922'
    r['missing_dates_artifact']=f'audit/datasets/{ep}_missing_dates.json' if scope=='dataset' and (A/f'datasets/{ep}_missing_dates.json').exists() else f'audit/datasets/{ep}_{scope}_missing_dates.json' if (A/f'datasets/{ep}_{scope}_missing_dates.json').exists() else ''
writecsv('dataset_coverage.csv',coverage)
# Extend the field inventory to raw physical schemas and non-market registry tables.
rawrows=collections.Counter()
for ep,state,n,rows in load('raw_summary.json'):rawrows[ep]+=rows or 0
rawsamples=collections.defaultdict(list)
for row in sample:
    if row['layer']=='raw':rawsamples[row['dataset']].append(row['path'])
physical=load('physical_groups.json')
for ep,paths in sorted(rawsamples.items()):
    fields=collections.defaultdict(set)
    for path in paths:
        for f in pq.ParquetFile(path).schema_arrow:fields[f.name].add(str(f.type))
    for name,types in fields.items():
        inventory.append({'dataset':ep,'layer':'raw','source':'Tushare','category':definitions[ep][1],'column':name,'actual_type':'|'.join(sorted(types)),'field_present':True,'rows':rawrows[ep],'null_count':'UNKNOWN','null_rate':'UNKNOWN','schema_scope':'deterministic full-decode samples; all registered raw footers/row counts checked','row_semantics':'physical batches including repeats, retries, quarantined/unpublished pages; do not concatenate for research','files':raw[ep]['files'],'primary_key':definitions[ep][3],'date_field':definitions[ep][4],'source_definition':docs.get(ep,{}).get('url')})
for name,obj in load('registry_structure.json').items():
    for col,typ,*rest in obj['schema']:
        inventory.append({'dataset':name,'layer':'duckdb_registry','source':'local ingestion registry','column':col,'actual_type':typ,'rows':obj['count'],'null_count':'UNKNOWN','null_rate':'UNKNOWN','row_semantics':'operational metadata, not independent market series'})
for ep in by:
    if not any(r['dataset']==ep and r['layer']=='canonical' for r in inventory):
        inventory.append({'dataset':ep,'layer':'canonical','source':'Tushare','column':'UNKNOWN (no downloaded fields / cached definition)','actual_type':'MISSING','field_present':False,'rows':0,'null_count':'UNKNOWN','null_rate':'UNKNOWN'})
writecsv('dataset_inventory.csv',inventory)
taskcounts=collections.Counter()
for ep,status,kind,n,rows,latest in load('task_summary.json'):taskcounts[status]+=n
present=[r for r in summary if r['status']=='SCANNED'];missing=[r['dataset'] for r in summary if r['status']=='MISSING']
business_nulls=[];allnull=[];nonfinite=[];violations=[]
for r in present:
    for field,s in r['fields'].items():
        if field.startswith('_'):continue
        if s.get('null_count'):business_nulls.append((r['dataset'],field,s['null_count'],f"{s['null_rate']:.6%}"))
        if s.get('null_rate')==1:allnull.append((r['dataset'],field))
        if s.get('nonfinite_count'):nonfinite.append((r['dataset'],field,s['nonfinite_count']))
    for name,n in r['anomalies'].items():
        if n:violations.append((r['dataset'],name,n))
writecsv('business_field_nulls.csv',[dict(zip(['dataset','field','null_count','null_rate'],r)) for r in business_nulls])
date_flags=[{'dataset':r['dataset'],'field':field,**obj} for r in present for field,obj in r.get('date_bounds',{}).items()]
writecsv('date_field_validity.csv',date_flags)
weight_summary=[]
for codeval in sorted({r['code'] for r in weights}):
    rr=[r for r in weights if r['code']==codeval];mm=[r for r in months if r['code']==codeval]
    sums=[float(r['weight_sum']) for r in rr]
    observed={r['month'] for r in mm};inspan=[]
    lo=min(observed);hi=max(observed);yr,mo=int(lo[:4]),int(lo[4:])
    while f'{yr:04}{mo:02}'<=hi:
        m=f'{yr:04}{mo:02}'
        if m not in observed:inspan.append(m)
        mo+=1
        if mo==13:yr+=1;mo=1
    weight_summary.append({'code':codeval,'start':min(r['date'] for r in rr),'end':max(r['date'] for r in rr),'snapshots':len(rr),'months':len(observed),'internal_missing_months':','.join(inspan),'min_members':min(int(r['members']) for r in rr),'max_members':max(int(r['members']) for r in rr),'min_weight_sum':min(sums),'max_weight_sum':max(sums),'weight_sum_outside_99_101':sum(not 99<=s<=101 for s in sums)})
writecsv('index_weight_coverage_summary.csv',weight_summary)
codehash={}
for rel in ['src/quant/data/schemas/catalog.py','src/quant/data/ingest/planner.py','src/quant/data/ingest/engine.py','src/quant/data/storage/lake.py','src/quant/data/sources/tushare.py','src/quant/data/quality/validation.py','config/settings.toml','config/official_api_schema.json']:
    path=Path(r'E:\quant')/rel;codehash[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
(A/'source_code_hashes.json').write_text(json.dumps(codehash,indent=2),encoding='utf-8')
calendar=load('calendar_summary.json');date_rows=[]
for r in summary:
    cov=r.get('coverage',{})
    nullcount=sum(1 for f,s in r.get('fields',{}).items() if not f.startswith('_') and s.get('null_count'))
    datespan=f"{fmt(cov.get('start'))} → {fmt(cov.get('end'))}"
    status='MISSING' if r['status']=='MISSING' else '已核行数；整体完整性 UNKNOWN'
    if r['dataset'] in ['shibor_quote','shibor_lpr','index_daily','index_weight']:status='部分可用，见专项'
    date_rows.append([r['dataset'],r.get('category'),f"{r.get('rows',0):,}",r.get('date_field') or cov.get('date_field') or '无统一事实日期',datespan,cov.get('rows_before_2016','UNKNOWN'),nullcount,status])
anomalytable=table(['数据集','规则','异常数'],violations) if violations else '所检查的非负价量、OHLC 区间、正复权因子、0–100权重规则未发现当前逻辑数据违规。'
audit=f'''# A股市场数据审计报告

审计日期：2026-11-04（Asia/Shanghai）。审计执行时间：{run['started_utc']} 至 {run['ended_utc']}（UTC）。

## 结论与边界

本地数据足以支持沪深300的历史价格风险研究：`000300.SH` 在 **2015-01-05 至 2026-09-22** 的 **2,850** 个本地交易日均有行情，OHLC、前收盘、涨跌幅、成交量和成交额无空值、无所检价量异常。2016年以前确有2015年行情；不能把下载起点误设为2016年，也不能假设已有2015年以前的沪深300价格历史。

全库不能认证为完整：有57个指数请求无实际数据、Shibor两表未完成、权限缺失数据集、指数权重覆盖限制及北交所日历缺失。股票、财务、事件、宏观等各表历史范围不同。`SUCCESS`、水位线、已有报告和本次页脚检查均不单独等同于研究完整性。

全程只读访问 `E:\\QuantData` 与 `E:\\quant`，未调用原项目CLI、Registry初始化、下载器、修复器或联网接口；未读取 `.env`。新脚本、诊断表、报告及查询临时文件均在 `E:\\MLEC`。本轮没有计算特征、状态、标签值、训练或回测；日期窗口检查仅证明观测是否存在。

## 1. 存储、来源与口径

数据来源由 `E:\\quant\\src\\quant\\data\\sources\\tushare.py` 的适配器和官方接口定义确认，是 Tushare。表定义、字段含义、成交量单位“手”、成交额单位“千元”等采用本地 `config/official_api_schema.json` 中缓存的定义；没有联网重新核验文档或独立核对交易所行情。逐字段来源URL已列入 `dataset_inventory.csv`。

共清点 **{files['files']:,}** 文件、**{files['extension_counts']['.parquet']:,}** 个 Parquet（{files['extension_bytes']['.parquet']/1e9:.2f} GB，十进制），包含Raw、当前Canonical、停用历史版本和审计样本。完整路径、大小、修改时间和文件类型见 [file_manifest.csv](../audit/file_manifest.csv)。

{table(['分层','文件数','实际用途'],[[k,f'{v:,}',{'00_raw':'Tushare原始批次及伴随JSON；包括重复观察、空响应和未发布页','10_canonical':'标准化版本文件；研究只能选择active路径及明确版本','40_qlib':'两个既有行情回放导出；不作本课程主要输入','80_quarantine':'隔离质量异常及失败批次证据','90_metadata':'请求意图、进度、锁、回收登记备份等','reports':'旧审计、冻结注册表、PIT测试临时库、核验材料','quant.duckdb':'注册表和读取Parquet的逻辑视图'}.get(k,'UNKNOWN')] for k,v in files['layer_counts'].items()])}

`20_pit / 30_features / 50_predictions / 60_backtests / 70_live` 目录没有文件；目录存在不表示已有课程样本或模型结果。当前发现 {len(present)} 个有有效Canonical的数据集；下载代码定义范围共 {len(summary)} 项（含未下载项）。主库不是另存一份全部行情：`canonical_*` 视图引用注册文件，先按`_row_hash + _ingested_at`去重，再按自然/版本键取最后观察。自然键空缺的事件接口使用内容哈希身份。物理重观测/版本行不能误报为逻辑重复。

共 {len(db)-1} 个辅助数据库（138个DuckDB及1个SQLite）另加主DuckDB；所有数据库以只读方式打开并读取表清单，SQLite `quick_check`通过。辅助数据库为备份、冻结注册表、PIT测试scratch和审计证据，不是独立市场数据源；未逐库解码其所有引用文件，完整内容为 **UNKNOWN**。见 [database_inventory.csv](../audit/database_inventory.csv)。365个CSV属于既有审计输出，逐文件见清单；未将其视作新下载行情，其完整内容为UNKNOWN。

## 2. 实际文件与下载状态核验

- 注册的 **217,467** 个Raw Parquet全部存在；逐文件读取页脚，行数全部与登记一致，坏页脚/行数不符均为0。逐文件证据见 [raw_file_checks.csv](../audit/raw_file_checks.csv)。Raw全列完整解码抽样 **{sum(r['layer']=='raw' for r in sample)}** 个文件，全部成功；未完整解码所有Raw数据页，未抽到的数据页损坏仍为 **UNKNOWN**。
- 当前有效Canonical **8,540** 文件全部存在，全部SHA-256与登记值一致，页脚与登记行数一致。对全部数据集所有列进行分年或整表实际聚合，完成逻辑行数、类型、空值、最小最大值、数值非有限值、键重复和适用异常规则检查。未发现当前有效数据读取损坏。明细见 [active_file_checks.csv](../audit/active_file_checks.csv)、[active_file_hashes.csv](../audit/active_file_hashes.csv)。
- 注册Canonical总文件 **1,077,188**，全部存在，其中1,068,648个已停用；停用文件完整解码抽样 **{sum(r['layer']=='retired' for r in sample)}** 个通过。其余停用文件的数据页/哈希为 **UNKNOWN**，不能笼统称129万Parquet全量无损。
- 另有 **16** 个未登记Canonical Parquet及 **3** 个`.partial`（一个行业成分Parquet、两个进度JSON）。这19个文件已只读解析且可读，但均未被注册为当前有效输入；可读不代表已完成原子发布。未删除、移动、改写它们。路径见 [lineage_summary.json](../audit/lineage_summary.json)、[unpublished_file_checks.csv](../audit/unpublished_file_checks.csv)。
- 财务Raw存在大量物理schema签名，可能包含全空列推断差异等；当前标准化层逐表核对了官方预期字段。所有原始schema变种逐一语义等价的认证为 **UNKNOWN**，不把签名差异直接等同于损坏。

任务库实际计数：{dict(taskcounts)}。失败/待处理共311项，已无`RUNNING`状态；不据此推断操作系统后台进程状态。

{table(['数据集','未完成状态','实际依据'],[['index_daily','57 FAILED_PERMANENT / source_empty_exhausted','9655个请求代码中9598个有实际行情，57个无行；全部失败代码在明细中'],['shibor_quote','40 FAILED_RETRYABLE + 88 PENDING','包含频率、网络及中断错误；实际历史并不连续'],['shibor_lpr','40 FAILED_RETRYABLE + 86 PENDING','包含频率、网络错误；实际历史并不连续']])}

[incomplete_tasks.csv](../audit/incomplete_tasks.csv) 保留请求代码/日期/状态，[task_status.csv](../audit/task_status.csv) 为逐接口汇总。持久化 `bootstrap_request.json` 的目标仍为 **2015-01-01—2026-09-22**；最后记录不是更新到审计当天的证据。2026-10-04的旧修复文档称`share_float`未完成，但现在该接口已无失败/待处理任务，实际行数与日期已重新查询，不能继续照抄旧阻断结论。当前Raw保留分页溢出及重试数据，其总行数不是可用逻辑行数。

代码核验：Planner按SSE/SZSE/BSE规划交易日历，指数基本信息按6个market获取；指数行情为基准代码加基本信息中`.SH/.SZ/.CSI/.BJ`范围。已核实在范围内的基本信息指数没有未规划遗漏（0个）；范围外代码不作失败结论。指数权重只规划11个BENCHMARKS，并不是全部10604个指数。`index_member_all`是申万行业历史成分，不是沪深300成分表。分页、请求行数上限和隔离机制在代码中存在，但不等于来源完整性；本轮以实际行、日历和键关联验证补足。代码指纹见 [source_code_hashes.json](../audit/source_code_hashes.json)。

## 3. 重点指数与交易日历

{table(['代码','名称','实际起点','实际终点','行数','目标区间缺少交易日','价量异常行'],[[r['code'],r['name'],fmt(r['start']),fmt(r['end']),r['rows'],r['missing_days'],r['invalid_ohlcv_rows']] for r in bench])}

科创50与北交所代码的较晚起点不能自动认定为下载失败，应区分指数历史定义/回溯区间与请求缺漏；各自已观测区间的内部缺日另见 `dataset_coverage.csv`。北交所代码名称在基本信息中缺失，标记UNKNOWN。中证A500等指数存在发布前回溯行情：基本信息的`base_date/list_date`与实际价格起点分开列于 [benchmark_master_definitions.csv](../audit/benchmark_master_definitions.csv)，不能将回溯行情当作当时已发布、可实时使用的指数。

科创50的2019-12-31、899050.BJ的2022-04-29各有一条初始基点记录，只有close/vol/amount，open/high/low/pre_close/pct_chg为空；这两条不具备完整OHLC。它们各自起点至末日没有内部SSE开放日缺口，但北交所仍缺独立日历认证。详见`benchmark_null_price_rows.json`，不将初始基点空值冒充普通完整日K线。

`000300.SH`与`399300.SZ`是两个本地沪深300代码口径，价量差异核对见 [csi300_code_comparison.json](../audit/csi300_code_comparison.json)；研究固定选择`000300.SH`，不要拼成重复样本。当前Raw中这两个代码的实际最早/最晚日期见 [csi300_raw_bounds.json](../audit/csi300_raw_bounds.json)。

两代码同日close有335日不完全相同，最大绝对差0.0009点；157日vol或amount不完全相同。固定代码也可避免混入这种来源口径差异。

本地交易日历只有SSE和SZSE：各4693条日历日，范围 **2013-12-27—2026-11-01**，各3120个开放日；审计目标区间内2850个开放日。沪深日历无日期缺口，开放标记一致，`pretrade_date`与前一开放日一致；BSE没有有效行，不能认证北交所。日历与交易所最新官方公告的独立比对为 **UNKNOWN**。**2026-11-02—11-04日历缺失**；本地已知日历显示市场行情9月22日之后至少22个开放日没有更新，另有11月尾部3个日历日尚未核实，见 [staleness.json](../audit/staleness.json)。这不影响选择截至9月22日的历史研究，但不能称当前实时数据库。

全部9598个实有行情代码的内部SSE交易日诊断见 [all_index_calendar_diagnostics.csv](../audit/all_index_calendar_diagnostics.csv)。跨境、债券和特殊指数可能不遵循同一日历；该诊断标记需要核对的区间，不能机械地把每个SSE差日都认定为下载错误。57个彻底无行代码及中文名称见 [index_code_request_reconciliation.csv](../audit/index_code_request_reconciliation.csv)。

隔离记录中有134条指数异常行，涉及16个代码，主要包括`000999.SH`（101行）等；全部明细见 [index_quarantined_rows.csv](../audit/index_quarantined_rows.csv)。**沪深300两代码均不在该隔离清单**。故“全表含隔离缺口”和“沪深300区间完整”可以同时成立；不得用前者否定已查证的主研究序列，也不得用后者认证全部指数。

## 4. 指数基本信息、每日指标和权重

`index_basic`实际10604行；`index_type`列全部为空，其余每列空值见清单，不能按21208物理行推断有21208个独立指数。`000300.SH`的`index_dailybasic`同样2850日齐全，12个业务字段（包括代码、日期、市值、股本、换手率、PE、PE_TTM、PB）全部无空值，可以直接用于该区间的扩展指数研究。`399300.SZ`此表缺2026-03-16一日，不能无核查地交换代码；`399303.SZ/000510.SH/899050.BJ`在此表无行；科创50该表始于2020-07-23，晚于其回溯价格起点。逐代码覆盖见 [index_dailybasic_symbols.csv](../audit/index_dailybasic_symbols.csv)，未以该表替代指数价格表。

权重为快照，按快照检查成员数、权重总和和月份连续性，而非要求每天都有记录：

{table(['指数','起点','终点','快照数','月份数','成员数范围','权重和范围','内部缺失月份'],[[r['code'],fmt(r['start']),fmt(r['end']),r['snapshots'],r['months'],f"{r['min_members']}–{r['max_members']}",f"{r['min_weight_sum']:.4f}–{r['max_weight_sum']:.4f}",r['internal_missing_months'] or '无'] for r in weight_summary])}

快照不提供逐次调仓完整生效时间和历史首次发布时间；仅有月度持仓无法认证逐日精确成分或严格可得时间。不能用当前成分倒推历史。没有权重行的已规划基准也须作为范围缺口处理；所有目标代码见`dataset_coverage.csv`。尾部未观察到2026年9月权重，不在没有来源发布时间证据时断言所有9月请求都应有快照，但不能声称权重已覆盖9月22日。单纯使用官方沪深300指数价量计算风险不依赖成分权重。

## 5. 股票行情、指标、复权与数据质量

股票行情实际 **{by['daily']['rows']:,}** 行，每日基本指标 **{by['daily_basic']['rows']:,}** 行，复权因子 **{by['adj_factor']['rows']:,}** 行；三表均有2015年记录。全部覆盖目标区间的2850个交易日，但“某天有股票数据”不能证明所有当日应交易股票齐备。

{table(['左表','需要右表','代码后缀','无法匹配的键'],[[r['left'],r['right'],r['exchange_suffix'],r['missing_keys']] for r in stock])}

所有行情键均有复权因子；沪深行情键均有每日基本指标，缺少基本指标的90362个键全属`.BJ`。反向每日基本指标有90个沪深键找不到行情；因子有513126个键找不到行情，可能涉及停牌、退市与来源覆盖，逐项真实原因仍为 **UNKNOWN**，不能自动补零或据此删除数据。涨跌停价表还有1130个沪深行情键无法匹配。按年份、代码、日期的明细见 [stock_dependency_reconciliation.csv](../audit/stock_dependency_reconciliation.csv)、[stock_dependency_gap_by_code.csv](../audit/stock_dependency_gap_by_code.csv)。

股票`daily`的open/high/low/close/vol/amount无空值，但pre_close/change/pct_chg各有224条空值；可能涉及首次交易记录，具体原因未逐条认证。研究股票收益时应明确采用相邻有效close还是来源pct_chg，不以日期覆盖完整推断每个收益字段无缺失。

全表数值规则结果：{anomalytable}

特别发现`index_daily`有1472条零收盘价，集中在`H50060.CSI`（457日）、`395011.SZ`（297日）、`931997.CSI`（198日）、`H50059.CSI`（196日）、`H30402.CSI`（192日）、`H30401.CSI`（132日）。这些序列不能直接用作对数收益/价格比率输入；本轮保留并标记，尚未判断零值是来源特殊定义还是错误。沪深300不涉及这些代码。另有1941条价格跳变/涨跌幅一致性候选，明细`index_price_issues.csv`仅为筛查，并非1941条已确认错误。

日期字段检查发现`disclosure_date.modify_date`有1200个逻辑记录不符合单一YYYYMMDD格式，实际样例为逗号分隔多个修改日期；`pledge_detail`的`start_date/end_date/release_date`分别有25/5/8条为年月或年份等低精度表示。不能把这些值无声解析为空后声称无缺失，需按字段语义另定解析规则。明细见`date_field_validity.csv`与`invalid_date_examples.json`；不是沪深300研究阻断。

全部逻辑数据集均已实际按键检查重复；每表的逻辑重复行、物理重复观察、相同内容再观察、版本差异记录在`audit/datasets/<数据集>.json`和覆盖表，不把取最新视图的0重复误当作物理输入没有重复。全部业务字段缺失率见 [business_field_nulls.csv](../audit/business_field_nulls.csv)，字段本身是否缺失、实际类型、最小最大值、非有限值数在 [dataset_inventory.csv](../audit/dataset_inventory.csv)。全空业务字段如下：

{table(['数据集','全空字段'],[[ep,', '.join(f for e,f in allnull if e==ep)] for ep in sorted({e for e,f in allnull})])}

以上空值不自动认定为下载失败。例如亏损PE为空、财务行业不适用列为空、北交所早期数据覆盖差异需分别解释。完整金融经济语义校验、来源错误数值的独立真值核对、极端值究竟错误还是经济事件，为 **UNKNOWN**；本轮通过明确价量规则、全列范围和非有限值筛查给出可复核候选，不以任意统计阈值删除极端行情。`daily_basic`估值、分红、自由流通股等列的不同空值率意味着扩展研究必须按字段设定样本口径。

## 6. 所有数据集实际范围与用途

下表为逐表实际查询；日期采用其事实日期字段，股票主表的上市日期、财报公告日期、未来解禁日期、宏观月份均不是共同的行情覆盖起点。没有统一事实日期的表查了所有原始日期列，详细边界见各表JSON的`date_bounds`。空值字段数仅统计业务列。事件/快照/宏观表在交易日覆盖表中的差日仅作诊断，不意味着它们应逐交易日有行。

{table(['数据集','类别/用途','逻辑行数','日期字段','实际区间','2016年前行数','有空值字段数','结论'],date_rows)}

未下载数据集：`{'`, `'.join(missing)}`。主要为接口权限拒绝；`moneyflow_hsgt`在代码定义范围但不在当前持久化bootstrap endpoints，不能标成下载成功。接口探测`empty`也不能当无权限：如`namechange/suspend_d/index_member_all`探测为空但实际有历史数据。逐项能力标志见`capabilities.json`，以实际Canonical是否有行判定存在。

## 7. 未核实项与复现

UNKNOWN项包括：所有未抽样Raw/停用文件的数据页损坏、辅助库/旧CSV完整内容、全部历史证券应交易日真值、独立交易所价量真值、历史成分准确发布/生效时间、财务事件宏观在首次采集之前的真实修订轨迹、未来日历尾部、各稀疏数据集的来源全集完整性。全量文件存在、页脚可读、哈希匹配和本地规则通过各有明确范围，不能扩展成全市场无误认证。

主数据库起止大小和修改时间一致：**{run['unchanged_db_stat']}**；原始文件仅只读打开，本轮未发起任何源目录写操作。输出脚本可用原项目现有Python环境离线复现，无需安装依赖：

```powershell
E:\\quant\\.venv\\Scripts\\python.exe -X utf8 E:\\MLEC\\scripts\\explore_audit.py
E:\\quant\\.venv\\Scripts\\python.exe -X utf8 E:\\MLEC\\scripts\\audit_market_data.py
E:\\quant\\.venv\\Scripts\\python.exe -X utf8 E:\\MLEC\\scripts\\audit_files_and_storage.py
E:\\quant\\.venv\\Scripts\\python.exe -X utf8 E:\\MLEC\\scripts\\audit_research_dependencies.py
E:\\quant\\.venv\\Scripts\\python.exe -X utf8 E:\\MLEC\\scripts\\audit_remaining_checks.py
E:\\quant\\.venv\\Scripts\\python.exe -X utf8 E:\\MLEC\\scripts\\audit_index_scope.py
E:\\quant\\.venv\\Scripts\\python.exe -X utf8 E:\\MLEC\\scripts\\audit_anomaly_details.py
E:\\quant\\.venv\\Scripts\\python.exe -X utf8 E:\\MLEC\\scripts\\build_audit_reports.py
```

审计按单线程DuckDB、2GB以内内存限制和分年查询执行，大表不整表载入Python；DuckDB临时落盘限于课程目录。曾在初次整表视图查询时触发2GB内存限制，已改为稳定日期键分年读取并重跑；最终报告仅纳入重跑成功的查询结果。检查清单见`audit_run.json`、`query_log.json`和逐数据集JSON。
'''
(R/'market_data_audit.md').write_text(audit,encoding='utf-8')

feasibility=f'''# 《经济学中的机器学习》市场研究数据可行性

审计日期：2026-11-04。**可以进入沪深300历史价格风险研究的下一阶段，当前已完成数据审计并停止，尚未开始特征工程、标签构建、状态划分、修复或训练。** 全库不完整不阻断已核实的沪深300价量研究；扩展到成分股、北交所、宏观或财务时需要另设完整性与可得时间约束。

## 1. 可直接支持的研究任务

固定指数代码`000300.SH`、价格指数口径、SSE交易日历；原始可用区间 **2015-01-05—2026-09-22**，共2850日。该区间关键价量字段无空值、无重复、无内部交易日缺口、无所检OHLC/非负规则异常。独立来源真值和完整历史修订认证为UNKNOWN，但这不妨碍明确采用本地提供商历史重建数据的课程研究。

{table(['研究内容','数据条件与结论','可用时间/限制'],[['历史收益','close或pre_close/pct_chg齐备，可直接研究','相邻本地close计算首个收益为2015-01-06；2015-01-05有pre_close但前一日价格行不在库内，须单独说明口径'],['5/20/60日波动率','连续交易日价格齐备；本轮未计算数值','分别首个完整日收益窗口：2015-01-12 / 2015-02-02 / 2015-04-07'],['最大回撤','可从已有指数close构造','明确全样本/滚动窗口及价格指数口径；不能把未见2015年前峰值计入历史最大回撤'],['成交活跃度','vol、amount逐日齐备','成交量单位手、成交额千元；可研究金额/成交量变化，若需换手率则检查index_dailybasic相应字段'],['未来20交易日风险状态标签','所需后续20日价格可获得；本轮仅检查日期存在','阈值、风险定义及估计方式尚待研究设计；末20日不能生成完整历史标签'],['每周预测样本','按真实交易周最后开放日取时点，非机械每周五','60日收益历史 + 未来20日的完整周候选582个，未建立样本表']])}

## 2. 最早和最晚日期

{table(['口径','最早','最晚','说明'],[['原始沪深300价格/价量','2015-01-05','2026-09-22','2016年前已有2015年；没有查到该指数更早的可用Raw/active行情'],['60个日收益的历史窗口','2015-04-07','2026-09-22','需要61个close；只做截至t的描述/预测输入时可到最后行情日'],['同时需要60日历史与未来20日的日研究时点','2015-04-07','2026-08-25','2770个日期候选；仅计算日期资格'],['按完整交易周末的有标签预测时点','2015-04-10','2026-08-21','582个日期候选；假期周按最后真实开放日'],['沪深交易日历','2013-12-27','2026-11-01','不代表价格也从2013年开始；11月2日后日历尾部缺失'],['科创50价格','2019-12-31','2026-09-22','含回溯历史，不能和其他指数假定相同起点'],['北交所899050.BJ行情','2022-04-29','2026-09-22','没有BSE日历及对应基本信息行，尚不能认证交易日覆盖']])}

日期资格按交易序列算，不按自然日平移；60日波动率约定为60个close-to-close收益，需要61个close。582仅为日期可用性上限，尚未处理其他特征缺失或训练/验证划分。最后20个交易日没有完整未来窗口，不应补值或作为已知标签。未来风险状态的类别阈值和未来波动/回撤等定义未设定；本轮未隐含选择。正式评估还需按时间划分，考虑20日标签重叠，阈值和标准化仅在训练段拟合；这属于后续研究设计，未执行。

## 3. 数据分级

{table(['分级','数据集','可用范围/说明'],[['可直接使用（限已核实口径）','index_daily 的000300.SH；SSE/SZSE trade_cal','截至2026-09-22的沪深300价量与已查日历；其他2850日完整基准可作比较，但需注意指数发布前回溯'],['部分可用','index_daily全表、index_basic、index_dailybasic、index_weight、index_member_all','57个行情代码无行、134条被隔离；index_type全空；每日指标字段空值与代码范围不同；权重为有限代码月度快照；行业成分不是沪深300'],['部分可用（扩展股票研究）','daily、daily_basic、adj_factor、stk_limit、stock_basic、suspend_d','沪深行情与指标、因子键匹配良好，但反向90个行情缺口、涨跌停缺口及停牌/证券全集真值未完全解释；BJ另有范围和日历缺口'],['部分可用（下载未完成）','shibor_quote、shibor_lpr','各40个可重试失败，并有88/86个待处理任务，不建议作为全区间必要特征'],['缺失',''+', '.join(missing),'多数权限不足；moneyflow_hsgt未列当前bootstrap；北交所交易日历也缺失'],['暂时不需要','财务三表、财务指标、预测快报、分红、股东、质押、解禁、回购、龙虎榜、资金流、融资融券、基金与宏观等已有表','主研究可不依赖它们；存在不等于历史PIT可用，首次观察前修订与发布时间需另外认证'],['暂时不需要','既有Qlib二进制、冻结/备份DuckDB、旧审计CSV','Qlib导出仅2026-08-17—09-22且为market_replay，不应替代完整指数历史；其他均是管理/核验证据']])}

逐数据集字段、空值率、记录数、起止范围及2016年前记录数在 [审计报告](market_data_audit.md) 和 [dataset_inventory.csv](../audit/dataset_inventory.csv)、[dataset_coverage.csv](../audit/dataset_coverage.csv)。不要用一个统一历史起点覆盖所有数据。

## 4. 阻断项、影响和修复顺序（仅建议，未执行）

{table(['顺序','核实问题','影响','建议'],[['P0 研究口径','数据截至9月22日，晚于此至少22个已知开放日没有更新；日历11月2日后缺失','要求预测到今天时阻断；历史截至9月22日的研究不阻断','先由用户决定固定历史截止日，或在另行授权修复阶段更新日历与基准行情；更新后重跑审计'],['P0 样本日期','60日历史和20日未来同时可用时，周样本只有2015-04-10—2026-08-21','扩大到原始尾部会缺未来标签；提前起点会缺完整窗口','审核确认研究区间和周频时点，再开始下一阶段；当前不生成标签'],['P1 指数范围','57个代码无行、16个代码合计134行隔离','对应指数的收益、波动、回撤及未来标签可能中断；沪深300不受其影响','只有研究实际依赖这些代码时，先核对改名/停用/接口覆盖和隔离价量原因，再定替代来源与修复；明细逐代码留证'],['P1 权重与历史成分','权重限定11个规划代码、实际范围有缺失；尾部为2026-08-31快照；发布/生效时点未知','不阻断指数直接研究；阻断严格逐日成分回放、精确成分股聚合与无未来信息的权重特征认证','若课程扩展成分股，先确认所需指数和月度/逐日口径，再核对官方调仓生效与公告时间，不能用现有成分倒填'],['P2 股票依赖','90个每日基本指标沪深键无行情；1130个沪深行情键无涨跌停；因子额外513126键无行情','扩展股票横截面、交易执行/涨跌停研究受影响；指数主任务不受影响','先查逐代码日期和停牌/上市/退市/代码变更，不凭猜测填补；保持BJ单独范围'],['P2 北交所','没有BSE有效日历、BJ行情基本指标键缺90362项','无法认证北交所样本完整性','如纳入BJ，优先补日历与证券代码历史映射/必要指标；沪深主研究可先排除BJ'],['P3 下载任务','Shibor两表254项失败/待处理，其他权限接口未下载','如果把它们设为全区间特征会截短或断裂样本','仅当研究需要时处理频控、网络、权限和日期；本轮不resume、不重下'],['P3 存储发布','16个未登记Parquet和3个partial，均不在active输入','递归通配合并可能读入未发布/重复数据','后续管理项目按登记与事务日志核对，恢复前先留证；不要自动清理原文件'],['后续验证','财务事件宏观历史PIT、全部原始/停用数据页完整性、独立价量真值均UNKNOWN','限制扩大后的因果/可交易性声称','按真正用到的数据集增加定向核验，保持未知项可追踪']])}

## 5. 下一步与停止点

建议先审核这两份报告，确认以`000300.SH`价格指数、固定截止日和周末交易时点开展最小课程研究；无需先修完整个数据库。主指数已有连续数据，下一阶段没有必须先重新下载沪深300的证据。若希望覆盖2015年前或2026年9月22日之后，再单独授权新增历史/更新并复核。

**本轮到此停止，等待检查。未进行数据修复、重新下载、特征工程、状态划分、标签值计算、建模或训练。**
'''
feasibility=feasibility.replace('index_daily 的000300.SH；SSE/SZSE trade_cal','index_daily及index_dailybasic的000300.SH；SSE/SZSE trade_cal')
feasibility=feasibility.replace('若需换手率则检查index_dailybasic相应字段','000300.SH的每日指标含换手率，2850日全部业务字段无空值')
feasibility=feasibility.replace('57个代码无行、16个代码合计134行隔离','57个代码无行、16个代码合计134行隔离，另6个代码1472条零收盘')
feasibility=feasibility.replace('对应指数的收益、波动、回撤及未来标签可能中断','对应指数的收益、波动、回撤及未来标签可能中断；零价格不能直接作收益比率')
feasibility=feasibility.replace('权重限定11个规划代码、实际范围有缺失','权重限定11个规划代码、各代码历史起点不同且只有月度快照')
(R/'market_research_feasibility.md').write_text(feasibility,encoding='utf-8')
print('reports written',len(summary),'datasets',len(inventory),'inventory fields',len(coverage),'coverage rows')
