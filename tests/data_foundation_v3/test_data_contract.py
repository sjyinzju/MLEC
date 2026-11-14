"""Real-source regressions. Deliberately no model fitting or experiment imports."""
import json
import numpy as np
import pandas as pd
import pytest
from scripts.data_foundation_v3.common import ROOT,STANDARD,TZ
from scripts.data_foundation_v3.features import make_weekly
from scripts.data_foundation_v3.validate import causality_check

@pytest.fixture(scope='module')
def facts():return pd.read_parquet(STANDARD/'macro_facts.parquet')

def accepted(f,s,p):return f[(f.series_id==s)&(f.period_end==pd.Timestamp(p))&f.quality_status.isin(['strict_pit_eligible','conservative_release_reconstructed'])]

@pytest.mark.parametrize('sid,value', [('industrial_va_yoy',-2.9),('industrial_va_ytd_yoy',4.0),('retail_sales_yoy',-11.1),('retail_sales_ytd_yoy',-0.2)])
def test_signed_monthly_and_cumulative(facts,sid,value):
    q=accepted(facts,sid,'2022-04-30');assert len(q);assert np.allclose(q.value,value)

def test_combined_months_not_fabricated(facts):
    q=facts[facts.series_id.isin(['industrial_va_yoy','retail_sales_yoy'])&facts.quality_status.eq('strict_pit_eligible')]
    assert not q.period_end.dt.month.isin([1,2]).any()

def test_january_2025_m2_is_real_reprint(facts):
    q=accepted(facts,'m2_yoy','2025-01-31');assert len(q);assert q.value.eq(7.0).all()
    assert q.quality_status.eq('conservative_release_reconstructed').all()
    assert q.research_available_at.eq(pd.Timestamp('2025-02-14 23:59:59',tz=TZ)).all()
    assert q.source_url.str.contains('cctv.cn/2025/02/14').all()

def test_m1_definitions(facts):
    assert facts.loc[facts.series_id.eq('m1_yoy'),'period_end'].lt(pd.Timestamp('2025-01-01')).all()
    assert facts.loc[facts.series_id.eq('m1_new_yoy'),'period_end'].ge(pd.Timestamp('2025-01-01')).all()

def test_pmi_early_release_preserved(facts):
    q=accepted(facts,'pmi_mfg','2022-01-31');assert q.release_at.dt.date.astype(str).eq('2022-01-30').any()

def test_actual_delayed_gdp(facts):
    # Preserved original page displays 2022/10/24 09:30; no fixed-day rule.
    q=accepted(facts,'gdp_real_yoy','2022-09-30');assert q.release_at.dt.date.astype(str).eq('2022-10-24').any()

def test_safe_unit(facts):
    q=accepted(facts,'usdcny_fixing','2025-12-31');assert len(q);assert np.allclose(q.value,7.0288)

def test_lpr_regime_and_quote_date(facts):
    q=accepted(facts,'lpr_1y','2019-08-31');assert len(q);assert np.allclose(q.value,4.25)
    assert q.observation_date.eq(pd.Timestamp('2019-08-20')).all()

def test_dr007_is_explicit_column(facts):
    q=accepted(facts,'dr007','2026-11-13');assert len(q);assert np.allclose(q.value,1.3723)
    assert q.source_url.str.endswith('prr-chrt.csv').all()

def test_no_cumulative_loan_as_monthly(facts):
    q=accepted(facts,'rmb_loans_ytd_flow','2015-06-30');assert q.value.eq(65600).any()
    monthly=accepted(facts,'new_rmb_loans','2015-06-30');assert not monthly.value.eq(65600).any()

def test_gov_curve_definition(facts):
    q=facts[(facts.series_id=='cgb_10y')&facts.quality_status.eq('conservative_release_reconstructed')]
    assert q.adjustment_note.str.contains('CFETS 11:30').all()

def test_actual_historical_cutoffs(facts):assert len(causality_check(facts))==3

def test_financial_loan_is_not_tsf_component(facts):
    q=accepted(facts,'new_rmb_loans','2024-02-29')
    assert len(q) and q.value.eq(14500).all()
    assert q.quality_status.eq('conservative_release_reconstructed').all()

def test_negative_monthly_loan_preserved(facts):
    q=accepted(facts,'new_rmb_loans','2026-04-30')
    assert len(q) and q.value.eq(-100).all()

