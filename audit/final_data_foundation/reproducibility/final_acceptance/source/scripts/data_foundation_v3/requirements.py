"""Economically specified candidate universe; never imports model results."""
from .common import CONFIG,VERSION,write_json
from .scopes import TSF_BASE,TSF_REGIMES,scoped_id

GROUPS={
 'growth':{
  'pmi_mfg':('制造业PMI','level','index','M'),
  'pmi_new_orders':('制造业PMI新订单指数','level','index','M'),
  'pmi_nonmfg':('非制造业商务活动指数','level','index','M'),
  'industrial_va_yoy':('规模以上工业增加值当月实际同比','yoy','%','M'),
  'industrial_va_ytd_yoy':('规模以上工业增加值累计实际同比','ytd_yoy','%','M'),
  'retail_sales_yoy':('社会消费品零售总额当月名义同比','yoy','%','M'),
  'retail_sales_ytd_yoy':('社会消费品零售总额累计名义同比','ytd_yoy','%','M'),
  'gdp_real_yoy':('GDP单季实际同比','yoy','%','Q'),
  'gdp_real_ytd_yoy':('GDP累计实际同比','ytd_yoy','%','Q'),
  'fai_ytd_yoy':('全国固定资产投资（不含农户）累计名义同比','ytd_yoy','%','M')},
 'prices':{s:(n,m,'%','M') for s,n,m in [
  ('cpi_yoy','居民消费价格同比','yoy'),('cpi_mom','居民消费价格环比','mom'),
  ('core_cpi_yoy','扣除食品能源的核心CPI同比','yoy'),
  ('ppi_yoy','工业生产者出厂价格同比','yoy'),('ppi_mom','工业生产者出厂价格环比','mom')]},
 'credit':{
  'm2_yoy':('广义货币M2同比（各期可比口径）','yoy','%','M'),
  'm1_yoy':('狭义货币M1同比（2024年底前口径）','yoy','%','M'),
  'm1_new_yoy':('狭义货币M1同比（2025年起新口径）','yoy','%','M'),
  'tsf_stock':('社会融资规模存量（各期统计范围）','stock','万亿元','M'),
  'tsf_stock_yoy':('社会融资规模存量可比同比','yoy','%','M'),
  'tsf_month_flow':('社会融资规模当月增量','flow','亿元','M'),
  'tsf_ytd_flow':('社会融资规模年初累计增量','ytd_flow','亿元','M'),
  'new_rmb_loans':('金融机构人民币贷款当月增加','flow','亿元','M'),
  'rmb_loans_ytd_flow':('金融机构人民币贷款年初累计增加','ytd_flow','亿元','M'),
  'rmb_loan_balance_yoy':('金融机构人民币贷款余额可比同比','yoy','%','M')},
 'rates':{
  'shibor_on':('Shibor隔夜定盘','level','%','D'),
  'shibor_1w':('Shibor1周期限定盘','level','%','D'),
  'shibor_3m':('Shibor3个月期限定盘','level','%','D'),
  'dr007':('存款类机构以利率债质押7天回购成交加权利率','level','%','D'),
  'cgb_1y':('CFETS11:30国债收益率曲线1年期','level','%','D'),
  'cgb_10y':('CFETS11:30国债收益率曲线10年期','level','%','D'),
  'term_spread_10y_1y':('同一CFETS曲线10年减1年期限利差','spread','percentage_points','D'),
  'lpr_1y':('2019年8月新机制1年期LPR','level','%','M')},
 'external':{
  'usdcny_fixing':('美元兑人民币中间价','level','CNY/USD','D'),
  'exports_yoy':('海关货物出口当月美元值同比','yoy','%','M'),
  'imports_yoy':('海关货物进口当月美元值同比','yoy','%','M'),
  'fx_reserves':('国家外汇储备余额','stock','亿美元','M'),
  'exports_cny_yoy':('海关货物出口当月人民币值同比','yoy','%','M'),
  'imports_cny_yoy':('海关货物进口当月人民币值同比','yoy','%','M'),
  'exports_cny_ytd_yoy':('海关货物出口累计人民币值同比','ytd_yoy','%','M'),
  'imports_cny_ytd_yoy':('海关货物进口累计人民币值同比','ytd_yoy','%','M')}
}

# Keep the existing unsuffixed TSF IDs for the current (December 2019+) scope.
# Historical definitions and uncertain modern restatements have distinct IDs.
for _base in TSF_BASE:
    _name,_measure,_unit,_freq=GROUPS['credit'][_base]
    GROUPS['credit'][_base]=(_name+'（2019年12月扩围后）',_measure,_unit,_freq)
    for _key,_start,_end,_label in TSF_REGIMES[:-1]:
        GROUPS['credit'][scoped_id(_base,_key)]=(_name+'（'+_label+'）',_measure,_unit,_freq)
    GROUPS['credit'][scoped_id(_base,'unverified')]=(_name+'（历史统计范围未认证，仅候选）',_measure,_unit,_freq)

