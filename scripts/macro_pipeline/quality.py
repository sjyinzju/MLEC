"""Auditable coverage and cross-source checks; differences are not overwritten."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.experiment_framework.common import ROOT,digest,save_frame,write_json,write_text
from scripts.macro_pipeline.govern import CORE,GROUPS,validate_facts

ACCEPTED=['strict_pit_eligible','conservative_release_reconstructed']

def build():
    f=pd.read_parquet(ROOT/'data/standardized/macro/macro_facts.parquet');validate_facts(f)
    a=f[f.quality_status.isin(ACCEPTED)].copy()
    conflicts=a.groupby(['series_id','period_start','period_end','research_available_at']).value.nunique()
    assert not conflicts.gt(1).any(),'Conflicting accepted same-time facts require adjudication'
    assert np.isfinite(a.value).all()
    assert a.research_available_at.le(a.retrieved_at).all()
    # A PMI reference month can end after its survey release. No other series can.
    future=a.period_end.gt(a.research_available_at.dt.tz_localize(None))
    assert a.loc[future,'series_id'].str.startswith('pmi_').all()
    expected_core=set(pd.period_range('2014-12','2022-12',freq='M'))
    for sid in CORE[:5]:assert expected_core<=set(a[a.series_id.eq(sid)].period_end.dt.to_period('M')),sid
    rows=[];gaps=[];comparisons=[]
    for sid in sorted(set(f.series_id)|{s for v in GROUPS.values() for s in v}):
        raw=f[f.series_id.eq(sid)];accepted=a[a.series_id.eq(sid)]
        row={'series_id':sid,'candidate_rows':len(raw),'accepted_rows':len(accepted),'strict_rows':int(raw.quality_status.eq('strict_pit_eligible').sum()),
             'accepted_start':str(accepted.period_end.min())[:10] if len(accepted) else '', 'accepted_end':str(accepted.period_end.max())[:10] if len(accepted) else '',
             'quality':';'.join(sorted(raw.quality_status.unique())) if len(raw) else 'blocked_no_verified_source'}
        if len(raw) and raw.frequency.iloc[0] in ['M','Q']:
            freq=raw.frequency.iloc[0];expected=pd.period_range('2015-01','2022-12',freq=freq)
            observed=set(accepted.period_end.dt.to_period(freq));structural=set()
            if sid in ['industrial_va_yoy','retail_sales_yoy']:structural={p for p in expected if p.month in [1,2]}
            if sid in ['industrial_va_ytd_yoy','retail_sales_ytd_yoy']:structural={p for p in expected if p.month==1}
            if sid=='lpr_1y':structural={p for p in expected if p<pd.Period('2019-08',freq='M')}
            if sid=='m1_new_yoy':structural=set(expected)
            required=set(expected)-structural
            missing=required-observed
            row.update(expected_dev_history=len(required),accepted_dev_history=len(required&observed),missing_dev_history=len(missing),structural_periods=len(structural))
            for period in sorted(missing):gaps.append({'series_id':sid,'period':str(period),'reason':'no_accepted_announcement_value'})
        elif len(raw):
            # SSE calendar is an explicit proxy for research alignment, not the
            # complete interbank quotation calendar (which includes makeup days).
            cal=pd.read_parquet(ROOT/'audit/research_v2/sse_calendar.parquet')
            expected=set(cal.loc[cal.is_open.astype(bool)&cal.date.between('2015-01-05','2022-12-31'),'date'])
            observed=set(accepted.period_end)
            row.update(expected_dev_history=len(expected),accepted_dev_history=len(expected&observed),missing_dev_history=len(expected-observed),structural_periods=0)
            for date in sorted(expected-observed):gaps.append({'series_id':sid,'period':str(date.date()),'reason':'missing_on_SSE_research_calendar; interbank_calendar_may_differ'})
        rows.append(row)
    mappings=[('cpi_yoy','cn_cpi','nt_yoy'),('cpi_mom','cn_cpi','nt_mom'),('ppi_yoy','cn_ppi','ppi_yoy'),('ppi_mom','cn_ppi','ppi_mom'),('m2_yoy','cn_m','m2_yoy'),('m1_yoy','cn_m','m1_yoy'),('pmi_mfg','cn_pmi','pmi010000'),('pmi_new_orders','cn_pmi','pmi010500'),('pmi_nonmfg','cn_pmi','pmi020100')]
    for sid,table,column in mappings:
        other=pd.read_parquet(ROOT/f'data/raw/macro/third_party_sources/quant/{table}.parquet')
        other['period_end']=pd.to_datetime(other.month.astype(str),format='%Y%m')+pd.offsets.MonthEnd(0)
        other=other.sort_values(['_ingested_at','_row_hash']).drop_duplicates('period_end',keep='last')
        official=a[a.series_id.eq(sid)].sort_values('research_available_at').drop_duplicates('period_end',keep='first')
        z=official[['period_end','value','source_url','research_available_at']].merge(other[['period_end',column]],on='period_end',validate='one_to_one')
        z=z.rename(columns={column:'latest_provider_value'});z['series_id']=sid;z['difference']=z.value-z.latest_provider_value
        z['status']=np.where(z.difference.abs()<=.051,'agrees_at_published_precision','different_vintage_or_definition; retain_official_announcement')
        comparisons.append(z)
    for sid,table,column in [('industrial_va_yoy','RPT_ECONOMY_INDUS_GROW','BASE_SAME'),('industrial_va_ytd_yoy','RPT_ECONOMY_INDUS_GROW','BASE_ACCUMULATE'),('retail_sales_yoy','RPT_ECONOMY_TOTAL_RETAIL','RETAIL_TOTAL_SAME'),('retail_sales_ytd_yoy','RPT_ECONOMY_TOTAL_RETAIL','RETAIL_ACCUMULATE_SAME'),('new_rmb_loans','RPT_ECONOMY_RMB_LOAN','RMB_LOAN')]:
        other=pd.read_parquet(ROOT/f'data/raw/macro/third_party_sources/eastmoney/{table}.parquet')
        other['period_end']=pd.to_datetime(other.REPORT_DATE)+pd.offsets.MonthEnd(0)
        official=a[a.series_id.eq(sid)].sort_values('research_available_at').drop_duplicates('period_end',keep='first')
        z=official[['period_end','value','source_url','research_available_at']].merge(other[['period_end',column]],on='period_end',validate='one_to_one').rename(columns={column:'latest_provider_value'})
        z['series_id']=sid;z['difference']=z.value-z.latest_provider_value
        z['status']=np.where(z.difference.abs()<=(50 if sid=='new_rmb_loans' else .051),'agrees_at_published_precision','different_vintage_or_definition; retain_official_announcement')
        comparisons.append(z)
    comparison=pd.concat(comparisons,ignore_index=True)
    save_frame(ROOT/'audit/framework/macro_crosscheck.parquet',comparison)
    summary=comparison.groupby('series_id').agg(overlap=('value','size'),differences=('status',lambda s:int(s.str.startswith('different').sum()))).reset_index()
    coverage=pd.DataFrame(rows);coverage.to_csv(ROOT/'data/metadata/macro_acceptance_catalog.csv',index=False,encoding='utf-8-sig')
    save_frame(ROOT/'audit/framework/macro_missing_periods.parquet',pd.DataFrame(gaps))
    # Large jumps are review flags, not automatic deletions of real shocks.
    jumps=[]
    for sid,g in a.groupby('series_id'):
        g=g.sort_values(['period_end','research_available_at']).drop_duplicates('period_end',keep='first').copy()
        delta=g.value.diff();scale=float(delta.abs().median())
        mask=delta.abs()>max(10*scale,1.)
        for i,r in g[mask].iterrows():jumps.append({'series_id':sid,'period_end':str(r.period_end),'value':r.value,'change':delta.loc[i],'source_url':r.source_url,'disposition':'flag_for_review; official_value_preserved; not_winsorized'})
    write_json(ROOT/'audit/framework/macro_jump_review.json',jumps)
    source_rows=[]
    for p in sorted((ROOT/'data/raw/macro').rglob('*')):
        if p.is_file():source_rows.append({'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)})
    write_json(ROOT/'data/metadata/raw_source_registry.json',source_rows)
    write_json(ROOT/'audit/framework/data_acceptance.json',{'core_monthly_2014_12_through_2022_12_complete':True,'same_time_accepted_conflicts':0,'nonfinite_accepted':0,'strict_pit_core':False,'quality_counts':f.quality_status.value_counts().to_dict(),'crosschecks':summary.to_dict('records'),'jump_flags':len(jumps)})
    write_text(ROOT/'reports/data_quality/macro_coverage.md','# 宏观覆盖与实际缺口\n\n核心五条月度序列 2014-12—2022-12 均有逐期官方公告值。Shibor 1W/3M 为官方报价档案，按报价日结束后可用；没有历史更正版本日志。\n\n'+coverage.to_markdown(index=False)+'\n\naccepted 指公告认证值或明确降级的官方金融报价档案，不包含事后宏观历史表。日频应有数量使用 SSE 研究日历代理，不能据此宣称银行间报价日历完整。工业与零售 1—2 月合并发布：当月序列的 1、2 月为结构性缺失，累计序列保留 1—2 月。LPR 2019-08 才有当前机制，M1 新定义 2025-01 才开始；不回填。逐期缺口：`audit/framework/macro_missing_periods.parquet`。\n')
    write_text(ROOT/'reports/data_quality/macro_reconciliation.md','# 宏观语义修复与交叉核对\n\n同伴八个采集脚本已在相邻 scripts 目录找到并按哈希归档；不再将其列为缺失。原包保留于 `data/raw/macro/original_submissions/v1/`。新版采集器补齐分页，并以缓存公告正文和官方列表日期为证据。\n\n- 工业、零售的当月同比与累计同比分别建序列；2022-04 工业当月 -2.9%、累计 4.0%，不混用。下降/负值照原文保留。\n- 贷款单月增量和年初累计分开，仅采明确单月陈述；不能识别的原记录保留 blocked。\n- PMI 新订单映射 `pmi010500`，`pmi010200` 是中型企业 PMI。早期跨月发布和 2022-01 月末前发布保留真实日期。\n- GDP 当季同比与累计同比分开；后续公告中的历史季度修订保留该次公告时间，不能提前使用。\n- CPI/PPI 环比、同比依据表头顺序解析；核心 CPI 使用不包括食品和能源行。M1 的 2025 年新定义独立为 `m1_new_yoy`。\n- SAFE 美元中间价原单位为每 100 美元折人民币，除以 100 得 CNY/USD。国债收益率是 CFETS 11:30 均值曲线，不能称中债收盘收益率。\n\n'+summary.to_markdown(index=False)+'\n\n交叉核对使用本地 QuantData 提取的事后历史表。价格和 PMI 的一致仅验证字段/数值，不证明发布版本。M2 等差异保留官方当时公告值，不用后来历史值覆盖；差异逐行保存于 `audit/framework/macro_crosscheck.parquet`。极端跳变只列入复核表，不截尾真实疫情冲击。原修复对应表 `audit/framework/macro_corrections.parquet`，全链路 `data/metadata/data_lineage.parquet`。\n')
    write_text(ROOT/'reports/data_quality/macro_pit_validation.md','# 发布时间与版本验收\n\n`research_available_at <= asof_time` 为硬门槛。官方 NBS 原公告时间由保存的官方检索响应 docDate 佐证；PBOC 迁站后的网页时间可能变成 2025 年，改用保存的官方目录相邻日期。公告只有日期时一律设北京时间 23:59:59，因此周五公告不会进入当日 18:00 预测。PMI 统计月份可在日历月末前公布，不等于未来数据。\n\n| 等级 | 依据与用途 |\n|---|---|\n| strict_pit_eligible | 逐期官方正文数值 + 官方公告日期，保留后续版本；可用于公告版本实验 |\n| conservative_release_reconstructed | Shibor、CFETS 国债、SAFE 官方历史报价；日期末可用，但缺更正日志，明确限制 |\n| latest_vintage_reconstructed | 原交付和第三方历史表未证实当时版本；可得时间为实际获取时间，不能用于 2015 年回测 |\n| blocked | 字段/口径无法可靠识别，禁止模型输入 |\n\n主核心组采用“官方公告 + 官方金融报价日末”政策，不标成全变量 strict PIT。未来若获得金融报价更正档案可建立更严格版本。原始、标准化、特征三层分开；后续旧季度修订先在季度内选版本，再选最近经济季度。不能按最后一次发布日期把旧季度当成最新季度。\n\n实际源文件和 SHA256：`data/metadata/raw_source_registry.json`；官方 URL、发布日期、数值原文路径和转换说明：macro_facts / data_lineage。DR007 同伴接口返回不同期限字段，未能取得可验证历史，不替换为 R007/FDR007。进出口目前仅事后历史候选池；不纳入主实验。\n')
    return coverage

if __name__=='__main__':print(build()[['series_id','accepted_rows']].to_string(index=False))
