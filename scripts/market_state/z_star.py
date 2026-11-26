"""Build the macro-only Z* extension from admitted release evidence."""

from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .macro import prepare


FEATURE_VERSION = 'macro-z-star-v1'
QUALITY_VIEW = 'historical_reconstructed'
CORE_RELEASES = (
    'pmi_mfg', 'pmi_new_orders', 'industrial_va_yoy', 'retail_sales_yoy',
    'gdp_real_yoy', 'cpi_yoy', 'ppi_yoy', 'm2_yoy',
)
TRADE = ('exports_cny_ytd_yoy', 'imports_cny_ytd_yoy')
SHARED_BULLETIN_CLOCKS = {
    'pmi_new_orders': 'pmi_mfg', 'retail_sales_yoy': 'industrial_va_yoy',
    'ppi_yoy': 'cpi_yoy', 'imports_cny_ytd_yoy': 'exports_cny_ytd_yoy',
}
CREDIT_SCOPES = (
    'tsf_stock_yoy__scope_pre_201807__definition_tsf_201501_pre_201807',
    'tsf_stock_yoy__scope_201809', 'tsf_stock_yoy', 'tsf_stock_yoy__scope_202301',
)
LOAN_SCOPES = ('loan_201501', 'loan_202301')
DAILY = {
    'shibor_on': ('latest',),
    'shibor_1w': ('latest',),
    'shibor_3m': ('latest', 'change_20obs'),
    'dr007': ('latest', 'change_5obs', 'change_20obs', 'vol_20obs'),
    'cgb_1y': ('latest', 'change_20obs'),
    'cgb_10y': ('latest', 'change_20obs'),
    'term_spread_10y_1y': ('latest', 'change_20obs'),
    'usdcny_fixing': ('latest', 'change_20obs', 'vol_20obs'),
}
RETAINED_FORMULAS = {
    'latest': 'Latest admitted vintage of the latest available economic period',
    'change_5obs': 'Latest minus fifth prior admitted quote within the same statistical definition',
    'change_20obs': 'Latest minus twentieth prior admitted quote within the same statistical definition',
    'vol_20obs': 'Population standard deviation of the last 20 successive quote differences within the same definition',
}
NEW_EDITION_EXCLUSIONS = {
    'later_annual_compilation_not_first_release', 'dated_later_table_not_first_release',
    'dated_monthly_table_version_not_first_release', 'explicit_201807_scope_backcast',
}


def source_paths(data_root: Path, macro_source: Path | None = None) -> tuple[Path, ...]:
    data_root = Path(data_root)
    facts = Path(macro_source) if macro_source is not None else (
        data_root.parent / 'standardized/macro/v4/macro_facts.parquet'
    )
    return (
        facts, data_root / 'sources/macro_repairs.parquet',
        data_root / 'macro/historical_reconstructed/features.parquet',
        data_root / 'macro/historical_reconstructed/lineage.parquet',
        data_root / 'macro/specifications.json', data_root / 'feature_sets.json',
        data_root / 'fold_membership.parquet',
    )


def column(series_id, name):
    return f'macro__{series_id}__{name}'


@dataclass(frozen=True)
class Release:
    period: pd.Timestamp
    time: pd.Timestamp
    value: float
    record_id: str
    scope: str
    unit: str
    revision: str


@dataclass(frozen=True)
class Observation:
    value: float = np.nan
    parents: tuple[Release, ...] = ()


def release_series(facts, spec):
    """One immutable earliest admitted record per period, within the formal scope."""
    selected = facts.loc[
        facts.series_id.eq(spec.get('source_series_id', spec['series_id']))
        & facts.period_end.between(spec['required_start'], spec['required_end'])
    ]
    if 'filter_scope_id' in spec:
        selected = selected.loc[selected.statistical_scope_id.eq(spec['filter_scope_id'])]
    earliest = selected.drop_duplicates(['period_end', 'effective_available_at'], keep='last')
    earliest = earliest.drop_duplicates('period_end', keep='first').sort_values('period_end')
    return {
        r.period_end: Release(r.period_end, r.effective_available_at, r.value,
                              r.source_record_id, r.statistical_scope_id, r.unit, r.revision_status)
        for r in earliest.itertuples(index=False)
    }


def consecutive(current, prior, frequency, ytd):
    if prior.scope != current.scope or prior.unit != current.unit:
        return False
    if ytd and current.period.year != prior.period.year:
        return False
    gap = (current.period - prior.period).days
    return 0 < gap <= (110 if frequency == 'Q' else 65)


