"""Research protocols, machine-readable handoff, and non-heldout diagnostics."""
from __future__ import annotations
import csv
import re
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from common import *
from core import CORE_FEATURES,STATE_FEATURES,OPTIONAL_FEATURES,VALUATION_FEATURES

def mdtable(headers,rows):
    def s(v):return str(v if v is not None else 'NA').replace('|',' / ').replace('\n',' ')
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(s(x) for x in r)+' |' for r in rows])
def write(name,text):(REPORT/name).write_text(text,encoding='utf-8')
def fmt(d):return pd.Timestamp(d).strftime('%Y-%m-%d') if pd.notna(d) else 'NA'

def field_spec(name,table):
    role='metadata';formula='处理记录、连接键或质量诊断，禁止自动入模';unit='元数据';window='无';source='本流水线';available='所属记录的asof_time；未来评价元数据仅事后可得';missing='不适用或未观测，不能自动转为0'
    meaning=name+'（流程元数据）'
    if name in CORE_FEATURES+STATE_FEATURES+OPTIONAL_FEATURES+VALUATION_FEATURES or name in ['log_return']:
        role='input';source='000300.SH index_daily / lagged index_dailybasic'
        available='当日18:00历史收盘重建假设；dailybasic滞后一个交易日；非真实提供商历史发布时间'
        missing='历史窗口不足或依赖无效，保留NA与missing__掩码'
    if name.startswith('future_') or name.startswith('y_') or name=='next_event_onset_type':
        role='target';source='未来价格路径/冻结状态和事件';available='完整H日结束的18:00，阳性和阴性对称成熟';window='(t,t+H]，路径回撤额外含P_t';unit='比例、年化比例或类别，见公式'
        formula='未来评价字段，禁止进入特征白名单'
    if name.startswith('ret_'):
        k=int(re.search(r'\d+',name).group());meaning=f'过去{k}交易日简单收益';formula=f'P_d/P_(d-{k})-1';unit='小数比例';window=f'{k}个收益跨度、{k+1}个价格'
    elif re.fullmatch(r'vol_\d+d',name):
        k=int(re.search(r'\d+',name).group());meaning=f'收盘日收益年化波动代理{k}日';formula=f'sqrt(252/{k} * sum(log(P_j/P_(j-1))^2))';unit='年化小数比例';window=f'{k}个有效相邻日收益、{k+1}个价格'
    elif re.fullmatch(r'mdd_\d+d',name):
        k=int(re.search(r'\d+',name).group());meaning=f'{k}日窗口最大峰谷损失';formula='max_(u<=v)(1-P_v/P_u)';unit='非负小数损失';window=f'[d-{k},d]含{k+1}个价格'
    elif re.fullmatch(r'current_drawdown_\d+d',name):
        k=int(re.search(r'\d+',name).group());meaning=f'期末距{k}日窗口高点损失';formula=f'1-P_d/max(P_(d-{k}),...,P_d)';unit='非负小数损失';window=f'[d-{k},d]'
    elif name=='downside_vol_20d':meaning='20日下行半波动';formula='sqrt(252/20 * sum(r_j^2 * 1[r_j<0]))';unit='年化小数比例';window='过去20个有效日收益，分母固定20'
    elif name=='log_return':meaning='相邻真实交易日对数收益';formula='ln(P_d/P_(d-1))';unit='小数对数收益';window='2个相邻价格；首日NA'
    elif name in ['amount','amount_ma20','amount_cny']:
        meaning={'amount':'源指数成交额','amount_ma20':'过去20日平均成交额','amount_cny':'人民币成交额'}[name]
        formula={'amount':'原值','amount_ma20':'mean(amount_d-19,...,amount_d)','amount_cny':'1000*amount'}[name];unit='人民币元' if name=='amount_cny' else '千元';window='20个观测' if name=='amount_ma20' else '当日'
    elif name=='amount_ratio_5_20':meaning='5日相对20日成交活跃度';formula='mean(amount,5)/mean(amount,20)，分母<=0时NA';unit='倍数';window='过去20日'
    elif name.startswith('turnover'):
        meaning='滞后一日换手率或其历史变化';unit='百分数；变化为百分点'
        formula='turnover_(d-1)' if 'lag1' in name else 'turnover_(d-1)-turnover_(d-1-k)';window='只使用d-1及以前，变化k取字段数字'
    elif name.endswith('_lag1'):
        meaning='滞后一交易日的指数每日指标';formula='index_dailybasic field_(d-1)';window='d-1'
        unit='PE/PB为倍数；index_dailybasic市值为人民币元、股本为股（不沿用stock daily_basic的万元/万股单位）'
    elif name in ['state_id','V','D','raw_stress']:
        meaning={'state_id':'四类当期价格压力类别','V':'波动压力标志','D':'下行损失压力标志','raw_stress':'组合原始压力'}[name]
        formula={'state_id':'V+2D；0=S0、1=S1、2=S2、3=S3，无严重度排序','V':'1(vol_20d>qV)，等于阈值不触发','D':'1(mdd_20d>qD)，等于阈值不触发','raw_stress':'V OR D'}[name];unit='类别/0或1';window='过去20个日收益'
        available='当日18:00；2015—2019标签为固定参考标准回放，非当时实时知道阈值'
    elif name.startswith('combined_') or name.startswith('vol_') or name.startswith('drawdown_'):
        meaning='相应维度当期事件状态机信息';formula='逐日递推；5个连续正常日才退出；未知段重新初始化';unit='布尔、交易日数或连接ID';window='仅当日及过去'
    elif name=='negative_return_fraction_20d':meaning='过去20日负收益比例';formula='mean(1[r_j<0])，要求20个有效收益';unit='0至1比例';window='过去20日'
    elif name=='worst_daily_return_20d':meaning='过去20日最差单日简单收益';formula='min(P_j/P_(j-1)-1)';unit='小数比例';window='过去20日'
    if name in OPTIONAL_FEATURES or name in ['adjusted_return','amihud_daily']:
        role='input' if name in OPTIONAL_FEATURES else 'metadata'
        source='观测到的沪深A股daily+相邻adj_factor；非精确沪深300池'
        available='当日18:00历史重建假设；版本与历史代码池真实性有限制'
        meaning='观测股票样本的'+{'down_fraction_proxy':'下跌家数比例','breadth_change_5d_proxy':'5日广度变化','mean_corr_60d_proxy':'60日等权股票对平均相关性','amihud_20d_proxy':'Amihud型20日流动性代理均值','amihud_20d_median_proxy':'Amihud型20日流动性代理中位数','adjusted_return':'相邻因子调整简单收益','amihud_daily':'日频价格冲击代理'}[name]
        formula={'down_fraction_proxy':'负调整收益股票数/有效调整收益股票数','breadth_change_5d_proxy':'down_fraction_d-down_fraction_(d-5)','mean_corr_60d_proxy':'(sum_t(sum_i z_ti)^2-N*(T-1))/(N*(N-1)*(T-1)); T=60, ddof=1','amihud_20d_proxy':'等权mean_i(mean_20(|adjusted_return_i|/amount_cny_i))','amihud_20d_median_proxy':'median_i(mean_20(|adjusted_return_i|/amount_cny_i))','adjusted_return':'close_d/close_(d-1)*factor_d/factor_(d-1)-1；必须交易日连续','amihud_daily':'abs(adjusted_return)/amount_cny'}[name]
        unit='人民币元的倒数' if 'amihud' in name else '相关系数' if 'corr' in name else '小数比例';window='60个有效相邻收益' if 'corr' in name else '每股20个连续有效日' if '20d' in name else '当前日或滞后5日'
        missing='停牌、零成交、相邻价格/因子无效、窗口不完整；不得填零；PROXY，默认非主输入'
    future_formulas={'future_return_20d':'P_e/P_t-1','future_vol_20d':'sqrt(252/20*sum(r_(t+1:e)^2))','future_mdd_20d':'max_(t<=u<=v<=e)(1-P_v/P_u)，包含P_t','future_downside_vol_20d':'sqrt(252/20*sum(r^2*1[r<0]))','future_worst_return_20d':'min_(t<j<=e)(P_j/P_t-1)','future_worst_daily_return_20d':'min_(t<j<=e)(P_j/P_(j-1)-1)','y_any_stress_next20':'完整未来区间中是否出现raw_stress；未来滚动状态有未知则NA','y_future_window_stress_20d':'1(future_vol_20d>qV OR future_mdd_20d>qD)','next_event_onset_type':'第一个未来新事件起点当天S1/S2/S3，非事后peak_type'}
    if name in future_formulas:formula=future_formulas[name];meaning='未来标签侧：'+name
    if name.startswith('y_new_'):formula='当且仅当对应维度当日处于风险集，且完整(t,t+H]内有已确认新事件起点；否则按资格取0或NA';meaning='未来新压力事件监督目标'
    if name.startswith('missing__'):meaning='对应特征缺失掩码';formula='isna(对应字段)';unit='布尔';role='metadata';available='asof_time'
    if name.startswith('basic_raw_'):meaning='当日来源每日指标原值，未直接入模';source='index_dailybasic';formula='原始指标；模型输入使用对应lag1';unit='原来源单位，见缓存官方定义';role='metadata'
    metadata_meanings={
        'sample_id':('固定周预测样本连接ID','CSI300-YYYYMMDD','字符串'),
        'index_code':('固定主指数代码','000300.SH，不拼接别的代码','代码'),
        'date':('对应SSE观测交易日','按已冻结交易日历排序','日期'),
        'asof_date':('完整交易周最后SSE开放日','每个完整ISO周的最后真实开放日','日期'),
        'asof_time':('研究预测信息截止时刻','asof_date 18:00 Asia/Shanghai，仅研究假设','带时区时间'),
        'research_available_at':('研究假设下的可得时刻','价格观测日18:00；不代表提供商真实历史发布时刻','带时区时间'),
        'availability_basis':('历史可得时间依据','保存研究假设说明','文本'),
        'source_available_at':('原库采集或入库可得时间','来源_available_at原值，不作历史公开时间','带时区时间'),
        'source_ingested_at':('原库入库观察时间','来源_ingested_at原值','带时区时间'),
        'source_row_hash':('来源逻辑内容哈希','来源_row_hash','SHA256标识'),
        'source_batch_id':('来源批次ID','来源_batch_id','字符串'),
        'basic_observation_date':('主输入使用的每日指标原观测日','当前交易日前一个SSE交易日','日期'),
        'basic_research_available_at':('滞后指标研究可得时刻','原观测日后一交易日18:00','带时区时间'),
        'feature_start':('最长主历史特征起点','当前交易日前60个交易日的价格日','日期'),
        'feature_end':('主历史特征终点','asof_date，包含当日价格','日期'),
        'feature_available_at':('本样本主输入最迟可得时刻','不晚于asof_time','带时区时间'),
        'label_start':('未来事件搜索开始日','asof_date之后第一个SSE交易日','日期'),
        'label_end':('完整未来标签窗结束日','asof_date之后第H个有价格的交易日，数据不足为NA','日期'),
        'label_available_at':('对称标签成熟时刻','完整H日label_end的18:00，阳性不提前','带时区时间'),
        'risk_set':('组合压力新事件预测风险集资格','已确认非事件日末且核心历史输入完整','布尔'),
        'target_valid':('主监督标签有效性','risk_set且未来H日完整','布尔'),
        'exclusion_reason':('标签排除原因','历史不足、初始化未知、not_at_risk、未来窗不足分别记录','文本'),
        'episode_id':('事件连接和评价ID','维度+观测到的起点日期；禁止入模','字符串'),
        'onset_date':('已确认新事件触发日','已知非事件状态后的首次压力；left_censored为NA','日期'),
        'last_stress_date':('该事件最后一次实际压力日','可能在预测时点之后；仅评价','日期'),
        'exit_confirm_date':('事件退出确认日','连续第5个正常日，不回填到第一个正常日','日期'),
        'lead_to_trigger':('预测到阈值事件触发的提前量','onset位置减asof位置','SSE交易日'),
        'horizon':('未来预测期限','主20、辅助5/40个SSE交易日','交易日'),
        'valid_state':('当日价格压力状态是否可计算','波动和损失的20日窗口均有效','布尔'),
        'measurement_standard_available_at':('固定参考测度最早完成时间','2019-12-31 18:00；禁止声称更早实时知道此阈值','带时区时间'),
        'reference_period_realtime_eligible':('是否已越过初始测度参考期','asof_date>2019-12-31；参考期只作历史训练回放','布尔'),
        'state_history_start':('递归事件状态历史起点','2015-01-05；feature_start仅标最长固定窗口起点','日期'),
        'retrospective_duration_days':('事件已观测持续期','end_position-start_position+1，含恢复确认日；右删失非最终持续期','交易日'),
        'retrospective_mdd':('事件观察起点之后的最大峰谷损失','对observation_start_date至exit_confirm或尾部价格计算窗口MDD，不含触发前已发生损失','非负小数比例'),
        'retrospective_peak_type':('事后压力类型摘要','期间出现S3则记S3，否则列S1/S2压力集合；不含恢复S0，不按S1/S2排序','类别'),
        'current_drawdown_at_prediction':('报警时已发生的20日期末回撤','使用asof_date的current_drawdown_20d，仅作事件评价诊断','非负小数比例'),
    }
    if name in metadata_meanings:meaning,formula,unit=metadata_meanings[name]
    if name in ['label_available_at','label_end','last_stress_date','exit_confirm_date']:available='未来窗成熟/事件事后确认才可得；禁止入模'
    if name.startswith('retrospective_') or table=='risk_episodes':role='metadata';available='事后事件评价，事件结束或数据尾部才得完整信息；禁止入模'
    return {'field':name,'meaning_zh':meaning,'formula':formula,'unit':unit,'source':source,'window':window,'research_availability':available,'missing_semantics':missing,'role':role,'protocol_version':PROTOCOL['protocol_version']}

