"""Focused tests for Z* publication-time and statistical-definition rules."""

import pandas as pd
import pytest

from scripts.market_state.z_star import Release, describe_releases, release_series


def _release(period, value, *, published=None, scope='scope', revision='dated_announcement'):
    date = pd.Timestamp(period)
    when = pd.Timestamp(published) if published else date + pd.Timedelta(days=10)
    return Release(date, when, value, f'{period}/{value}', scope, '%', revision)


def _describe(records, *, ytd=False):
    return describe_releases({r.period: r for r in records}, frequency='M', ytd=ytd)


def test_same_day_and_future_publications_cannot_form_release_prediction():
    releases = [
        _release('2024-01-31', 1), _release('2024-02-29', 2),
        _release('2024-03-31', 3), _release('2024-04-30', 9),
    ]
    current = releases[-1].period
    innovation = _describe(releases)[current]['release_innovation']
    assert innovation.value == pytest.approx(7)
    assert all(parent.time < innovation.parents[0].time for parent in innovation.parents[1:])
    assert _describe(releases + [_release('2024-05-31', 900)])[current] == _describe(releases)[current]
    revised = releases[:2] + [_release('2024-03-31', 30, published='2024-05-10'), releases[-1]]
    assert 'release_innovation' not in _describe(revised)[current]


def test_trade_year_reset_and_credit_scope_guards():
    december = _release('2023-12-31', 100)
    january = _release('2024-01-31', 1)
    february = _release('2024-02-29', 2)
    assert 'release_change' not in _describe([december, january, february], ytd=True)[january.period]
    assert _describe([december, january, february], ytd=True)[february.period]['release_change'].value == 1
    same_month_old_scope = _release('2023-02-28', 200, scope='old')
    assert 'release_yoy_pct' not in _describe([same_month_old_scope, january, february])[february.period]


def test_first_documented_edition_survives_later_revisions():
    first = _release('2024-01-31', 10)
    revised = _release('2024-01-31', 11, published='2024-04-10')
    records = pd.DataFrame.from_records([
        dict(period_end=r.period, effective_available_at=r.time, value=r.value, source_record_id=r.record_id,
             statistical_scope_id=r.scope, unit=r.unit, revision_status=r.revision, series_id='source')
        for r in (first, revised)
    ])
    specs = dict(series_id='source', required_start='2024-01-01', required_end='2024-12-31')
    assert release_series(records, specs) == {first.period: first}


def test_explicit_later_compilation_does_not_seed_innovation():
    releases = [
        _release('2024-01-31', 1, revision='later_annual_compilation_not_first_release'),
        _release('2024-02-29', 2), _release('2024-03-31', 3), _release('2024-04-30', 9),
    ]
    result = _describe(releases)[releases[-1].period]
    assert 'release_trend3' in result
    assert 'release_innovation' not in result