def describe_releases(releases, *, frequency, ytd=False):
    """Freeze descriptors when each period is first documented, before weekly holding."""
    result = {}
    innovations = {}
    for period, current in releases.items():
        prior = [p for p in releases.values() if p.period < period and p.time < current.time]
        chain = [current]
        for prev in reversed(prior):
            if not consecutive(chain[-1], prev, frequency, ytd):
                break
            chain.append(prev)
            if len(chain) == 4:
                break
        stats = {}
        if len(chain) >= 2:
            stats['release_change'] = Observation(current.value - chain[1].value, tuple(chain[:2]))
        if len(chain) >= 3:
            change = (current.value - chain[2].value) / 2
            stats['release_trend3'] = Observation(change, tuple(chain[:3]))
        if len(chain) == 4 and all(r.revision not in NEW_EDITION_EXCLUSIONS for r in chain):
            error = current.value - np.mean([r.value for r in chain[1:]])
            raw = Observation(float(error), tuple(chain))
            stats['release_innovation'] = raw
            history = [
                obs for key, obs in innovations.items()
                if key < period and obs.parents[0].time < current.time
                and obs.parents[0].scope == current.scope and obs.parents[0].unit == current.unit
            ][-12:]
            if len(history) >= 6:
                scale = np.std([obs.value for obs in history], ddof=0)
                if scale > 1e-12:
                    parents = tuple(dict.fromkeys(p for obs in [raw, *history] for p in obs.parents))
                    stats['scaled_innovation'] = Observation(float(error / scale), parents)
            innovations[period] = raw
        last_year = releases.get(period - pd.offsets.MonthEnd(12))
        if (last_year and last_year.time < current.time and last_year.scope == current.scope
                and last_year.unit == current.unit and last_year.value > 0):
            stats['release_yoy_pct'] = Observation(100 * (current.value / last_year.value - 1), (current, last_year))
        result[period] = stats
    return result