def dictionaries():
    rows=[];coverage=[]
    paths=sorted(DATA.glob('*.parquet'))
    for path in paths:
        pf=pq.ParquetFile(path);table=path.stem
        coverage.append({'table':table,'path':str(path.relative_to(BASE)),'rows':pf.metadata.num_rows,'columns':len(pf.schema_arrow),'bytes':path.stat().st_size})
        for f in pf.schema_arrow:rows.append({'table':table,'path':str(path.relative_to(BASE)),'dtype':str(f.type),**field_spec(f.name,table)})
    panel=DATA/'stock_proxy_inputs/2015.parquet'
    for f in pq.ParquetFile(panel).schema_arrow:rows.append({'table':'stock_proxy_inputs/YYYY','path':'data/research_v2/stock_proxy_inputs/YYYY.parquet','dtype':str(f.type),**field_spec(f.name,'stock_proxy_inputs')})
    pd.DataFrame(rows).to_csv(AUDIT/'field_dictionary.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(coverage).to_csv(AUDIT/'output_coverage.csv',index=False,encoding='utf-8-sig')
    jsonwrite(CONFIG/'feature_specs.json',[r for r in rows if r['table']=='market_features_weekly'])
    jsonwrite(CONFIG/'label_specs.json',[r for r in rows if r['table'] in ['prediction_targets_weekly','future_outcomes_weekly','dimension_labels_daily']])
    return coverage

def build_reports():
    validation=readjson(AUDIT/'validation_checks.json');assert validation['status']=='PASS'
    cfg=readjson(CONFIG/'research_config.json');thr=readjson(CONFIG/'thresholds.json');statistics=readjson(AUDIT/'reference_development_statistics.json');chains=readjson(AUDIT/'sample_count_chain.json');stock=readjson(AUDIT/'stock_scope_certification.json');dims=readjson(AUDIT/'dimension_availability.json');sens=readjson(AUDIT/'sensitivity_reference_development.json');coverage=dictionaries()
    f=pd.read_parquet(DATA/'market_features_weekly.parquet');y=pd.read_parquet(DATA/'prediction_targets_weekly.parquet');s=pd.read_parquet(DATA/'state_labels_daily.parquet');e=pd.read_parquet(DATA/'risk_episodes.parquet');membership=pd.read_parquet(DATA/'fold_membership.parquet');plan=pd.read_parquet(AUDIT/'fold_manifest.parquet');proxies=pd.read_parquet(DATA/'stock_market_proxies_daily.parquet')
    primary=y.loc[y.horizon.eq(20)];valid=primary.loc[primary.target_valid]
    source_version=readjson(AUDIT/'source_version.json');budget_info=budget()
    write('protocol_changes.md',f'''# 本轮协议细化与旧材料差异

本轮规范来源：用户2026-11-05附件。`E:\\MLEC`中找到上一轮两份审计报告、字段/覆盖清单、有效文件快照和审计程序；没有找到额外课题设计与分工文档。未杜撰旧设计。旧审计保留原样，不覆盖。

| 事项 | 旧阶段 | 本轮冻结规范 |
| --- | --- | --- |
| 工作边界 | 只审计、不处理 | 正式全区间市场数据处理，仍不训练/调参/回测 |
| 状态定义 | 未规定 | 20日波动与窗口最大回撤，参考期固定80%分位，严格大于 |
| 参考标准 | 未估计 | 2015—2019完整20日观测，1199日；不使用2020以后拟合 |
| 收益 | 尚未生成 | 相邻真实close，首日NA，不借pre_close拼出更早历史 |
| 基本指标时点 | 数据日期存在 | 主输入滞后一交易日，18:00只是信息截止假设 |
| 事件 | 未构建 | 因果状态机，5日正常确认退出，初始/内部未知需重新初始化 |
| 周候选 | 582是窗口资格提示 | 保留599个完整交易周；582只是60日历史+20日未来的候选，风险集与成熟度再筛选 |
| 股票结构 | 完整性未认证 | 已核查上市/退市、停牌、映射和实际缺口；输出PROXY，精确沪深300与完整全市场认证BLOCKED |
| 初始化细化 | 附件要求不可默认正常 | 初始需5个已知正常日；确认前压力只记left_censored，不记真实新起点 |
| 代理细化 | 附件允许合格代理 | 连续20/60日完整同日期股票窗；等权聚合，零成交/停牌不填0；不将代理压力并入主标签 |
| 未来worst_return细化 | 附件未给公式 | 主字段为min(P_j/P_t-1)，另存最差单日收益，避免歧义 |
| 退出/分位/期限敏感性 | 未执行 | 仅预设单因素，测试详情放heldout，不择优 |
| 研究版本 | audit | {PROTOCOL['protocol_version']} |

主价格实际2850日与旧审计一致；没有为满足旧数字删除日期或拼接399300.SZ。源注册表与文件哈希留证。运行中出现过日志参数命名冲突、Windows临时映射释放和旧/新产物并发读取问题，已修正并由最终顺序全量运行及校验覆盖；失败日志保留，未伪造PASS。
''')
    write('measurement_protocol.md',f'''# 市场风险测度协议

协议 `{PROTOCOL['protocol_version']}`；配置哈希 `{source_version['protocol_hash']}`。研究预设在计算前冻结，实际配置见`config/research_v2/research_config.json`，来源版本`{source_version['source_version']}`。所有参数是本研究预设，不是金融学公认最优标准。

## 一、连续观测与五维

主序列为000300.SH价格指数、SSE交易日历，2015-01-05至2026-09-22，2850日；不混用399300.SZ，不含分红收益，不叠加个股因子。来源只选active登记文件，按内容/采集版本去重，再取自然键最新版本，查询与完整文件哈希在audit/research_v2。提供商重建历史并非真实历史修订PIT。

| 规则 | 公式/口径 | 方法归属 |
| --- | --- | --- |
| 日对数收益 | ln(P_d/P_(d-1))，首日NA | 本研究适配，标准日频定义 |
| 趋势 | P_d/P_(d-k)-1，k=5/20/60 | 本研究适配；不贴牛熊横盘标签 |
| 波动 | sqrt(252/k × sum(r²))，k个收益需k+1个价格 | 本研究适配；日收盘代理，不是日内RV |
| 下行半波动 | sqrt(252/20 × sum(r²1[r<0])) | 本研究适配，分母固定20 |
| 窗口最大回撤 | max_(d-k≤u≤v≤d)(1-P_v/P_u)，k=20/60 | 本研究适配；与R1终点累计损失不能混同 |
| 期末回撤 | 1-P_d/max(P_(d-k),...,P_d) | 借鉴R1损失测度的本研究窗口适配 |
| 活跃度 | amount均值20；5/20均值比；滞后换手率及5/20日变化 | 本研究适配，不等同流动性危机 |
| 单位 | amount千元、vol手；amount_cny=1000amount；换手率源百分数，变化为百分点 | 原来源定义与本研究单位转换 |
| Amihud型 | 每股abs(相邻因子比调整简单收益)/amount_cny；连续20日均值后等权均值/中位数 | 借鉴R4的本研究适配，非逐项复现原论文 |
| 广度 | 有效调整收益中负值股票比例及5日变化 | 本研究代理，不是精确沪深300或完整全市场 |
| 相关结构 | 60日同日期完整股票窗，剔除常数列；等权股票对平均相关 | 借鉴R3的描述性适配；不使用未来持续上市筛股 |

相关性用标准化列和的等价恒等式计算，不保存N×N矩阵；不做未经说明的pairwise缺失配对。停牌S端点、零成交、缺邻价/因子、非相邻交易日无有效收益，不填0。已保留333只退市证券；未用list_status=L筛池。股票旧代码缺master、缺少沪深完整映射和未解释停牌缺行情使精确历史池仍受阻；因此代理字段带PROXY和覆盖率，不把代理伪称第五维精确测量。

## 二、可得时间与阈值

每个完整交易周最后一个SSE开放日18:00预测，假期可早于周五；行情只有周中尾部时排除不完整周。18:00是本研究收盘信息截止假设。`source_available_at`只保留采集/入库证据，不解释成历史公开时间。另有`research_available_at/availability_basis`。dailybasic原观测日另存、输入滞后一个交易日；代理价格和因子也只声明历史重建假设。

阈值仅用{thr['reference_start']}—{thr['reference_end']}的{thr['reference_n']}个完整20日观测，`numpy.quantile(method='linear')`，版本记录在research_config。qV={thr['qV']:.12f}（年化比例，约{100*thr['qV']:.4f}%），qD={thr['qD']:.12f}（损失比例，约{100*thr['qD']:.4f}%）；threshold_version=`{thr['threshold_version']}`。

V=1(vol20>qV)，D=1(mdd20>qD)，严格大于；状态S0=00、S1=10、S2=01、S3=11。S0仅表示未触发这两项价格压力，不表示无风险；S1、S2没有天然严重度排序。无效窗为NA。2015—2019标签是按事后冻结参考标准生成的训练标签，不声称早年实时知道2019阈值；正式样本外始于2020。

## 三、事件与未来目标

状态机逐日递推：先确认5个连续正常日才初始化非事件状态；已确认非事件首次压力当天新起点；事件中再压力清零恢复计数；第5个正常日收盘才确认退出，当日末可回风险集。不回填起点或退出日，初始受压left_censored、尾部未退出right_censored；内部未知中断知识且重新初始化。组合、波动、下行损失各自事件表分开，S1发展为S3不重计组合事件。

主H=20、辅助5/40。事件起点搜索区间(t,t+H]不含t；仅当日末对应维度非活动、状态已确认、核心历史特征完整才在风险集。当前事件/恢复期标签NA；尾部不足H也NA，不当负例。所有正负标签都在完整H日结束18:00成熟，禁止阳性提前释放。辅助H40不缩短主H20。

未来完整路径收益、平方收益波动、半波动、最大回撤、最差累计收益和最差单日收益分表保存，未来回撤含P_t。三个对象明确区分：未来日期上的过去20日滚动压力、完全未来20日路径压力、新事件起点。未来滚动状态含未知时`y_any_stress_next20`为NA。`next_event_onset_type`只取首个新事件当天类别，事后最大损失/最终持续期/peak_type和所有事件ID不进模型。

## 四、时间划分与预设敏感性

初始2015—2019、开发2020—2022、最终时间外2023起。开发逐年扩展，fit_cutoff为上一年最后SSE交易日18:00；训练label_available_at≤cutoff，不能使用验证年结果。2022末目标到2023成熟的行标boundary_purged，不用于2022末选择；之后成熟可进入更晚预设折。最终按月首个周预测日前一交易日18:00计划更新，仅建立资格，无模型。

不随机切分、不全样本标准化/填补/SMOTE，不机械按20行隔离；测试特征允许读取此前历史。默认25个市场输入含类别state_id，源价格、采集时刻、未来列、split/sample_id/episode_id及事后事件属性不自动入模；估值和股票代理为单独可选组。

仅单因素：q=.75/.85；退出3/10日；以期末回撤替换mdd并估计其自己的初始阈值；H5/40保持状态20日不变。结果机械生成，不按测试数量或预测难易择优；测试细节单独放heldout。本轮无聚类/HMM/GARCH、无模型概率、无宏观有效性检验。
''')
    write('literature_basis.md','''# 文献依据与核验状态

核验日期：2026-11-05。网络仅查论文，未下载/更新金融数据。以下不宣称完整复现任何论文；正文无长段引用。

| 文献 | 实际可访问依据 | 本研究借鉴和边界 | 规则归属 |
| --- | --- | --- | --- |
| R1 Holló, Kremer & Lo Duca (2012), ECB WP1426 | [ECB原文PDF](https://www.ecb.europa.eu/pub/pdf/scpwps/ecbwp1426.pdf)；核验§3.2分布变换及股票CMAX定义，PDF第15–19页相关段落 | CISS五个金融市场部门并非本课题五维。其递归经验CDF和约两年终点累计损失不能直接叫本研究固定分位阈值或20日窗口最大回撤 | 多维压力思想为原文方法；20日窗口、固定2015—2019阈值与四类状态是本研究适配/预设 |
| R2 Chen, Chen & Cai，2023在线/2024卷28 pp2483–2499 | [出版社页面](https://link.springer.com/article/10.1007/s00500-023-08496-z)摘要与书目信息已核验；[PMC指定全文](https://pmc.ncbi.nlm.nih.gov/articles/PMC10235853/)遇验证码，全文细节未核验 | 摘要支持VaR型中国市场多类别预警背景；不把估计风险当无误差真值，不声称已核验其全文验证设计 | 研究背景依据；详细全文方法待验证 |
| R3 Pang & Lin (2025) | [Frontiers原文](https://www.frontiersin.org/journals/physics/articles/10.3389/fphy.2025.1647667/full)；核验§3.1股票池、§3.2相关矩阵状态说明 | 原文股票池含整个研究期持续上市约束；本研究不采用此事后筛股。相关结构仅作描述代理，不复制其聚类，也不把五个类别当五维 | 相关结构启发；60日完整窗口和动态观测股票池为本研究预设 |
| R4 Amihud (2002), DOI 10.1016/S1386-4181(01)00024-6 | [2002出版社页面](https://www.sciencedirect.com/science/article/pii/S1386418101000246)正文403，未声称读到出版全文；实际核验[作者NYU 2000年8月工作稿](https://archive.nyu.edu/jspui/bitstream/2451/27420/2/S-AM-00-10.pdf)引言、§2.1（PDF第3–6页） | 绝对日收益/成交金额是粗价格冲击代理。使用人民币、相邻调整简单收益、每股连续20日及等权市场聚合，是本研究适配；不复现原稿NYSE年度规则 | 基础比率有原文依据；单位和窗口/排除规则为本研究预设 |
| R5 Cerqueira, Torgo & Mozetič (2020) | [作者机构发表版本PDF](https://kt.ijs.si/igor_mozetic/papers/CerTorMoz-TimeSer-MACH-20.pdf)，摘要、引言及结果讨论PDF第18页相关段落；[作者目录](https://web.cs.dal.ca/~ltorgo/publication/2020_ctm20/) | 讨论时序依赖、平稳性和多期OOS评价，不是宣称所有时序一律不能任何交叉验证；本研究采用指定向前时间划分 | 时序评价原则有文献依据；年份、H、label成熟和purge规则均为本研究设计 |

252年化、5/20/60窗口、80%主阈值、75/85敏感性、5日退出及3/10敏感性、18:00、H20及5/40、初始化正常期和月度更新计划均属于**本研究预设参数**，没有冒充论文公认最优值。精确历史证券池、提供商日内历史发布时间、宏观真实公告/修订时刻均为**待验证**。代码测试通过不能证明该测度是唯一正确经济学定义；文献合理性也不能证明预测有效。
''')
    state_rows=[]
    for role,stat in statistics.items():
        state_rows.append([role,stat['valid_state_days'],str(stat['state_counts']),stat['known_new_combined_events'],stat['median_observed_episode_days'],stat['max_observed_episode_days'],stat['right_censored_episodes'],stat['recovery_days_inside_active_episode']])
    chain_rows=[[role]+[value[k] for k in ['candidate_weeks','market_feature_complete_weeks','main_at_risk_weeks','complete_main_label_weeks','positive_weeks','deduplicated_events_covered','events_with_true_warning_opportunity']] for role,value in chains.items()]
    maturity_rows=[[role]+[value[k] for k in ['mature_by_period_end_weeks','positive_mature_by_period_end','deduplicated_mature_events','boundary_unmatured_weeks']] for role,value in chains.items()]
    sens_rows=[[r['variant'],r['period'],f"{r['state_agreement']:.4f}",r['known_events'],r['event_count_change'],r['median_signed_onset_shift_trading_days'],r['single_stress_day_episode_count'],r['valid_targets'],r['positive_targets']] for r in sens]
    independent=[]
    for role,stat in statistics.items():
        for state_name in ['S0','S1','S2','S3']:
            independent.append([role,state_name]+[f"{stat.get(k+'_by_state',{}).get(state_name,{}).get('mean',float('nan')):.6g}" for k in ['downside_vol_20d','worst_daily_return_20d','current_drawdown_20d','down_fraction_proxy']])
    write('label_validation_report.md',f'''# 市场标签验证报告

主阈值：qV={100*thr['qV']:.4f}%年化波动，qD={100*thr['qD']:.4f}%窗口最大回撤；参考期{thr['reference_start']}—{thr['reference_end']}，1199日，线性分位数。以下只展示初始参考/开发期资料；2023以后诊断在heldout单独保存，不用来选标签。

## 状态与事件

{mdtable(['时期','有效状态日','S0/S1/S2/S3计数','已确认新组合事件','事件观测持续期中位数','最大观测持续期','右删失事件','事件中恢复日'],state_rows)}

完整状态占比、转换矩阵、单压力日事件、压力日数与恢复日数在`audit/research_v2/reference_development_statistics.json`。持续期在各期末截断计算，右删失不冒充最终已知持续期。S1和S2不可按编号当严重度。

## 非构造指标诊断

{mdtable(['时期','类别','下行半波动均值','最差单日收益均值','期末回撤均值','观测股票下跌比例均值'],independent)}

这些仅作经济解释和边界检查；下行半波动、最差单日损失与期末回撤依然与价格压力相关，不能当独立因果证明。广度来自已排除停牌/缺因子的观测股票样本，认证状态PROXY。没有仅凭构造指标组间差异宣称标签科学。

## 样本数量链

{mdtable(['时期','候选周','市场特征完整周','主风险集周','完整标签周','阳性周','样本覆盖去重事件','期内具预警机会事件'],chain_rows)}

这些数量回答不同问题。风险集仅包含已确认非事件状态；恢复期样本仍保留且主标签NA。样本覆盖去重事件可能含跨年未来起点，期内事件按onset归属，不能把两列机械看成同一分母。具有机会要求完整H日前史且至少一个有效周风险集点；这是冻结测度下的历史回放机会，不声称2015年已有实际预测系统。

当期截止时可真正用于拟合/选择的成熟口径另列：

{mdtable(['时期','当期末已成熟目标','其中阳性周','成熟样本覆盖去重事件','跨边界未成熟周'],maturity_rows)}

上面的完整标签周表示用当前本地全样本后来可计算，不能用于冒充当期末已经知道。初始参考期资料选择只用初始期状态/事件和截至2019末成熟目标；开发年边界另外按逐折manifest隔离。固定阈值的历史训练标签有`measurement_standard_available_at=2019-12-31 18:00`，所有训练折还核对已越过该测度校准时刻；参考期没有被宣称实时评价。

## 预设单因素敏感性

{mdtable(['方案','时期','状态一致率','新组合事件','相对主事件变化','匹配起点偏移中位数/交易日','单压力日碎片','有效目标','阳性目标'],sens_rows)}

起点偏移按20交易日内最近起点一对一贪心匹配；未匹配计数和类别稀疏明细在JSON。H5/H40只改事件搜索期限，状态一致率应为1；未因辅助40日期限统一截短20日样本。敏感性没有模型、择优或排名；测试期明细仅在`heldout/sensitivity_details.json`。

## 实际执行的检查

{mdtable(['检查','结果','证据'],[[r['check'],r['status'],str({k:v for k,v in r.items() if k not in ['check','status']})] for r in validation['checks']])}

人工路径测试日志与JUnit为`audit/research_v2/logs/unit_tests.log`、`unit_tests.xml`。真实截断在2020-06-30、2022-12-30、2024-06-28重算全部此前主输入/实时状态/事件起点，并重新读取历史股票返回检查代理；未来扰动在2022-06-30后进行，初始阈值、此前输入与事件不变。未要求尚未成熟标签或事后结束信息提前一致。逐折训练成熟度、验证年边界、输入白名单已执行断言。

结论仅限代码与数据规则通过这些检查。事件量有限、每周目标重叠且多个阳性周可能指同一事件，后续概率评价须同时报告事件级结果和不确定性；本轮未为凑事件改参数，未训练预测器，未检验宏观增量有效性。
''')
    horizons=[]
    for H in [20,5,40]:
        yy=y.loc[y.horizon.eq(H)];vv=yy.loc[yy.target_valid]
        horizons.append([H,len(yy),int(yy.horizon_complete.sum()),int(yy.risk_set.sum()),len(vv),fmt(vv.asof_date.min()),fmt(vv.asof_date.max()),fmt(vv.label_end.max())])
    write('market_data_handoff.md',f'''# 给宏观侧与后续实证研究的交接

已交付完整市场侧真实数据，没有等待宏观数据；没有预测概率、模型效果、调参或策略结果。源目录只读。主口径000300.SH价格指数；阈值版本`{thr['threshold_version']}`，协议`{PROTOCOL['protocol_version']}`。

## 读取接口

- 默认输入：`data/research_v2/market_features_weekly.parquet`，严格按`config/research_v2/feature_whitelist.json`选列；state_id是类别。估值单独可选。
- 股票代理扩展输入：`market_features_weekly_with_proxies.parquet`，代理默认不进入主输入组；有覆盖、股票数和缺失标记。
- 目标：`prediction_targets_weekly.parquet`是长表，键`sample_id+horizon`；主H20使用`risk_set & target_valid`及`y_new_episode_next20`。未来路径观测单独在`future_outcomes_weekly.parquet`。
- 事件：`risk_episodes.parquet`；连接：`sample_to_event.parquet`。未来ID、onset、exit、最终持续期与严重度只用于标签/评价。
- 折：`fold_membership.parquet`，计划`audit/research_v2/fold_manifest.parquet`。`eligible_for_fit`必须true；模型只能用成熟目标。
- 字段字典：`audit/research_v2/field_dictionary.csv`，含中文、公式、单位、来源、窗口、可得时点、缺失含义、角色与版本。

{mdtable(['H','保留周数','未来路径完整周','主风险集周','有效新事件目标周','有效时点首日','有效时点末日','最后标签结束日'],horizons)}

候选周范围{fmt(f.asof_date.min())}—{fmt(f.asof_date.max())}，共{len(f)}；有效60日主输入周{int(f.market_features_complete.sum())}。60日历史+20日未来的窗口候选仍为582，进一步风险集后主目标有效{len(valid)}周。排除详情在`sample_exclusions.parquet`，尾部未来不足保持NA；辅助40日期限不影响主样本。

## 宏观as-of合并

`sample_id`固定为CSI300-YYYYMMDD，`asof_time`为该完整周最后SSE交易日18:00（Asia/Shanghai）。每条宏观事实必须带真实公布/修订可得时间：只合并`macro_research_available_at<=asof_time`的最近已公布版本，不以统计期末日期代替公告时间。只有日期没有小时的宏观公告，需双方预先约定保守可得规则，记录依据；不能假定同日18:00前一定公布。

`source_available_at`、原库`_available_at`可能是2026年采集/入库，不能用于伪造早年公开时间。市场`research_available_at`基于收盘重建假设，dailybasic滞后1日；这与宏观真实公告时刻不是同一种证据。

M和M+Z须共享sample_id、目标、风险集、折及共同样本版本。宏观覆盖不足时双方联合确定共同日期和排除原因，再生成一个共同样本掩码；不能各自dropna后直接比较。宏观修订、混频聚合、发布时间、覆盖尚待联合验收，不影响本轮市场侧交付完成。

## 后续训练与评价约束

开发2020/2021/2022向前扩展；每折fit_cutoff前标签必须已按完整H成熟。2022末未成熟目标在2022末选择中boundary_purged，之后可进入更晚训练计划。最终2023起按月预设更新计划，允许使用更早已成熟历史，但不能用测试反馈改变阈值/模型定义。无初始2015—2019内部实时回测。

后续标准化、填补、特征选择、重采样仅训练折拟合；测试特征可读取此前历史。输入白名单禁止所有数值列自动入模。预测配对schema为`paired_prediction_schema.json`，当前只有schema，无虚假概率。

事件归属按onset_date所在评价期；每事件一次检出，优先最早有效报警；报警必须在onset前、H窗口内、对应风险集。`lead_to_trigger`是交易日到阈值触发的距离，不是提前于股灾开始。`current_drawdown_at_prediction`保留报警时已发生损失；不能把未来事件尚未发生的损失伪填为0。跨边界与完整H先行窗口、周机会字段均保留。

五维状态：

{mdtable(['维度','状态','限制'],[[r['dimension'],r['status'],r['limitation']] for r in dims])}

`feature_start`表示最长固定60日窗口起点；递归状态另有`state_history_start`保存历史递推起点。`reference_period_realtime_eligible`明确标出参考期不能当作实时测度评价。相关结构使用同一日期完整股票窗，但不同窗口股票组成可变，其变化也可能影响均值，因此必须连同股票数/覆盖率解释。

股票证据：5554只master范围内沪深股票，333只退市保留；4265条行情来自master中无记录的旧/异常代码，具体为`000043.SZ/000022.SZ/300114.SZ`；282674条重建上市池缺行情中271480有同日S停牌记录，11194未解释。248条可用映射仅BSE，精确沪深历史代码池仍BLOCKED；观测代理可用，不称沪深300精确成分广度。

联合验收需确认：共同宏观样本、真实公告与修订as-of规则、可选代理是否进入扩展M、模型训练折预处理和事件去重评价实现。代码正确、测度有依据、样本是否充足、宏观是否有效是四个不同结论；本轮只完成前两项的可复核材料与样本数量证据，宏观有效性未验证。
''')
    write('run_summary.md',f'''# 市场侧正式处理运行摘要

本轮已实现并运行完整真实数据流水线，协议`{PROTOCOL['protocol_version']}`。没有训练/调参/回测，没有宏观有效性结果。

{mdtable(['产物','行数','列数','路径'],[[r['table'],r['rows'],r['columns'],r['path']] for r in coverage])}

来源：9个依赖接口、登记active文件哈希冻结，非递归拼库。主序列2850日，599个完整周候选，{int(f.market_features_complete.sum())}个核心历史特征完整周，582个历史+20日未来窗口候选，{len(valid)}个主风险集且标签完整周；有效主时点{fmt(valid.asof_date.min())}—{fmt(valid.asof_date.max())}。末日标签成熟时间按完整期限对称处理。

实际阈值：年化波动{100*thr['qV']:.4f}%，20日窗口最大回撤{100*thr['qD']:.4f}%，1199个初始期日观测。初始/开发状态事件和单因素敏感性见label_validation_report，测试细节独立heldout，不作选择。

验证：{validation['checks'][0]['tests']}项公式/事件单元测试通过；真实历史截断、未来扰动、参考阈值不变、全部折成熟度和完整主流程语义复现通过。折计划{len(plan)}个，折成员{len(membership)}行。检查证据在audit/research_v2/validation_checks.json和unit_tests.xml。

新增产物预算2GiB、安全余量5GiB；当前统计产物约{budget_info['artifact_bytes']/1024**2:.1f}MiB（本摘要生成前），磁盘空余{budget_info['free_bytes']/1024**3:.1f}GiB。股票代理临时矩阵约242MiB，已关闭并仅清理本轮自建文件；没有保存股票两两相关矩阵。最终精确体积见日志run_complete。

复现（无需安装依赖，原环境只读使用，源目录不写pycache）：

```powershell
E:\\quant\\.venv\\Scripts\\python.exe -B -X utf8 E:\\MLEC\\scripts\\research_v2\\run_pipeline.py --stage all
```

统一入口先检查源哈希与冻结配置，复用校验通过的检查点；`--force`可完整重算。日志位于audit/research_v2/logs；输入/输出哈希、逐查询SQL、清单和字段字典均已保存。旧审计与源项目没有被改写；主注册表大小/mtime复核一致。

限制：历史重建不是严格历史版本PIT；沪深股票池/代码史与部分缺行情未完全认证，流动性和结构为PROXY；未验证宏观公告、覆盖或增量预测效果；事件数量有限、周目标重叠，不能用阳性周数冒充独立事件数。停止在市场侧研究数据和报告交付，不进入模型或类JEV开发。
''')
    # Copy primary protocol rules into a machine-readable availability/role reference.
    jsonwrite(AUDIT/'research_manifest.json',{'protocol_version':PROTOCOL['protocol_version'],'source_version':source_version,'primary_index':'000300.SH','market_features_file':'market_features_weekly.parquet','proxy_features_file':'market_features_weekly_with_proxies.parquet','primary_horizon':20,'candidate_weeks':len(f),'valid_primary_targets':len(valid),'feature_white_list':'config/research_v2/feature_whitelist.json','heldout_diagnostics_separate':True,'training_performed':False,'macro_effectiveness_tested':False})
    log('reports_complete',files=6,field_dictionary_rows=len(pd.read_csv(AUDIT/'field_dictionary.csv')))