def test_rounded_cumulative_difference_not_certified(facts):
    for period in ['2026-05-31','2026-06-30']:
        assert accepted(facts,'new_rmb_loans',period).empty

def test_reserve_excel_days_are_month_periods(facts):
    q=facts[facts.series_id.eq('fx_reserves')]
    assert q.period_end.dt.is_month_end.all()
    assert len(q[(q.period_end==pd.Timestamp('2014-01-31'))&q.quality_status.eq('latest_vintage_reconstructed')])

def test_stock_reprint_date_is_not_backdated(facts):
    q=accepted(facts,'tsf_stock','2025-01-31')
    assert len(q) and q.value.eq(415.2).all()
    assert q.research_available_at.dt.strftime('%Y-%m-%d').eq('2025-02-17').all()

def test_all_unverified_vintages_are_retrieval_only(facts):
    q=facts[facts.quality_status.eq('latest_vintage_reconstructed')]
    assert q.research_available_at.ge(q.retrieved_at).all()

def test_trade_currency_and_monthly_sign(facts):
    usd=accepted(facts,'imports_yoy','2014-11-30')
    cny=accepted(facts,'imports_cny_yoy','2014-11-30')
    assert usd.value.eq(-6.7).any() and cny.value.eq(-6.5).any()
    assert usd.currency.eq('USD').all() and cny.currency.eq('CNY').all()

def test_later_trade_attachment_cannot_inherit_older_page_date(facts):
    q=facts[facts.source_url.str.contains('20150310')&facts.source_name.eq('MOFCOM dated trade bulletin')&facts.period_end.eq(pd.Timestamp('2015-01-31'))]
    assert len(q) and q.quality_status.eq('latest_vintage_reconstructed').all()


def test_reviewed_trade_images_keep_currency_and_repost_date(facts):
    q=accepted(facts,'exports_yoy','2020-11-30')
    image=q[q.source_name.eq('MOFCOM visually checked trade bulletin')]
    assert len(image) and image.value.eq(21.1).all()
    assert image.research_available_at.eq(pd.Timestamp('2021-07-08 23:59:59',tz=TZ)).all()
    cny=accepted(facts,'exports_cny_yoy','2020-11-30')
    assert cny.value.eq(14.9).any()


def test_combined_trade_image_does_not_invent_monthly_values(facts):
    q=facts[facts.source_name.eq('MOFCOM visually checked trade bulletin')&facts.period_end.eq(pd.Timestamp('2020-02-29'))]
    assert set(q.series_id)=={'exports_cny_ytd_yoy','imports_cny_ytd_yoy'}


def test_replaced_trade_image_is_retrieval_only(facts):
    q=facts[facts.source_name.eq('MOFCOM visually checked trade bulletin')&facts.period_end.eq(pd.Timestamp('2018-03-31'))]
    assert len(q) and q.quality_status.eq('latest_vintage_reconstructed').all()
    assert q.release_at.isna().all()


def test_tsf_scopes_never_share_a_series_id(facts):
    from scripts.data_foundation_v3.scopes import TSF_BASE,regime_at
    q=facts[facts.concept_id.isin(TSF_BASE)]
    assert q.groupby('series_id').statistical_scope_id.nunique().eq(1).all()
    valid=q[q.quality_status.isin(['strict_pit_eligible','conservative_release_reconstructed'])]
    assert (valid.statistical_scope_id=='tsf_'+valid.period_end.map(regime_at)).all()
    assert not valid.series_id.str.endswith('unverified').any()
    assert facts.loc[facts.series_id.eq('tsf_stock'),'period_end'].ge(pd.Timestamp('2019-12-01')).all()


def test_tsf_new_scope_has_no_previous_old_scope_feature(facts):
    market=pd.DataFrame({'sample_id':['scope_check'],'asof_time':[pd.Timestamp('2018-08-31 18:00',tz=TZ)]})
    w,line=make_weekly(facts,market,series=['tsf_stock__scope_201807'])
    assert pd.notna(w['macro__tsf_stock__scope_201807__latest'].iloc[0])
    assert pd.isna(w['macro__tsf_stock__scope_201807__previous'].iloc[0])
    assert pd.isna(w['macro__tsf_stock__scope_201807__change'].iloc[0])
