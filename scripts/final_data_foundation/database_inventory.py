"""Human-readable inventory of the actual validated research database."""
from .common import *
from .macro_contract import specifications


NAMES={
 'index_daily':'七指数日行情','index_daily_basic':'指数估值/换手等基本指标',
 'stock_daily':'个股日行情及价量','stock_daily_basic':'个股估值、市值、股本与换手',
 'stock_adjustment':'个股复权因子','stock_master_history':'证券身份与有效区间',
 'stock_name_history':'证券名称/ST历史','stock_trading_status':'证券交易状态',
 'index_constituents_history':'指数成分历史证据','index_weights_history':'指数月度成分权重快照',
 'trade_calendar':'交易所日历','index_identity':'指数身份及发布范围',
 'stock_limits':'个股涨跌停价格','margin_market':'市场融资融券汇总',
 'margin_security':'个股融资融券','stock_moneyflow':'个股资金流代理量',
 'exchange_activity_sh':'上交所市场统计','exchange_activity_sz':'深交所市场统计',
 'stock_connect_top10':'沪深股通十大成交','stock_dividend_events':'分红送转事件',
 'market_data_quality':'逐证券日/字段质量例外','macro_facts':'宏观数值事实',
 'macro_vintages':'宏观数值版本投影','macro_release_events':'宏观发布事件投影',
 'macro_quality':'宏观逐记录质量投影','stock_code_changes':'证券代码变更证据',
 'stock_suspension_intervals':'特殊停牌区间证据','index_adjustment_events':'指数调整公告事件',
 'stock_limit_rule_evidence':'涨跌停规则证据','stock_suspension_events':'停复牌事件',
}


def refresh_storage():
    """Current size inventory; never delete or touch external sources."""
    files=[p for p in ROOT.rglob('*') if p.is_file()]
    def size(base):return sum(p.stat().st_size for p in files if p.is_relative_to(base))
    old=read(ROOT/'data/metadata/delivery_storage.json')
    total=sum(p.stat().st_size for p in files)
    forbidden=[p.relative_to(ROOT).as_posix() for p in files
        if p.is_relative_to(ROOT/'audit/final_data_foundation') and p.suffix in ['.log','.tmp','.partial']]
    result=dict(measurement_date='2026-11-15',bytes_after_cleanup=total,
        gib_after_cleanup=round(total/1024**3,3),standardized_market_gib=round(size(MARKET)/1024**3,3),
        standardized_macro_mib=round(size(MACRO)/1024**2,3),
        research_features_mib=round(size(ROOT/'data/features')/1024**2,3),
        metadata_mib=round(size(ROOT/'data/metadata')/1024**2,3),
        local_dependencies_gib=round(size(ROOT/'.local_deps')/1024**3,3),
        git_objects_gib=round(size(ROOT/'.git')/1024**3,3),
        size_basis='Local project including retained formal results, dependencies and Git; bytes are not unique economic observations.',
        previous_cleanup_removed_bytes=old.get('previous_cleanup_removed_bytes',old.get('bytes_removed_this_cleanup')),
        external_sources_modified=False,git_history_rewritten=False,
        frozen_file_count=len(read(ROOT/'data/metadata/frozen_integrity_hashes.json')),
        technical_check_count=len(read(ROOT/'data/metadata/final_validation.json')['checks']),
        raw_directory_present=(ROOT/'data/raw').exists(),forbidden_run_files=forbidden,
        cleanup_policy='Current raw responses were processed in memory. Superseded exploration extracts and code caches removed. Numeric evidence parents, frozen formal outcomes and user documents retained.')
    write(ROOT/'data/metadata/delivery_storage.json',result)
    return result