class MacroPanel:
    def __init__(self, base, lineage, facts, specs):
        self.base = base.set_index('asof_date')
        self.points = lineage[['asof_date', 'asof_time']].drop_duplicates().sort_values('asof_date')
        if (not self.points.asof_date.is_unique or not self.points.asof_time.is_monotonic_increasing
                or not self.base.index.equals(pd.Index(self.points.asof_date))):
            raise ValueError('Macro release anchors are not identical, unique and chronological')
        self.lineage = {key: block.set_index('asof_date').loc[self.base.index]
                        for key, block in lineage.groupby('series_id', sort=False)}
        self.facts = facts
        self.specs = specs
        self.obs = {}
        self.catalog = []
        self.derived_lineage = []
        available = facts[['period_end', 'effective_available_at', 'value', 'source_record_id',
                           'statistical_scope_id', 'unit', 'revision_status']]
        self.records = {values[3]: Release(*values) for values in available.itertuples(index=False, name=None)}

    def emit(self, name, values, *, group, sources, formula, unit, frequency, kind='derived', states=None):
        if name in self.obs or len(values) != len(self.points):
            raise ValueError(f'Invalid or duplicate Z* feature {name}')
        self.obs[name] = tuple(values)
        self.catalog.append(dict(
            feature=name, group=group, sources=list(sources), formula=formula, unit=unit,
            frequency=frequency, kind=kind,
            source_names=[self.specs[sid]['series_name'] for sid in sources],
            source_definition_urls=[self.specs[sid]['source_definition_url'] for sid in sources],
            availability='All parent source timestamps must be at or before the weekly 18:00 Asia/Shanghai prediction clock',
            missing='NaN for unavailable or unsupported observations; imputation is learned in the training fold',
        ))
        if states is None:
            states = [None] * len(values)
        for point, obs, state in zip(self.points.itertuples(index=False), values, states, strict=True):
            valid = np.isfinite(obs.value)
            if valid and not obs.parents:
                raise ValueError(f'No parent evidence for {name} at {point.asof_date}')
            when = max((r.time for r in obs.parents), default=pd.NaT)
            if pd.notna(when) and when > point.asof_time:
                raise ValueError(f'Future macro parent for {name} at {point.asof_date}')
            self.derived_lineage.append(dict(
                asof_date=point.asof_date, asof_time=point.asof_time, feature=name,
                available_at=when, status='AVAILABLE' if valid else (
                    state if state not in ('AVAILABLE', None) else 'INSUFFICIENT_COMPARABLE_HISTORY'
                ),
                source_record_ids=json.dumps(list(dict.fromkeys(r.record_id for r in obs.parents)), separators=(',', ':')),
            ))

    def emit_series(self, sid, name, values, formula, *, unit=None, kind='derived'):
        spec = self.specs[sid]
        self.emit(column(sid, name), values, group=spec['series_group'], sources=[sid],
                  formula=formula, unit=unit or spec['unit'], frequency=spec['frequency'],
                  kind=kind, states=self.lineage[sid].status)

    def retain(self, sid, name):
        values = []
        for point, value in zip(self.lineage[sid].itertuples(index=False), self.base[column(sid, name)], strict=True):
            if not np.isfinite(value):
                values.append(Observation())
                continue
            parents = (self.records[point.source_record_id],)
            if name.endswith('obs'):
                size = 6 if name == 'change_5obs' else 21
                parents = tuple(self.records[key] for key in json.loads(point.daily_history_parent_ids)[-size:])
            values.append(Observation(value, parents))
        self.emit_series(sid, name, values, RETAINED_FORMULAS[name], kind='retained')

    def release_panel(self, sid, fields):
        spec = self.specs[sid]
        releases = release_series(self.facts, spec)
        descriptions = describe_releases(releases, frequency=spec['frequency'], ytd=sid in TRADE)
        empty = Observation()
        grid = {field: [] for field in fields}
        previous_clock = pd.NaT
        for point in self.lineage[sid].itertuples(index=False):
            release = releases.get(point.period_end)
            stats = descriptions.get(point.period_end, {})
            if release is None:
                cached = {}
            else:
                event = pd.notna(previous_clock) and previous_clock < release.time <= point.asof_time
                innovation = stats.get('release_innovation', empty)
                cached = {
                    **stats,
                    'release_age_days': Observation((point.asof_time - release.time).total_seconds() / 86400, (release,)),
                    'new_release': Observation(float(event), (release,)) if pd.notna(previous_clock) else empty,
                    'new_innovation': (
                        innovation if event else Observation(0.0, innovation.parents)
                    ) if np.isfinite(innovation.value) and pd.notna(previous_clock) else empty,
                }
            previous_clock = point.asof_time
            for field in fields:
                grid[field].append(cached.get(field, empty))
        for field, series in grid.items():
            formula, unit = fields[field]
            self.emit_series(sid, field, series, formula, unit=unit)

    def combine(self, name, names, group, formula, unit, operation, *, same_period=False):
        values = []
        source_by_feature = {item['feature']: item for item in self.catalog}
        sources = list(dict.fromkeys(sid for key in names for sid in source_by_feature[key]['sources']))
        for parts in zip(*(self.obs[key] for key in names), strict=True):
            if (all(np.isfinite(part.value) for part in parts)
                    and (not same_period or len({part.parents[0].period for part in parts}) == 1)):
                parents = tuple(dict.fromkeys(parent for part in parts for parent in part.parents))
                values.append(Observation(float(operation(*(part.value for part in parts))), parents))
            else:
                values.append(Observation())
        self.emit(name, values, group=group, sources=sources, formula=formula,
                  unit=unit, frequency='weekly_asof')


CHANGE = ('Difference between consecutive earliest documented editions; require comparable periods', None)
TREND = ('Mean change per transition over three comparable earliest documented periods', None)
INNOVATION = ('Earliest documented value minus the mean of its three strictly prior comparable first-known periods', None)
SCALED = ('Historical prediction innovation divided by SD of the preceding 6–12 eligible strictly prior innovations', 'ratio')
EVENT = ('Latest economic period first became documented after the preceding weekly anchor', 'binary')
FRESH_INNOVATION = ('Historical prediction innovation at a new-release anchor; zero on an eligible held-value week', None)
AGE = ('Elapsed days since the earliest admitted publication for the currently held period', 'days')
YOY = ('100 × (earliest documented value ÷ same month one year earlier within this definition − 1)', '%')


