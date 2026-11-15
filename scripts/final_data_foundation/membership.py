"""Historical membership queries with explicit effective/snapshot precision."""
import pandas as pd
from .common import MARKET, INDEX_CODES, END, db


def load_index_members(index_code, asof, *, mode='effective', max_snapshot_age_days=45):
    """Query preserved histories without current-member backfill.

    effective uses announced validity intervals; it does not certify that the
    historical announcement catalogue is exhaustive. monthly_snapshot explicitly
    assumes the observed snapshot was available at 18:00 on its observation day.
    Weights remain percentages at that snapshot, never exact daily weights.
    A date-only asof means midnight, so that day's closing snapshot is excluded.
    """
    if index_code not in INDEX_CODES or mode not in ['effective', 'monthly_snapshot']:
        raise ValueError('Unknown index or membership mode')
    if max_snapshot_age_days < 0:
        raise ValueError('Snapshot age must be nonnegative')
    t = pd.Timestamp(asof)
    t = t.tz_localize('Asia/Shanghai') if t.tzinfo is None else t.tz_convert('Asia/Shanghai')
    if t.tz_localize(None).normalize() > pd.Timestamp(END):
        raise ValueError('Query exceeds the registered research end date')
    c = db()
    try:
        if mode == 'effective':
            f = c.execute('SELECT * FROM read_parquet(?) WHERE index_code=?',
                          [str(MARKET/'index_constituents_history.parquet'), index_code]).df()
            f = f[(f.valid_from <= t.tz_localize(None)) & (f.valid_to > t.tz_localize(None))
                  & (f.research_available_at <= t)].copy()
            f['membership_precision'] = 'announced_effective_interval_catalogue_not_exhaustive'
        else:
            f = c.execute('SELECT * FROM read_parquet(?) WHERE index_code=?',
                          [str(MARKET/'index_weights_history/*.parquet'), index_code]).df()
            f['assumed_available_at'] = pd.to_datetime(f.trade_date).dt.tz_localize('Asia/Shanghai') + pd.Timedelta(hours=18)
            f = f[f.assumed_available_at <= t].copy()
            latest = f.trade_date.max() if len(f) else None
            f = f[f.trade_date.eq(latest)].copy()
            f['snapshot_age_days'] = (t.normalize() - f.assumed_available_at.dt.normalize()).dt.days
            f = f[f.snapshot_age_days <= max_snapshot_age_days].copy()
            f['membership_precision'] = 'monthly_snapshot_historical_reconstructed'
            f['weight_unit'] = 'percent_at_snapshot'
        assert not f.con_code.duplicated().any()
        return f.reset_index(drop=True)
    finally:
        c.close()