def section(validation):
    meta=ROOT/'data/metadata';registry=read(meta/'dataset_registry.json')
    byid={r['dataset_id']:r for r in registry['datasets']}
    text='''
## 数据库到底包含什么

这是由 Parquet 标准表、研究特征及 JSON/Parquet 元数据组成的文件型研究数据库，不是把原始下载堆放在一起，也不是一个单独的 DuckDB 文件。DuckDB 用于查询这些权威表；外部 `E:/QuantData/quant.duckdb` 是只读补充来源，不是项目运行入口。

当前金融行情范围主要为2014-01-01至2026-09-22的沪深A股，包含历史退市证券；存托凭证单独识别，部分全A代理指标排除CDR。七个指数为上证综指、沪深300、中证500、中证1000、上证50、深证成指、创业板指。不是全球金融市场数据库：没有据此宣称具备全量债券逐券行情、期货、期权、境外个股或全部北交所证券。宏观覆盖中国增长、价格、信用、利率和外部五组，65个注册序列包含统计口径拆分，不能理解成65个互不相关的经济概念。

```text
MLEC/
├─ data/standardized/market/v4/  金融权威标准表，多数按年分区
├─ data/standardized/macro/v4/   宏观事实、版本、发布事件、质量四个投影
├─ data/research_v2/             冻结市场数据、状态、标签、599个时点及时间划分
├─ data/features/market/v4/      市场广度、流动性/相关性代理和指数维度
├─ data/features/macro/v4/       五种质量视图的周频特征及逐特征来源
├─ data/datasets/               特征集定义、质量定义、样本资格掩码、权威指针
├─ data/metadata/               数据契约、字段字典、来源、修复父值、缺口、验收
├─ config/                      数据要求与冻结研究/实验配置
├─ scripts/final_data_foundation/  维护、修复、验证、统一研究读取接口
├─ scripts/experiment_framework/  对统一接口的薄适配及保留的模型框架
└─ reports/data_quality/        本报告；既有正式实验成果在原位置保留
```

目录名`v4`是沿用的物理存储路径，当前数据契约版本是`practical-research-data-v5`；不能凭目录名另建一套“v5副本”。`dataset_registry.json`确定每张表的唯一权威路径。旧正式实验输入保留是为了保护已有成果，其结果不代表本轮新数据实验。

### 30张权威标准表的实存清单

以下记录数和范围直接取自本轮全表扫描。质量例外表一条代表一个字段问题；发布、版本和质量投影不应重复计入宏观独立观测总量。事实表可能包含研究契约之外的历史期、较晚抓取观测和被隔离记录，实存日期范围不等于研究纳入范围。空范围表示该表按证据/身份键组织，不代表缺少数据。

| 数据表 | 内容 | 记录数 | 字段数 | 实存日期范围（字段） | 主键 |
|---|---|---:|---:|---|---|
'''
    for r in validation['tables']:
        keys=', '.join(r['primary_key'])
        dates='—' if r['start']=='None' else r['start']+' ～ '+r['end']+' (`'+byid[r['dataset_id']]['date_field']+'`)'
        text+=f"| `{r['dataset_id']}` | {NAMES.get(r['dataset_id'],r['dataset_id'])} | {r['rows']:,} | {len(r['columns'])} | {dates} | `{keys}` |\n"
    text+='''
逐表实际路径、质量等级和字段要求见[注册表](../../data/metadata/dataset_registry.json)；每一字段的物理类型、定义、单位、空值数见[field_dictionary.parquet](../../data/metadata/field_dictionary.parquet)。金融表的主关联键是`instrument_id + trade_date`，证券代码变更通过身份区间处理，不按今日股票名单回填历史。宏观事实通过`source_record_id`连接版本、发布与质量信息，并保留`series_id + period_end + vintage`语义。

### 宏观序列清单及完整情况

分母是契约范围内应当存在的合法统计期，已经排除制度前不存在、1—2月合并发布等明确结构性不适用期。分子是满足所声明口径与质量条件的期数，不是简单统计非空行数。同一指标因社融、贷款、M1等统计制度变化可能拆成多个系列，跨口径变化量不会直接相减。

| 组 | 序列代码 | 指标 | 频率/单位 | 合格期数/应有期数 | 缺口 |
|---|---|---|---|---:|---:|
'''
    complete=pd.read_csv(meta/'data_completeness.csv').set_index('indicator')
    groups={'growth':'增长','prices':'价格','credit':'信用','rates':'利率','external':'外部'}
    for s in specifications():
        if s['series_id'] not in complete.index:
            assert not s['required']
            text+=f"| {groups[s['series_group']]} | `{s['series_id']}` | {s['series_name']} | {s['frequency']} / {s['unit']} | 隔离候选，不计入完整率 | 未认证口径 |\n"
            continue
        r=complete.loc[s['series_id']]
        text+=f"| {groups[s['series_group']]} | `{s['series_id']}` | {s['series_name']} | {s['frequency']} / {s['unit']} | {int(r.available_periods)}/{int(r.expected_periods)} | {int(r.missing_periods)} |\n"
    text+='''
65个注册项中，61项进入必需序列完整性统计，4项是统计范围未认证的隔离候选，不作为合格研究观测或完整率分母。

### 标准数据如何进入研究

1. 标准表保留实际行情/经济统计值、身份、单位和来源，修复不意味着重算冻结研究协议。
2. 市场研究主特征、状态、H5/H20/H40风险标签和时间折从冻结`data/research_v2/`读取。新增市场广度/相关性等为单独扩展，不能自动替换原M组定义。
3. 宏观按每个样本时点进行可得时间对齐，形成latest、previous、change、days_since_release等研究列，同时保留数值父记录和来源时间。
4. 质量视图与信息组决定样本资格。599行是候选时点；不同M+Z组可能没有可用开发样本。M与M+Z只能在同一资格掩码、标签和时间折下比较。
5. 模型从统一接口取值，不能绕过质量表自行拼旧CSV或把NULL填零。本轮未调用模型、调参器或预测生成流程。

### 单位、空值与历史可得性的使用约束

- 行情`close`为未复权价格；`adj_factor`单列，调整收益与除权除息需按已登记口径使用。价量字段同时存在供应商原单位与标准化单位时，应优先查字典：如`volume_shares`为股、`amount_cny`为元，日基本表股本/市值分别常为万股/万元；换手率为百分数。
- PB的非正普通股净资产是已证明的不适用空值；PE空值仍混合亏损不适用与来源缺失，不能一概豁免。未裁定分母字段通过`market_data_quality`排除，数值非空不表示已认证。
- `period_end`是经济统计期，`release_at`是公开发布时刻，`retrieved_at`是抓取时间；实际特征按effective/research availability取值。已公布的历史重建可使用，但不得宣称有完整原始修订档案。
- 4条邦讯技术PB采用后来更正财报，首次可用日期为2020-05-11；`pb_issuer_field_repairs.parquet`保留明确时钟和资格。森马重新限售公告的首个事件日也属于事后验证。它们不进入冻结M组，更不能被当作当日已经公开的新增预测变量。
- strict、conservative、quote_reconstructed、historical_reconstructed、latest_at_retrieval是不同来源/时钟政策；均不自动使整个市场数据库成为原始版本PIT认证数据。不要混用质量视图后仍沿用旧版本标识。

### 体积、留存与可迁移性

保留处理后的标准表、研究特征、必要契约/来源链接/数值父项和维护代码；删除本轮原始响应、探索摘录、备份、运行日志与临时缓存。来源链接及精简派生父值是解释正确性所必需的元数据，不是原始下载副本。外部E盘来源未改动。大型金融分区依照现有Git规则只保留本地，GitHub仓库包含代码、契约、报告和可提交的数据，不能用GitHub文件大小代表本地数据库大小。
'''
    storage=read(meta/'delivery_storage.json')
    text+=f"\n本地项目实际约 **{storage['gib_after_cleanup']:.3f} GiB**（包含已有正式成果和本地依赖），其中金融标准表约 **{storage['standardized_market_gib']:.3f} GiB**；详细计量见[delivery_storage.json](../../data/metadata/delivery_storage.json)。\n"
    return text