def add_macro_features(panel):
    f = column
    for sid in CORE_RELEASES:
        panel.retain(sid, 'latest')
        fields = dict(release_change=CHANGE, release_trend3=TREND, release_innovation=INNOVATION,
                      new_innovation=FRESH_INNOVATION)
        if sid not in SHARED_BULLETIN_CLOCKS:
            fields.update(new_release=EVENT, release_age_days=AGE)
        if sid in ('pmi_mfg', 'cpi_yoy', 'm2_yoy', 'gdp_real_yoy'):
            fields['scaled_innovation'] = SCALED
        panel.release_panel(sid, fields)
    for sid in ('pmi_mfg', 'cpi_yoy', 'm2_yoy'):
        events = panel.obs[f(sid, 'new_innovation')]
        rolling = []
        for position in range(len(events)):
            window = events[max(0, position - 3):position + 1]
            if len(window) == 4 and all(np.isfinite(obs.value) for obs in window):
                parents = tuple(dict.fromkeys(p for obs in window for p in obs.parents))
                rolling.append(Observation(sum(obs.value for obs in window), parents))
            else:
                rolling.append(Observation())
        panel.emit_series(sid, 'innovation_sum4w', rolling,
                          'Sum of observed historical prediction innovations over the last four weekly anchors')
    for sid in CREDIT_SCOPES:
        panel.retain(sid, 'latest')
        panel.release_panel(sid, {'release_trend3': TREND, 'release_innovation': INNOVATION})
        panel.combine(f(sid, 'minus_m2'), [f(sid, 'latest'), f('m2_yoy', 'latest')], 'credit',
                      'Same economic period TSF growth minus M2 growth within the named TSF definition',
                      'percentage points', lambda tsf, m2: tsf - m2, same_period=True)
    for scope in LOAN_SCOPES:
        loan = 'new_rmb_loans__definition_' + scope
        loan_balance = 'rmb_loan_balance_yoy__definition_' + scope
        panel.release_panel(loan, {'release_yoy_pct': YOY})
        panel.retain(loan_balance, 'latest')
        panel.release_panel(loan_balance, {'release_trend3': TREND})
    for sid, fields in DAILY.items():
        for field in fields:
            panel.retain(sid, field)
    for sid in TRADE:
        panel.retain(sid, 'latest')
        fields = dict(release_change=CHANGE, release_trend3=TREND)
        if sid not in SHARED_BULLETIN_CLOCKS:
            fields.update(new_release=EVENT, release_age_days=AGE)
        panel.release_panel(sid, fields)
    panel.retain('fx_reserves', 'latest')
    panel.release_panel('fx_reserves', {'release_yoy_pct': YOY, 'release_age_days': AGE})

    sid = 'dr007'
    releases = release_series(panel.facts, panel.specs[sid])
    quotes = list(releases.values())
    rank = {}
    for offset, quote in enumerate(quotes):
        prior = [r for r in quotes[max(0, offset - 252):offset] if r.time < quote.time and r.scope == quote.scope]
        if len(prior) == 252:
            percentile = np.mean([(r.value < quote.value) + 0.5 * (r.value == quote.value) for r in prior])
            rank[quote.period] = Observation(float(percentile), tuple([quote, *prior]))
    panel.emit_series(sid, 'pressure_rank252', [rank.get(p, Observation()) for p in panel.lineage[sid].period_end],
                      'Midrank of current DR007 against its 252 strictly prior as-of quote observations', unit='ratio')
    panel.combine(f('shibor_3m', 'minus_on'), [f('shibor_3m', 'latest'), f('shibor_on', 'latest')], 'rates',
                  'Three-month minus overnight Shibor of the same observation day',
                  'percentage points', lambda term, overnight: term - overnight, same_period=True)
    panel.combine(f('growth_state', 'breadth'), [f('pmi_mfg', 'latest'), f('industrial_va_yoy', 'release_innovation'),
                  f('retail_sales_yoy', 'release_innovation')], 'growth',
                  'Fraction of expansion signals: PMI above 50, positive industrial and retail innovations',
                  'ratio', lambda pmi, industrial, retail: ((pmi > 50) + (industrial > 0) + (retail > 0)) / 3)
    panel.combine(f('prices_state', 'release_momentum'), [f(s, 'release_change') for s in ('cpi_yoy', 'ppi_yoy')],
                  'prices', 'Equal-weight mean of CPI and PPI year-over-year inflation changes',
                  'percentage points', lambda cpi, ppi: (cpi + ppi) / 2)
    panel.combine(f('credit_state', 'trend_x_funding_pressure'), [f('m2_yoy', 'release_trend3'), f('dr007', 'pressure_rank252')],
                  'credit', 'M2 growth trend multiplied by centered historical DR007 pressure percentile',
                  'percentage points', lambda trend, pressure: trend * (pressure - 0.5))
    panel.combine(f('external_state', 'joint_fx_pressure'), [f('usdcny_fixing', 'change_20obs'), f('fx_reserves', 'release_yoy_pct')],
                  'external', 'Indicator of RMB depreciation over 20 quotes together with falling reserves year over year',
                  'binary', lambda fx, reserves: fx > 0 and reserves < 0)
    panel.combine(f('external_state', 'export_minus_import'), [f(s, 'latest') for s in TRADE], 'external',
                  'CNY exports less imports year-to-date growth, same cumulative period',
                  'percentage points', lambda exports, imports: exports - imports, same_period=True)


