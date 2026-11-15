"""One consolidated A-C report and active registries from actual artifacts."""
import numpy as np
import pandas as pd
from .common import *

DEFINITIONS={
 'return':('ratio','P[t+H]/P[t]-1; H=20'),
 'volatility':('annualized ratio','sqrt(252/H * sum(log(P[d]/P[d-1])^2))'),
 'drawdown':('nonnegative loss ratio','max(1-P[b]/P[a]), 0<=a<=b<=H; H+1 prices'),
 'amihud':('1/CNY','mean over days of cross-sectional median(abs(adjusted log stock return)/CNY amount)'),
 'turnover':('ratio','mean over days of sum(volume shares)/sum(float shares), same valid stock subset'),
 'breadth':('ratio','mean over days of fraction of negative valid adjusted stock returns'),
 'correlation':('Pearson correlation','mean of stock-pair correlations on complete common-date H-day panel; membership required on every day')}

def field_definition(col,specs):
    if col in DEFINITIONS:return DEFINITIONS[col]
    if col.startswith('macro__'):
        sid,suffix=col[len('macro__'):].rsplit('__',1);s=specs[sid]
        meaning={'latest':'latest published value held until superseded','change':'difference between adjacent comparable released periods; no scope break/YTD flow reset',
            'age_days':'calendar days from effective availability to asof_time','not_applicable':'institutional scope not applicable',
            'release_gap':'last economic period exceeds declared release cadence; legal value held','missing':'no legal release in applicable regime'}
        description=meaning.get(suffix,'daily series: trailing '+suffix+' on as-of-available economic-date history')
        unit='days' if suffix=='age_days' else '0/1' if suffix in ['missing','not_applicable','release_gap'] else s['unit']
        return unit,s['series_name']+'; '+description+'; separate statistical_scope_id'
    if col.startswith('market__') or col.startswith('cross__'):
        for metric,(unit,definition) in DEFINITIONS.items():
            if '__'+metric+'_' in col:return unit,'PAST window only; '+definition+'; '+col
        return 'past measure in original units','Historical '+col+'; uses the same past-window measurement function'
    if 'state_prob_' in col:return 'probability','GMM membership in fixed dictionary component order; descriptive membership, not model prediction'
    if 'state_id' in col:return 'nominal category','Fixed dictionary component ID; not an ordinal risk score'
    if 'entropy' in col:return 'nats','-sum(q log(q)); no confidence-based row filtering'
    if col.endswith('_at') or col=='asof_time':return 'Asia/Shanghai timestamp','Availability/fit cutoff; observed clock stored separately from economic date'
    if 'coverage' in col or 'fraction' in col:return 'ratio','Observed valid subset / applicable historical members; no zero-filled returns'
    if col in ['correlation_stocks','correlation_union_stocks','min_members','min_return_stocks','n','price_count']:return 'count','Observed window/stock count'
    return 'metadata or original source unit','Explicit key, source field or coverage flag; see schema and generating function'