def specifications():
    out=[]
    for group,items in GROUPS.items():
        for sid,(name,measure,unit,freq) in items.items():
            source='NBS' if group in ['growth','prices'] else 'PBOC' if group=='credit' else 'CFETS' if group=='rates' else ('SAFE' if sid in ['fx_reserves','usdcny_fixing'] else 'GAC/NBS')
            start={'m1_new_yoy':'2025-01-01','lpr_1y':'2019-08-20','dr007':'2014-12-15','fai_ytd_yoy':'2011-01-01','tsf_stock':'2014-12-31','tsf_stock_yoy':'2014-12-31'}.get(sid,'2014-01-01')
            concept=sid.split('__scope_')[0]
            scope=sid.split('__scope_')[1] if '__scope_' in sid else '201912' if sid in TSF_BASE else None
            regime=next((r for r in TSF_REGIMES if r[0]==scope),None)
            if regime:start=max(start,regime[1])
            structural='none'
            if sid in ['industrial_va_yoy','retail_sales_yoy']:structural='January and February are a combined publication; do not split into single months'
            if sid in ['industrial_va_ytd_yoy','retail_sales_ytd_yoy','fai_ytd_yoy']:structural='January not separately released'
            if sid.startswith('tsf_stock'):structural='2015 stock is quarterly; monthly from 2016; pre-2014-12 not in original publication regime'
            out.append(dict(series_id=sid,series_name=name,series_group=group,measure_type=measure,unit=unit,frequency=freq,
              currency='USD' if sid in ['fx_reserves','exports_yoy','imports_yoy'] else 'CNY' if group=='credit' or '_cny_' in sid or sid=='usdcny_fixing' else 'NA',
              concept_id=concept,statistical_scope_id='tsf_'+scope if scope else 'as_registered',required=scope!='unverified',
              required_start=max(start,'2014-01-01'),required_end=min(regime[2],'2026-09-30') if regime else '2026-09-30',collection_end='2026-11-14',
              original_regime_start=start if sid in ['m1_new_yoy','lpr_1y','dr007','fai_ytd_yoy','tsf_stock','tsf_stock_yoy'] else 'earlier_history_in_raw; not asserted first-ever publication',
              source_priority=source,structural_rule=structural,late_start_warning='No retrospective filling before regime exists',
              economic_purpose={'growth':'景气和实体需求','prices':'通胀和成本','credit':'货币信用供给','rates':'流动性与融资价格','external':'外部需求和汇率环境'}[group],
              design_basis='User data foundation task + archived research design; no model-performance selection',
              source_definition_url={'NBS':'https://www.stats.gov.cn/','PBOC':'https://www.pbc.gov.cn/diaochatongjisi/116219/116225/index.html','CFETS':'https://www.chinamoney.com.cn/','SAFE':'https://www.safe.gov.cn/safe/tjsj1/','GAC/NBS':'https://www.stats.gov.cn/zs/tjws/zytjzbqs/zckze/202411/t20241115_1957489.html'}[source],
              max_staleness_days=10 if freq=='D' else 150 if freq=='Q' else 75))
    return out

def write_config():
    write_json(CONFIG/'requirements.json',{'version':VERSION,'variables':specifications(),'basis':'2014 onward baseline; frozen market unchanged; raw earlier histories retained'})
    write_json(CONFIG/'quality_levels.json',{
     'strict':['strict_pit_eligible'],
     'conservative':['strict_pit_eligible','conservative_release_reconstructed'],
     'latest_at_retrieval':['strict_pit_eligible','conservative_release_reconstructed','latest_vintage_reconstructed'],
     'blocked':'never usable',
     'policy':'Only explicitly dated announcement values may be strict. Reprints and quote histories without correction logs are conservative. Latest archives become available at retrieval; never backdated.'})
    write_json(CONFIG/'feature_sets.json',{'version':VERSION,'selection_basis':'economic groups, declared before any new model work',
      'groups':{g:list(v) for g,v in GROUPS.items()},'quality_levels':['strict','conservative','latest_at_retrieval'],
      'custom_selection':'CLI --series comma-separated IDs or --groups comma-separated group names; supports any subset and combination',
      'dataset_policy':'Keep every frozen sample; explicit per-set eligibility, no complete-case deletion; M and M+Z must reuse the identical eligibility manifest'})