def summarize_sources(panel, formal_series):
    audit = {}
    for sid in formal_series:
        spec = panel.specs[sid]
        releases = release_series(panel.facts, spec)
        lineage = panel.lineage[sid]
        held = lineage.loc[lineage.held_legal_release]
        editions = panel.facts.loc[
            panel.facts.series_id.eq(spec.get('source_series_id', sid))
            & panel.facts.period_end.between(spec['required_start'], spec['required_end'])
        ]
        if 'filter_scope_id' in spec:
            editions = editions.loc[editions.statistical_scope_id.eq(spec['filter_scope_id'])]
        observed = held.period_end.nunique()
        unit_counts = editions.groupby('unit', dropna=False).size().to_dict()
        if set(unit_counts) != {spec['unit']}:
            raise ValueError(f'Unexpected admitted units for {sid}: {unit_counts}')
        revision_updates = held.period_end.eq(held.period_end.shift()) & held.source_record_id.ne(held.source_record_id.shift())
        audit[sid] = dict(
            frequency=spec['frequency'], unit=spec['unit'],
            admitted_source_rows=len(editions), first_documented_periods=len(releases),
            changed_values_across_editions=int((editions.groupby('period_end').value.nunique() > 1).sum()),
            periods_used_weekly=observed, held_or_current_weekly_rows=len(held),
            weekly_rows_within_same_period=int(held.period_end.eq(held.period_end.shift()).sum()),
            same_period_source_updates=int(revision_updates.sum()),
            weekly_lineage_by_quality={str(key): int(val) for key, val in held.quality.value_counts().items()},
            weekly_lineage_by_status={str(key): int(val) for key, val in lineage.status.value_counts().items()},
            effective_availability_basis={str(key): int(val) for key, val in editions.release_time_basis.value_counts().items()},
        )
        if sid in TRADE:
            crossed_years = []
            for r, change in zip(lineage.itertuples(index=True), panel.base[column(sid, 'change')], strict=True):
                if np.isfinite(change):
                    previous = panel.records[r.previous_record_id]
                    if previous.period.year != r.period_end.year:
                        crossed_years.append(r.Index.date().isoformat())
            audit[sid]['legacy_ytd_cross_year_change_anchors'] = crossed_years
    return audit


def summarize_columns(frame):
    return dict(
        rows=len(frame), columns=len(frame.columns),
        all_missing=frame.columns[frame.nunique().eq(0)].tolist(),
        constant_observed=frame.columns[frame.nunique().eq(1)].tolist(),
        coverage={key: float(count / len(frame)) for key, count in frame.count().items()},
    )