def report():
    REPORT.mkdir(parents=True,exist_ok=True)
    manifest=read('sample_manifest');daily=read('market_daily');targets=read('supervised_targets')
    dictionary=json.loads((OUT/'state_dictionary/dictionary.json').read_text(encoding='utf8'))
    profiles=read('state_dictionary/profiles');candidates=read('state_dictionary/candidates')
    coverage=manifest.groupby(['market_id','period']).agg(candidate_weeks=('eligible','size'),continuous_valid=('continuous_valid','sum'),
        categorical_valid=('class_valid','sum'),history_valid=('history_valid','sum'),paired_eligible=('eligible','sum'),boundary_score_eligible=('evaluation_eligible','sum')).reset_index()
    coverage.to_csv(REPORT/'weekly_coverage.csv',index=False,encoding='utf8')
    annual=manifest.assign(year=manifest.asof_date.dt.year).groupby(['market_id','year']).agg(candidate_weeks=('eligible','size'),continuous_valid=('continuous_valid','sum'),categorical_valid=('class_valid','sum'),eligible=('eligible','sum')).reset_index()
    annual.to_csv(REPORT/'annual_coverage.csv',index=False,encoding='utf8')
    miss=manifest[~manifest.eligible].groupby(['market_id','period','eligibility_reason']).size().reset_index(name='weeks')
    miss.to_csv(REPORT/'missing_labels.csv',index=False,encoding='utf8')
    dc=daily.assign(year=daily.date.dt.year).groupby(['market_id','year']).agg(days=('date','size'),min_members=('members','min'),
        min_quote_coverage=('quote_coverage','min'),mean_quote_coverage=('quote_coverage','mean'),min_float_coverage=('float_coverage','min'),
        min_return_coverage=('return_coverage','min'),max_unexplained_unquoted_fraction=('unexplained_unquoted_fraction','max')).reset_index()
    dc.to_csv(REPORT/'cross_section_coverage.csv',index=False,encoding='utf8')
    # Actual remaining field gaps, with security/date counts and reasons. No
    # missing return is assumed to be a zero or a confirmed suspension.
    master=read('security_history');gaprows=[]
    from .sources import load_suspensions
    c=db();c.register('history',master);c.register('calendar',read('calendar'));c.register('confirmed',load_suspensions(master))
    unknown=c.execute("""SELECT h.instrument_id,h.ts_code,cal.date,'NO_QUOTE_NO_CONFIRMED_SUSPENSION' reason
       FROM history h JOIN calendar cal ON cal.date>=h.valid_from AND cal.date<h.valid_to
       LEFT JOIN read_parquet(?) q ON q.instrument_id=h.instrument_id AND q.date=cal.date
       LEFT JOIN confirmed s ON s.instrument_id=h.instrument_id AND s.date=cal.date
       WHERE q.instrument_id IS NULL AND s.instrument_id IS NULL ORDER BY h.ts_code,cal.date""",[str(OUT/'cache/stocks/*.parquet')]).df()
    frame('coverage/unexplained_quote_gaps',unknown);c.close()
    unknown_summary=unknown.groupby('ts_code').agg(security_dates=('date','size'),start=('date','min'),end=('date','max')).reset_index()
    unknown_summary.to_csv(REPORT/'unexplained_quote_gaps.csv',index=False,encoding='utf8')
    for p in sorted((OUT/'cache/stocks').glob('*.parquet')):
        d=pd.read_parquet(p,columns=['instrument_id','date','adj_factor','float_shares','volume_shares','amount_cny','r'])
        for field,mask in [('adjustment_factor',d.adj_factor.isna()),('float_shares',d.float_shares.isna()&d.volume_shares.gt(0)),('CNY_amount',d.amount_cny.isna()&d.volume_shares.gt(0))]:
            q=d[mask]
            if len(q):gaprows.append(dict(field=field,year=int(p.stem),security_dates=len(q),securities=q.instrument_id.nunique(),start=q.date.min(),end=q.date.max(),impact='excluded from affected daily estimator; coverage retained'))
        # Keep exact IDs only for the small mandatory-field gap set.
        q=d[d.adj_factor.isna()|(d.float_shares.isna()&d.volume_shares.gt(0))|(d.amount_cny.isna()&d.volume_shares.gt(0))]
        if len(q):frame('coverage/field_gaps_'+p.stem,q)
    gaps=pd.DataFrame(gaprows,columns=['field','year','security_dates','securities','start','end','impact'])
    gaps.to_csv(REPORT/'required_field_gaps.csv',index=False,encoding='utf8')
    lin=read('macro/historical_reconstructed/lineage')
    macro=lin.groupby(['series_group','series_id','status']).agg(weeks=('asof_date','size'),start=('asof_date','min'),end=('asof_date','max')).reset_index()
    macro.to_csv(REPORT/'macro_coverage.csv',index=False,encoding='utf8')
    oldgaps=pd.read_parquet(ROOT/'data/metadata/unresolved_macro_periods.parquet')
    oldgaps.to_csv(REPORT/'macro_source_period_gaps.csv',index=False,encoding='utf8')
    snapshots=read('membership_snapshots').groupby('index_code').agg(start=('snapshot_date','min'),end=('snapshot_date','max'),snapshots=('snapshot_date','nunique'),rows=('con_code','size')).reset_index()
    snapshots.to_csv(REPORT/'membership_coverage.csv',index=False,encoding='utf8')
    counts=targets.groupby(['market_id','future_state_id'],dropna=False).size().reset_index(name='weeks')
    counts.to_csv(REPORT/'class_counts.csv',index=False,encoding='utf8')
    # Replace stale global bindings while preserving source/correction metadata.
    regpath=ROOT/'data/metadata/dataset_registry.json';reg=json.loads(regpath.read_text(encoding='utf8'))
    source_datasets=[r for r in reg.get('datasets',[]) if r.get('domain') in ['M','Z'] and r.get('authority_path','').startswith('data/standardized/')]
    products=[];fields=[]
    specs={s['series_id']:s for s in json.loads((OUT/'macro/specifications.json').read_text(encoding='utf8'))}
    for name in ['security_history','membership_snapshots','index_prices','market_daily','market_features','future_window_outcomes','supervised_targets','sample_manifest','time_splits','fold_membership','current_states','macro/historical_reconstructed/features','macro/historical_reconstructed/lineage','state_dictionary/profiles','state_dictionary/candidates']:
        q=read(name);products.append(dict(dataset_id=name,authority_path='data/market_state/'+name+'.parquet',rows=len(q),version=VERSION,
            primary_key=KEY if set(KEY)<=set(q) and not q.duplicated(KEY).any() else None))
        for col in q:
            definition=field_definition(col,specs)
            fields.append(dict(dataset_id=name,field=col,dtype=str(q[col].dtype),unit=definition[0],definition=definition[1],version=VERSION))
    frame('field_dictionary',pd.DataFrame(fields))
    write(regpath,dict(version=VERSION,protocol='docs/MLEC_research_protocol.md',interface='scripts.market_state.framework.load_dataset',
        rebuild='python -m scripts.market_state.run build',research_products=products,datasets=source_datasets,
        objects={'market_universe':'data/market_state/market_universe.json','state_dictionary':'data/market_state/state_dictionary/dictionary.json',
                 'macro_features':'data/market_state/macro/historical_reconstructed/features.parquet'},
        label_version=dictionary['label_version'],source_layer_policy='Preserved reconstructed source layers with independent schema and correction evidence; sole research authority data/market_state',
        source_registry='data/metadata/source_registry.parquet',feature_sets='data/market_state/feature_sets.json',field_dictionary='data/market_state/field_dictionary.parquet'))
    write(ROOT/'data/metadata/schema_registry.json',dict(version=VERSION,research_schemas={r['dataset_id']:read(r['dataset_id']).dtypes.astype(str).to_dict() for r in products},source_schemas='data/metadata/field_dictionary.parquet'))
    write(OUT/'dataset_manifest.json',dict(version=VERSION,products=products,label_version=dictionary['label_version'],protocol_sha256=__import__('hashlib').sha256((ROOT/'docs/MLEC_research_protocol.md').read_bytes()).hexdigest()))
    formulas=pd.DataFrame([dict(field=k,unit=v[0],definition=v[1]) for k,v in DEFINITIONS.items()])
    summary=targets[CORE].describe().T.reset_index().rename(columns={'index':'field'})
    coremacro=['pmi_mfg','pmi_new_orders','industrial_va_yoy','retail_sales_yoy','gdp_real_yoy','cpi_yoy','ppi_yoy','m2_yoy','rmb_loan_balance_yoy','shibor_1w','dr007','cgb_1y','cgb_10y','term_spread_10y_1y','usdcny_fixing','exports_cny_ytd_yoy','imports_cny_ytd_yoy','fx_reserves']
    test_output=(REPORT/'tests.txt').read_text(encoding='utf8') if (REPORT/'tests.txt').exists() else 'Tests not yet run'
    test_result=next((line for line in test_output.splitlines() if 'passed in' in line),test_output[:200])
    text=f'''# 新版研究 A—C 集中执行报告

唯一内容依据：[market-state-research-v3.0](../../docs/MLEC_research_protocol.md)。真实处理区间：2014-01-02—{read('calendar').date.max().date()}；候选预测周：{manifest.asof_date.min().date()}—{manifest.asof_date.max().date()}。本轮未运行监督预测模型或 Benchmark，未生成预测成绩或宏观增益结论。

## 执行结果与完成边界

已真实完成四市场完整区间的统一前后向测度、七项连续标签、训练期共享 GMM、当前状态、市场/宏观输入、共同样本和月度时间折。候选周不依赖事件状态或类别置信度。末端未成熟窗口保留空标签。数据与标签研究接口已切换到新版。

**A—C 的处理和标签产物已执行交付；尚不能宣布所有数据要求和目录清理无缺口完成。** 下述字段缺口、证券资料的历史重建精度、旧 Word 文件占用需保留为交付限制；没有以测试通过替代覆盖核查。

## 删除、保留和重构

删除旧事件标签实现、阈值/白名单/敏感性配置、旧折和样本视图、旧预测与模型、重复协议说明及已有版本历史的 archive 副本；逐文件清单见 [cleanup_manifest.json](cleanup_manifest.json)。提取共享 IO/hash 至 `scripts/common.py`，保留采集、标准化、身份、复权、公司行为、修复证据、宏观口径及来源库。保留用户未追踪的协议和 Word 文件。一个已追踪旧 Word 文件因 Windows 进程占用未删除，没有关闭用户应用。

唯一研究命令入口为 `python -m scripts.market_state.run`；读取入口为 `scripts.market_state.framework.load_dataset`；全部研究产物位于 `data/market_state/`。旧来源目录仅作标准化库，不再提供第二套研究样本入口。

## 数据补齐与来源

四指数通过项目已有 Tushare 只读适配器补齐至实际末端；中证全指供应商标识为 `000985.CSI`，显式映射至研究 `000985.SH`。补充 2014 年成员快照和 2026 年后续快照、2026-09-23 后股票行情/股本/复权/停复牌资料，以及最新上市/退市目录。旧日历还缺 2026 年 11 月的开放日期，已重新取得 SSE 日历；当前 3127 个实际开放日期与指数日期逐日相符，20 日边界使用独立交易所日历。请求、取回时间、来源字段见 `data/market_state/source_requests.json`、`calendar_request.json` 和 `sources/`。

北交所行情、复权、股本和代码映射优先从 E:/QuantData 只读 DuckDB 投影，未复制全库或写入外部来源；全 A 横截面从 2021-11-15 加入北交所（此前精选层行情不冒充上市 A 股）。六只试点和其余存量代码分别按 2025-05-06、2025-10-09 生效；来源为[北交所通知](https://www.bse.cn/important_news/200025487.html)及[北京市政府发布](https://www.beijing.gov.cn/ywdt/gzdt/202510/t20251010_4218545.html)。复用沪深修复后的 `*_observations`，保留已退市证券与身份区间。证券身份文件记录 {master.instrument_id.nunique()} 个稳定证券标识，其中北交所 {master[master.ts_code.str.endswith('.BJ')].instrument_id.nunique()} 个。

整体价格代表与全 A 横截面严格区分。规模层使用截至当日最后一个真实快照，最多持有 45 天；没有将快照伪造为精确逐日权重。现有已验证的生效调整档案只覆盖另一指数，不能冒用于这三个规模层。覆盖精度为历史快照重建；主规模层完整生效调整目录仍不具备。快照实际覆盖如下：

{snapshots.to_markdown(index=False)}

逐年横截面覆盖见 [cross_section_coverage.csv](cross_section_coverage.csv)。个股缺价/停牌不填零收益；相邻交易日且都有有效成交与复权价格才形成收益。相关性使用窗口内始终为成员、有完整同日期收益且非零方差的平衡子集，另存其数量和对窗口成员并集的覆盖。

## 监督标签与样本覆盖

{coverage.to_markdown(index=False)}

逐年详表：[annual_coverage.csv](annual_coverage.csv)。缺失标签原因：[missing_labels.csv](missing_labels.csv)。history_valid 指当前 20 日五维可构造；5/60 日特征的个别预热缺失仍保留为空，交给训练折处理，不删掉特征。边界评分资格与标签有效性分开：2019 年末未成熟标签不进入初始字典；2022 年末跨入 2023 的开发窗口不用于开发评分；以后成熟后仍可加入对应月训练。

{formulas.to_markdown(index=False)}

{summary.to_markdown(index=False)}

辅助结果包括下行半波动、最差单日/累计收益、路径斜率、上涨日比例、成交额、报价/有效收益/流通股本覆盖、确认停牌与未解释缺价比例、相关性面板规模。2015-07-03 沪深300窗口的 H+1 价格、手工复算七项结果见 [arithmetic_replay.json](arithmetic_replay.json)。

## 状态字典

仅 2015—2019 且在 2019-12-31 18:00 已成熟的四市场共同日期进入训练，共 {dictionary['training_rows']} 条，每市场等权。变换为 volatility/drawdown/amihud 的 log1p(x/训练期正值中位数)，再按训练中位数与 IQR 标准化，流动性、结构各列除 sqrt(2)。原单位标签、变换参数、模型和类别顺序均保存。

预记录比较 1—8 类 × spherical/diag/tied/full，2017/2018/2019 三段前推验证且清除训练未成熟窗口，12 次同步日历 8 周区块重采样；每次验证和重采样重新拟合其自身变换。按 BIC、验证似然、稳定性 ARI 三者的秩和选择，平分优先较少类别再按 BIC。所有选择不读取宏观或 2020 年以后数据。

选择 **K={dictionary['selected']['k']}，{dictionary['selected']['covariance']}**；BIC={dictionary['selected']['bic']:.3f}，分块验证均值对数似然={dictionary['selected']['cv_likelihood']:.4f}，重采样 ARI 均值={dictionary['selected']['stability_ari']:.4f}，最低={dictionary['selected']['stability_ari_min']:.4f}。最低稳定性明显较弱，不能声称类别在所有重采样下稳健。完整候选分数、每次 ARI、画像、训练键在 `state_dictionary/`；版本 `{dictionary['label_version']}`。类别按训练期收益画像排列以保证确定性，编号不代表风险等级；风险类型映射依据训练期画像固定，未设置报警工作点。

{profiles[['state_id','description','n']+CORE].to_markdown(index=False)}

事后归属为 `future_state_prob_*`；当前归属为 `current_state_prob_*`。未来预测概率接口须使用 `predicted_state_prob_*`，本轮没有生成。软归属熵和最高归属概率保留，未据此删除边界样本。类别数量见 [class_counts.csv](class_counts.csv)。

## 宏观输入与实际缺口

增长、物价、信用、利率、外部经济五组全部重建，主视图为带明确时间假设的历史重建；严格来源和获取时版本另存。旧来源清单的 2026-09-30 结束日期已从活动系列的经济适用期中移除，避免明明有 11 月报价却被误判制度性不适用；M1 旧定义及已结束社融口径仍有真实制度终点。按 available_at<=asof_time 从当时可得版本选择最新经济期，再计算可比变化和信息年龄；跨口径变化、累计值跨年重置和异常期距不求差。日度利率与汇率保存 5/20 个有效观测变化和变化波动。合法发布值持有到下次公布，发布断档单列，不因宏观缺失删整行。

逐系列/状态/起止/受影响周见 [macro_coverage.csv](macro_coverage.csv)，原始逐期来源缺口见 [macro_source_period_gaps.csv](macro_source_period_gaps.csv)。2014 年同口径 CFETS 国债 1Y/10Y 与派生利差各缺 245 日，影响预热并非 2015 年起标签。人民币进出口单月仍有 2020/2022 年 1—2 月及 2025 年 2 月缺口，不能把合并公告拆成单月；旧目录标记的累计 1 月缺口也不能用 1—2 月公告回填。已核对[2020 年官方合并口径](https://www.ndrc.gov.cn/fggz/fgzy/jjsjgl/202004/t20200429_1227114.html)、[2022 年官方合并发布](https://app.www.gov.cn/govdata/gov/202203/08/482607/article.html)、[2025 年官方合并发布](https://www.ccpitzj.gov.cn/art/2025/3/10/art_1229557691_47918.html)。累计同比系列中合法已有发布继续使用；这些来源不证明单月数值，未制造替代单月观测。宏观来源断档保留缺失/年龄接口，不构成 M/M+Z 不同样本。

本轮逐个股实际必需字段缺口（不是用所有可选扩展字段阻断研究）：

{gaps.to_markdown(index=False) if len(gaps) else '已观察成交记录的复权因子、元成交额、流通股本未发现空字段。'}

精确证券/日期明细位于 `data/market_state/coverage/field_gaps_*.parquet`。无报价且无确认停牌证据共 {len(unknown)} 个证券日、{unknown.instrument_id.nunique()} 只证券，见 [unexplained_quote_gaps.csv](unexplained_quote_gaps.csv) 和 `coverage/unexplained_quote_gaps.parquet`。实际检查本地湖及最新上市/退市资料、停牌事件；另外定向查询三只转板/退市北交所证券的行情、股本、因子、停牌，行情未返回而停牌记录覆盖相应区间（请求见 `bse_repair_requests.json`），没有填零收益。仍未取得独立交易所全历史名册完备证明或完整逐日成分生效档案。不能把这些精度限制说成原始实时数据认证。新补尾段复权来自供应商因子；32 个新增交易日的除权事件已逐日定向取回，见 `corporate_action_requests.json` 和 `sources/dividend/`，历史公司行为/修复依据继续保留。

## 调用、重建与验证

```powershell
$env:PYTHONPATH='.local_deps'
python -m scripts.market_state.run collect  # 仅缺口补齐，需网络
python -m scripts.market_state.run build    # 完整本地 A-C 重建，包括标签 GMM
python -m scripts.market_state.run verify
python -m pytest -q
```

```python
from scripts.market_state.framework import load_dataset, preprocessing
d = load_dataset(market_id='000985.SH', information_set='M+Z',
                 task='classification', fold_id='2023-01', role='train')
# task 还可取 probability / regression；所有信息集共用同一元数据和目标行。
# preprocessing() 只返回未拟合的训练折预处理接口。
```

主键为 market_id/asof_date/horizon；特征和标签分表，源/时间元数据另存。模型只使用 feature_sets.json 显式列，初始训练期标签变换与后续模型预处理独立。月度训练截止时刻取上月最后交易日 18:00，各市场日期同步。验证证据：[validation.json](validation.json)，测试实际结果：**{test_result}**，完整运行记录见 [tests.txt](tests.txt)。Python 退出时本机 pyreadline3 控制台析构输出 WinError 0xc0000008；pytest 退出码为 0，此环境告警不属于研究测试失败。缓存为按年紧凑股票字段、北交所投影，不保存全量相关矩阵；不复制整个外部数据库。
'''
    (REPORT/'completion_report.md').write_text(text,encoding='utf8')
    print('report written',REPORT/'completion_report.md',flush=True)
