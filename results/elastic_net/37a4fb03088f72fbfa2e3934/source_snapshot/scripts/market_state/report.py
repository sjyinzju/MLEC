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
    from .release import RELEASE,cutoff,file_hash
    REPORT.mkdir(parents=True,exist_ok=True)
    f=read('supervised_targets');m=read('sample_manifest');folds=read('fold_membership')
    spec=json.loads((OUT/'feature_sets.json').read_text(encoding='utf8'))
    policy=json.loads((OUT/'missing_policy.json').read_text(encoding='utf8'))
    dictionary=json.loads((OUT/'state_dictionary/dictionary.json').read_text(encoding='utf8'))
    profiles=read('state_dictionary/profiles');audit=read('release/macro_period_audit')
    refitted=dictionary.get('fit_event',{}).get('training_input_changed',False)
    dictionary_action='本轮修复后的初始核心输入指纹改变，已按相同候选、时间验证与重采样规则重新拟合和选择字典，并重建全部标签和当前状态。' if refitted else '本轮初始训练七项核心输入逐值/指纹未变，复用原拟合和选择；修复的最差累计收益为辅助指标，不参与GMM，已重算画像并更新目标版本。'
    coverage=m.groupby(['market_id','period']).agg(candidate_weeks=('eligible','size'),continuous_valid=('continuous_valid','sum'),
        class_valid=('class_valid','sum'),paired_eligible=('eligible','sum'),score_boundary_valid=('evaluation_eligible','sum')).reset_index()
    coverage.to_csv(REPORT/'weekly_coverage.csv',index=False,encoding='utf8')
    annual=m.assign(year=m.asof_date.dt.year).groupby(['market_id','year']).agg(candidate_weeks=('eligible','size'),continuous_valid=('continuous_valid','sum'),class_valid=('class_valid','sum')).reset_index()
    annual.to_csv(REPORT/'annual_coverage.csv',index=False,encoding='utf8')
    monthly=folds.groupby(['market_id','fold_id','role']).size().reset_index(name='rows')
    monthly.to_csv(REPORT/'monthly_fold_counts.csv',index=False,encoding='utf8')
    excluded=m[~m.eligible].groupby(['market_id','period','eligibility_reason']).size().reset_index(name='rows')
    excluded.to_csv(REPORT/'sample_exclusions.csv',index=False,encoding='utf8')
    audit.to_csv(REPORT/'macro_period_audit.csv',index=False,encoding='utf8')
    pd.DataFrame(policy['series']).to_csv(REPORT/'macro_series_decisions.csv',index=False,encoding='utf8')
    macro=read('macro/historical_reconstructed/lineage')
    macro.groupby(['series_group','series_id','status']).agg(weeks=('asof_date','size'),start=('asof_date','min'),end=('asof_date','max')).reset_index().to_csv(REPORT/'macro_coverage.csv',index=False,encoding='utf8')
    values=read('macro/historical_reconstructed/features');warm=[]
    for sid in ['cgb_1y','cgb_10y','term_spread_10y_1y']:
        for suffix in ['latest','change_5obs','change_20obs','vol_20obs']:
            col='macro__'+sid+'__'+suffix;dates=values.loc[values.asof_date.dt.year.eq(2015)&values[col].isna(),'asof_date']
            warm.append(dict(series_id=sid,feature=col,missing_prediction_weeks=len(dates),dates=json.dumps(dates.astype(str).tolist()),decision='TRAIN_FOLD_WARMUP_MISSING_HANDLING; no label or row imputation'))
    pd.DataFrame(warm).to_csv(REPORT/'cgb_warmup_impact.csv',index=False,encoding='utf8')
    counts=f.groupby(['market_id','future_state_id'],dropna=False).size().reset_index(name='weeks');counts.to_csv(REPORT/'class_counts.csv',index=False,encoding='utf8')
    daily=read('market_daily');daily.groupby('market_id').agg(min_quote_coverage=('quote_coverage','min'),min_float_coverage=('float_coverage','min'),max_unknown_unquoted=('unexplained_unquoted_fraction','max')).reset_index().to_csv(REPORT/'cross_section_coverage.csv',index=False,encoding='utf8')
    products=[];fields=[];specs={s['series_id']:s for s in json.loads((OUT/'macro/specifications.json').read_text(encoding='utf8'))}
    names=['security_history','membership_snapshots','index_prices','calendar','market_daily','market_features','future_window_outcomes','past_window_outcomes',
        'supervised_targets','current_states','sample_manifest','time_splits','fold_membership','macro/historical_reconstructed/features',
        'macro/historical_reconstructed/lineage','state_dictionary/profiles','state_dictionary/candidates','data_tasks']
    for name in names:
        path=OUT/(name+'.parquet')
        if not path.exists():continue
        q=read(name)
        key=KEY if set(KEY)<=set(q) and not q.duplicated(KEY).any() else ['fold_id','role']+KEY if name=='fold_membership' else ['market_id','asof_date','horizon','window_length'] if name=='past_window_outcomes' else ['asof_date'] if name.endswith('/features') else None
        products.append(dict(dataset_id=name,authority_path=path.relative_to(ROOT).as_posix(),rows=len(q),primary_key=key,version=VERSION))
        for col in q:
            unit,definition=field_definition(col,specs)
            role='target' if name in ['future_window_outcomes','supervised_targets'] and col in CORE+['future_state_id'] or col.startswith('future_state_prob_') else 'input' if col in spec['sets']['M+Z'] and name in ['market_features','macro/historical_reconstructed/features'] else 'source_or_metadata'
            fields.append(dict(dataset_id=name,field=col,dtype=str(q[col].dtype),unit=unit,definition=definition,role=role,
                formal_input=role=='input',nominal_category=col=='current_state_id' or col.startswith('current_state_id_lag'),version=VERSION))
    frame('field_dictionary',pd.DataFrame(fields))
    registry_path=ROOT/'data/metadata/dataset_registry.json';old=json.loads(registry_path.read_text(encoding='utf8'))
    sources=old.get('datasets',[])
    write(registry_path,dict(version=VERSION,interface='scripts.market_state.framework.load_dataset',protocol='docs/MLEC_research_protocol.md',
        research_products=products,datasets=sources,label_version=dictionary['label_version'],target_version=spec['target_version'],feature_version=spec['feature_version'],
        missing_policy_version=policy['policy_version'],input_snapshot='data/market_state/release/input_snapshot.json',
        objects={'market_universe':'data/market_state/market_universe.json','state_dictionary':'data/market_state/state_dictionary/dictionary.json',
            'macro_features':'data/market_state/macro/historical_reconstructed/features.parquet'},
        feature_sets='data/market_state/feature_sets.json',formal_dependencies='data/market_state/research_dependencies.json',
        release='data/market_state/release/seal.json',field_dictionary='data/market_state/field_dictionary.parquet'))
    write(OUT/'dataset_manifest.json',dict(version=VERSION,cutoff=str(cutoff().date()),products=products,
        dictionary_version=dictionary['label_version'],target_version=spec['target_version'],feature_version=spec['feature_version'],missing_policy_version=policy['policy_version']))
    write(ROOT/'data/metadata/schema_registry.json',dict(version=VERSION,research_schemas={r['dataset_id']:read(r['dataset_id']).dtypes.astype(str).to_dict() for r in products},source_schemas='data/metadata/field_dictionary.parquet'))
    def result(name):
        path=REPORT/name
        return json.loads(path.read_text(encoding='utf8')) if path.exists() else {'status':'NOT_YET_RUN'}
    acceptance=result('acceptance_validation.json');batch=result('batch_preflight.json');cleanup=result('cleanup_final.json')
    seal_path=RELEASE/'seal.json';seal=json.loads(seal_path.read_text(encoding='utf8')) if seal_path.exists() else {'status':'DRAFT_PENDING_FINAL_ACCEPTANCE'}
    tests=(REPORT/'tests.txt').read_text(encoding='utf8') if (REPORT/'tests.txt').exists() else ''
    testline=next((line for line in tests.splitlines() if 'passed in' in line),'Tests pending')
    bridges=json.loads((OUT/'sources/factor_bridge_scales.json').read_text(encoding='utf8')) if (OUT/'sources/factor_bridge_scales.json').exists() else []
    factor_changes=len(read('release/factor_adjudication_rows')) if (OUT/'release/factor_adjudication_rows.parquet').exists() else 0
    formal=[r for r in policy['series'] if r['formal']];excluded_series=[r for r in policy['series'] if not r['formal']]
    missing_formal=audit[audit.series_id.isin([r['series_id'] for r in formal])&audit.status.eq('SOURCE_GAP')]
    formulas=pd.DataFrame([dict(field=k,unit=v[0],definition=v[1]) for k,v in DEFINITIONS.items()])
    text=f"""# 正式建模前数据校对、补齐与封版验收

唯一研究依据：[market-state-research-v3.0](../../docs/MLEC_research_protocol.md)。本轮输入快照 **mlec-formal-20261113**；数据截止 **{cutoff().date()} 18:00 Asia/Shanghai**，未扩展至新的交易日。初始输入235项的内容哈希、起始提交和补充来源保存在 `release/input_snapshot.json` 与封版清单。

## 验收结论

封版状态：**{seal['status']}**。标签、特征、正式缺失裁定与统一读取均已按当前协议重建；是否可以进入模型选型以 `release/seal.json` 的准入状态为准。当前正式宏观系列 {len(formal)} 条，正式系列内未解释的适用期来源缺口 **{len(missing_formal)}** 项。保留的缺失具有预先确定的语义和训练折处理规则，不声称对以后统计结果没有影响。

本轮没有实现、选择、训练、调参或比较监督预测模型，没有预测成绩或宏观增益结论；GMM仅定义监督标签。快照重建的成分精度沿用协议，不把缺少完整逐日公告档案设为无限补库门槛。

## 实际修复、补齐和清理

1. 修复持续上涨路径的最差未来累计收益：只取 h=1..H，不再把起点0作为未来结果；回撤仍使用完整H+1价格。
2. 北交所11只证券的来源因子历史有冲突，定向取得真实因子，修复 **{factor_changes}** 个证券日；不按异常收益屏蔽风险时期。新尾段因子衔接另有 **{len(bridges)}** 只沪深证券，已用81日重叠逐一核验后统一乘法基准，保留已有公告确认的公司行为修复和尾段内原始因子比例。不是来源取平均，也不是价格平滑；公式及容差见 `sources/factor_bridge_scales.json`，重建父记录见 `release/factor_*`。
3. 补入2026年10月人民币累计出口/进口同比各1条。使用湖北省政府转载新华社的真实2026-11-11日期、保守日末可得时间，未改写成更早的原始首发时间。[来源](https://www.hubei.gov.cn/szyw/202611/t20261111_6083241.shtml)。
4. 对2020/2022年1—2月和2025年2月人民币贸易重新定向核验。官方合并累计表不能证明单月数值；单月人民币系列及其所有派生列退出正式Z，美元替代口径也不从别名重入。正式外部组保留同币种CNY累计同比。累计系列2020/2022年1月未独立公布属于制度合并，不伪造为采集缺口。查询与原表精简证据见 `release/trade_source_attempts.json`。
5. 仅核验实际预热需要的2014年末同口径CFETS国债历史，接口403，其他可得中债曲线/单券成交不与CFETS11:30均值曲线混接。2015年起逐交易日数据齐备；具体输入影响见 [cgb_warmup_impact.csv](cgb_warmup_impact.csv)，不把补齐2014全年设为门槛。
6. 缓存改为父数据内容哈希＋完整日历＋身份＋修复记录＋计算代码＋上一年分区哈希；跨年父数据变化会逐年传播。北交所来源投影绑定注册分区版本。输出排序固定，禁止旧缓存掩盖更新。
7. 按市场移除自身20日cross重复列；状态编号按名义类别编码。训练折全空/常数值列、后出现字段、新类别和缺失标记均有固定处理规则。默认读取必须明确fold/role，跨期查看需显式 `view='analysis'`。
8. 本轮删除的旧Word文件：{cleanup.get('removed',[])}；仍被用户应用占用的未删除文件：{cleanup.get('locked',[])}。用户未提交的临时锁文件保留。残留被占用Word不被任何研究入口或注册表引用，是物理清理遗留，不改变研究内容依据。

## 正式范围、版本与依赖

四市场保持中证全指价格代表＋历史全A横截面、沪深300、中证500、中证1000。中证全指供应商代码000985.CSI映射研究代码000985.SH；整体指数成分集合不冒充全A。北交所从2021-11-15纳入，6只试点及其余存量代码按真实生效日期切换。历史成分按当时观测快照重建、最多持有45天，并立即应用已知上市退市边界，不称精确逐日权重。身份联接终检补回了中证500的53个快照中的689009.SH（CDR）；复用原有发行人1:10份数单位修复，以报价CDR份数匹配成交量和流通量。CDR仅按真实成分进入规模层，整体普通A股横截面仍排除CDR；不把两种范围混称。全部观测成分代码都有历史证券身份。

研究依赖清单：`research_dependencies.json`，区分标签必需、正式M/Z、核验来源与不进入研究的扩展字段。PE/PB、资金流等来源字段不作为本轮完成门槛。E:/QuantData只读，项目仅保留必要投影。

- 字典映射版本：`{dictionary['label_version']}`。
- 连续/类别目标版本：`{spec['target_version']}`。
- 特征定义版本：`{spec['feature_version']}`。
- 缺失裁定版本：`{policy['policy_version']}`。
- 封版数据版本：`{seal.get('data_version','待封版')}`。

## 样本、训练与评分

{coverage.to_markdown(index=False)}

2014年仅预热，没有监督训练样本。每个完整交易周最后交易日18:00预测，未来固定20交易日。末端4周保留候选但未成熟，不作为负例；其余缺失标签不插补。2019年末初始字典训练剔除未成熟窗口；开发评分不使用跨入2023年的未来结果。全部市场日期同步分折。

逐年样本：[annual_coverage.csv](annual_coverage.csv)；全部月度训练/验证/测试行数：[monthly_fold_counts.csv](monthly_fold_counts.csv)。训练行在不同月重复使用的次数不是独立样本量。样本排除：[sample_exclusions.csv](sample_exclusions.csv)。M/M+Z及五组加入/删除共用各阶段相同行、y和版本。

## 五维标签与独立核验

{formulas.to_markdown(index=False)}

辅助结果含下行半波动、最差单日及最差未来累计收益、成交、报价/股本/有效收益覆盖、确认停牌及相关性平衡子集。停牌与缺价不填零收益。流动性先股票→日中位数/股本加权日比率→窗口均值；未来相关性使用未来同日期面板，不用历史60日指标代替。

独立核验覆盖四市场及上涨、下跌、平稳、跨年、成分调整、北交所代码切换、公司行为和停牌密集期。源码独立从close×factor重建个股收益，以流式股票对点积核验相关性，不复用生成测度函数、不保存全量相关矩阵。逐例实际数值在 `release/independent_replays.parquet`；全量窗口域约束、全部股票跨年/来源边界和元/股单位检查在 [acceptance_validation.json](acceptance_validation.json)、[continuity_validation.json](continuity_validation.json)。结果：{acceptance.get('passed',False)}。

固定字典后，从中间股票/指数层扰动2020年以后数值并截断历史，核对以前全部过去窗口；原始宏观事实的未来合法可得记录也做扰动/截断。比较键和值精确相等，允许完整/截断表的整数计数存储dtype不同。2019年末成熟训练核心输入不变。证据：[causal_replay.json](causal_replay.json)。

## 状态字典

仅2015—2019、2019年末已成熟窗口拟合，四市场等权；volatility/drawdown/amihud做训练期log类变换与中位数/IQR尺度，流动性/结构列除sqrt(2)。原单位连续标签保留。

{dictionary_action}没有根据后续预测难易或类别均衡选择字典。全部32种候选、2017/2018/2019时间分块似然和12次同步8周区块重采样均保留。

选择K={dictionary['selected']['k']}、{dictionary['selected']['covariance']}，ARI均值{dictionary['selected']['stability_ari']:.4f}、最低{dictionary['selected']['stability_ari_min']:.4f}；最低结果较弱，不能声称所有重采样均稳健。类别编号不代表连续风险等级，近零均值命名为近零；硬类、全部归属概率、不确定性和当前状态使用相同映射与顺序。

{profiles[['state_id','description','n']+CORE].to_markdown(index=False)}

## 正式缺失裁定与候选池

`missing_policy.json`及 [macro_series_decisions.csv](macro_series_decisions.csv) 是接口实际执行的裁定，不是报告备注。来源池保留全部候选；正式{len(formal)}条系列及其派生项按经济机制、定义和逐期覆盖选择，无预测成绩筛选。贷款的2015/2023定义、早期社融的2015定义已拆成独立列，原拼接列不得进入正式Z，不仅在求差时阻断一次。五组加入/删除均从正式集合展开，不能重新引入排除系列。来源逐期校对：[macro_period_audit.csv](macro_period_audit.csv)；as-of使用状态：[macro_coverage.csv](macro_coverage.csv)。周度非空不作为源期完整的证明，信息年龄也不独立作为采集失败证明。

训练折内规则：数值全空/常数值列删除，只用训练中位数/IQR；保留原列固定缺失标记；名义状态使用训练类别one-hot及明确MISSING/UNSEEN。制度后才出现的变量在早期训练全空时不从未来学习数值填补；下一月训练重新确定schema，单次训练的验证/测试顺序保持一致。所有训练统计均为逐列统计，可为精确的变量子集复用，不依赖其他信息组的数值或y。没有全样本提前拟合。

## 接口、任务配置与真实执行

```powershell
$env:PYTHONPATH='.local_deps'
python -m scripts.market_state.run build
python -m scripts.market_state.run accept
python -m scripts.market_state.run preflight
python -m pytest -q
python -m scripts.market_state.run seal
```

```python
from scripts.market_state.framework import load_dataset, preprocessing
train=load_dataset(market_id='000985.SH',information_set='M+Z',task='regression',fold_id='2023-01',role='train')
test=load_dataset(market_id='000985.SH',information_set='M+Z',task='regression',fold_id='2023-01',role='test')
pre=preprocessing()  # 未拟合；只能fit(train.X)，再transform同折验证/测试
```

`data_task_config.json` 和 `data_tasks.parquet` 仅含市场、信息集、三类目标和月度折，没有具体监督模型配置。批量结果：[batch_preflight.json](batch_preflight.json)，任务数{batch.get('tasks','待执行')}，失败{batch.get('failed','待执行')}，尚无成熟评分行的任务{batch.get('no_mature_score_tasks','待执行')}。逐任务结果和训练折列处理清单位于 `release/data_preflight.parquet`、`release/preprocessing_audit.parquet`。

实际测试：**{testline}**。本机Python退出时pyreadline3可能输出控制台析构告警，退出码与pytest测试结果单独记录。封版清单绑定内容哈希、代码、缺失裁定和目标版本；父数据变更须重建并重新验收，不能继续把旧批量检查当作新版依据。达到准入后停止扩库，后续先选模型，再统一批量训练。
"""
    (REPORT/'completion_report.md').write_text(text,encoding='utf8')
    print('formal report written',flush=True)