def summarize_quality(panel, features, membership, original_z, catalog):
    train = membership.loc[membership.role.eq('train')]
    initial_dates = pd.Index(train.loc[train.fold_id.eq('initial'), 'asof_date'].unique())
    initial = features.loc[initial_dates]
    old_initial = panel.base.loc[initial_dates, original_z]
    quantiles = initial.quantile([0.25, 0.75])
    iqr = quantiles.loc[0.75] - quantiles.loc[0.25]
    numeric = iqr.index[iqr.gt(0)]
    extremes = ((initial[numeric] < quantiles.loc[0.25, numeric] - 6 * iqr[numeric])
                | (initial[numeric] > quantiles.loc[0.75, numeric] + 6 * iqr[numeric]))
    correlations = initial.corr(min_periods=40).abs()
    near_duplicates = np.argwhere(np.triu(correlations.to_numpy() >= 0.995, k=1))
    all_train_columns = {}
    for (fold, market), rows in train.groupby(['fold_id', 'market_id'], sort=True):
        unique = features.loc[rows.asof_date.unique()].nunique()
        all_train_columns[f'{fold}/{market}'] = dict(rows=len(rows), variable=int(unique.gt(1).sum()),
                                                     all_missing=int(unique.eq(0).sum()), constant=int(unique.eq(1).sum()))
    return dict(
        version=FEATURE_VERSION, anchors=dict(count=len(features), first=str(features.index.min().date()),
                                              last=str(features.index.max().date())),
        quality_view=QUALITY_VIEW, initial_train=summarize_columns(initial),
        legacy_initial_train=summarize_columns(old_initial), coverage=summarize_columns(features),
        by_fold_market_train=all_train_columns,
        by_group={group: sum(row['group'] == group for row in catalog)
                  for group in ('growth', 'prices', 'credit', 'rates', 'external')},
        initial_train_population_variance={col: float(var) if np.isfinite(var) else None
                                           for col, var in initial.var(ddof=0).items()},
        initial_train_extended_tukey_outliers={col: int(count) for col, count in extremes.sum().items() if count},
        initial_train_high_correlations=[dict(left=initial.columns[i], right=initial.columns[j],
                                              absolute_pearson=float(correlations.iloc[i, j]))
                                         for i, j in near_duplicates],
        interpretation=dict(
            inputs='Descriptive checks only; original units and missing values preserved. No labels or performance used.',
            later_editions='Revision evidence is retained under dated PIT rules in legacy levels. New release descriptors freeze the first admissible edition of each period and require strictly earlier parents. Historical reconstruction can include dated contemporary reprints.',
            expectation='No archived pre-release market consensus was present in the registered source data. Innovation is a forecast against prior observed releases.',
            daily='Existing observation-window features are reused. Reconstructed quotes inherit the source vintage and date limitations; correction archives are incomplete.',
            credit='TSF and loan regimes remain separate. TSF–M2 requires identical economic periods; new-loan seasonal change stays in the same definition.',
            legacy='The sealed Z is preserved. Its trade YTD changes can cross calendar years and its source-age resets on same-period table reissues; Z* applies the economic year guard and first-documentation clock. Historical M+Z models using these columns should continue to be labeled legacy Z.',
        ),
    )


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def build_z_star(data_root: Path, macro_source: Path | None = None, output_dir: Path | None = None):
    """Create the macro-only release files. The release command seals them separately."""
    data_root = Path(data_root)
    facts_path, repairs_path, features_path, lineage_path, specs_path, sets_path, membership_path = source_paths(data_root, macro_source)
    facts = pd.concat([pd.read_parquet(facts_path), pd.read_parquet(repairs_path)], ignore_index=True)
    if not facts.source_record_id.is_unique:
        raise ValueError('Macro facts and repair record IDs must be unique')
    facts = prepare(facts, QUALITY_VIEW)
    if not np.isfinite(facts.value).all():
        raise ValueError('Non-finite admitted macro facts')
    specs = {item['series_id']: item for item in json.loads(specs_path.read_text(encoding='utf-8'))}
    sets = json.loads(sets_path.read_text(encoding='utf-8'))
    original_z = [c for c in sets['sets']['M+Z'] if c not in sets['sets']['M']]
    panel = MacroPanel(pd.read_parquet(features_path), pd.read_parquet(lineage_path), facts, specs)
    add_macro_features(panel)
    features = pd.DataFrame({key: [obs.value for obs in values] for key, values in panel.obs.items()}, index=panel.base.index)
    lineage = pd.DataFrame(panel.derived_lineage)
    retained = [row['feature'] for row in panel.catalog if row['kind'] == 'retained']
    if not set(retained).issubset(original_z) or not features[retained].equals(panel.base[retained]):
        raise ValueError('Retained Z* columns differ from the original formal Z')
    catalog = dict(version=FEATURE_VERSION, quality_view=QUALITY_VIEW, features=panel.catalog,
                   shared_bulletin_clocks=SHARED_BULLETIN_CLOCKS,
                   original_z=dict(retained=retained, removed=[col for col in original_z if col not in retained],
                                   added=[col for col in features if col not in retained]))
    membership = pd.read_parquet(membership_path, columns=['market_id', 'fold_id', 'asof_date', 'role'])
    quality = summarize_quality(panel, features, membership, original_z, panel.catalog)
    quality['series'] = summarize_sources(panel, sets['formal_macro_series'])
    quality['original_z'] = {key: len(names) for key, names in catalog['original_z'].items()}
    if output_dir is None:
        output_dir = data_root / 'release/z_star'
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)
    features.reset_index().to_parquet(output_dir / 'features.parquet', index=False)
    lineage.to_parquet(output_dir / 'lineage.parquet', index=False)
    write_json(output_dir / 'feature_catalog.json', catalog)
    write_json(output_dir / 'quality_report.json', quality)
    return quality
