"""Separate full-history acceptance gaps from complete development core coverage."""
from pathlib import Path
import sys
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.common import ROOT,write_text,write_json

def build():
    facts=pd.read_parquet(ROOT/'data/standardized/macro/macro_facts.parquet')
    accepted=facts[facts.quality_status.isin(['strict_pit_eligible','conservative_release_reconstructed'])]
    rows=[]
    for sid,g in facts.groupby('series_id'):
        freq=g.frequency.iloc[0]
        if freq not in ['M','Q']:continue
        # Completed statistical periods through the most recent collected month.
        expected=pd.period_range('2014-01','2026-10' if freq=='M' else '2026-09',freq=freq)
        known=set(accepted[accepted.series_id.eq(sid)].period_end.dt.to_period(freq))
        for p in expected:
            if p in known:continue
            reason='missing_accepted_publication; latest_candidate_may_exist'
            if sid in ['industrial_va_yoy','retail_sales_yoy'] and p.month in [1,2]:reason='structural_Jan_Feb_combined_release'
            elif sid in ['industrial_va_ytd_yoy','retail_sales_ytd_yoy'] and p.month==1:reason='structural_no_separate_January_release'
            elif sid=='lpr_1y' and p<pd.Period('2019-08',freq='M'):reason='structural_current_LPR_regime_not_started'
            elif sid=='m1_new_yoy' and p.year<2025:reason='structural_new_M1_definition_not_started'
            elif sid=='m1_yoy' and p.year>=2025:reason='structural_old_M1_definition_ended'
            rows.append({'series_id':sid,'period':str(p),'reason':reason,'development_or_initial':2015<=p.year<=2022})
    gaps=pd.DataFrame(rows);gaps.to_csv(ROOT/'audit/framework/macro_full_history_gaps.csv',index=False,encoding='utf-8-sig')
    core=gaps[gaps.series_id.isin(['cpi_yoy','ppi_yoy','pmi_mfg','pmi_new_orders','m2_yoy'])]
    write_json(ROOT/'audit/framework/full_core_coverage.json',{'scope':'2014-01 through 2026-10','gaps':core.to_dict('records'),
        'm2_2025_01_evidence':{'value_in_candidate_pool':7.0,'primary_announcement_in_current_pboc_index':False,
        'republication':'https://www.wlmq.gov.cn/wlmqs/c119358/202602/3194010f277a421a91fa1737aaa68891.shtml',
        'contemporaneous_secondary_report':'https://finance.people.com.cn/n1/2025/0214/c1004-40418849.html',
        'decision':'Retain latest candidate; do not invent original-release certification or silently backdate the 2026 republication'}})
    path=ROOT/'reports/data_quality/macro_coverage.md';text=path.read_text(encoding='utf-8')
    marker='\n## 全历史范围补充验收'
    text=text.split(marker)[0]+marker+'\n\n上述 expected_dev_history 仅针对 2015—2022。完整月度范围 2014-01—2026-10 的核心公告缺口如下；不能把开发期覆盖齐全说成全历史所有版本认证完成。\n\n'+core.to_markdown(index=False)+'\n\n2025-01 M2 候选值为 7.0%，当前央行目录中未定位原公告。已有 2025-02-14 人民网报道和 2026 年政府网站转载，未直接将转载日期回写为历史首发认证。该缺口不影响 2020—2022 开发结果；当时周度可继续使用此前已知 M2，但不能声称该月公告值已纳入。全部月/季候选的结构性和未认证缺口见 `audit/framework/macro_full_history_gaps.csv`。这也是最终时间外评价前需要补核的事项。\n'
    write_text(path,text)
    return core

if __name__=='__main__':print(build().to_string(index=False))
