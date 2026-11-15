"""Continuous market extensions; frozen labels/features are never overwritten."""
import numpy as np
from .common import *
from .market import rel

OUT=ROOT/'data/features/market/v4'


def cross_section():
    c=db();rows=[]
    c.execute('CREATE TEMP TABLE ids AS SELECT DISTINCT instrument_id,security_type FROM read_parquet(?)',[str(MARKET/'stock_master_history.parquet')])
    for year in range(2014,2027):
        pred=f"trade_date BETWEEN '{year}0101' AND '{min(str(year)+'1231',END)}'"
        q=f"""WITH d AS(SELECT * FROM {rel('stock_daily_observations')} WHERE {pred}),
          s AS(SELECT * FROM {rel('stock_trading_status')} WHERE {pred})
          SELECT s.trade_date,count(*) eligible_listed_securities,count(d.close) observed_securities,
           count(*) FILTER(WHERE d.close IS NULL) unquoted_securities,
           count(*) FILTER(WHERE d.close/d.pre_close-1<0) declining_securities,
           count(*) FILTER(WHERE d.close/d.pre_close-1>0) advancing_securities,
           sum(d.amount_cny ORDER BY s.instrument_id) amount_cny,sum(d.volume_shares) volume_shares,
           avg(abs(d.close/d.pre_close-1)/nullif(d.amount_cny,0)*1e8 ORDER BY s.instrument_id) amihud_per_100m_cny,
           stddev_samp(d.close/d.pre_close-1 ORDER BY s.instrument_id) reference_return_dispersion,
           max(d.retrieved_at) latest_parent_retrieved_at,
           count(*) FILTER(WHERE s.status='SUSPENDED_OFFICIAL_EVIDENCE') ex_post_certified_suspensions
          FROM s JOIN ids USING(instrument_id) LEFT JOIN d USING(instrument_id,trade_date)
          WHERE ids.security_type='A_SHARE' GROUP BY s.trade_date ORDER BY s.trade_date"""
        d=c.execute(q).df();rows.append(d)
    daily=pd.concat(rows).sort_values('trade_date').reset_index(drop=True);daily['observation_date']=pd.to_datetime(daily.trade_date)
    daily['declining_fraction_traded']=daily.declining_securities/daily.observed_securities
    daily['unquoted_fraction_listed']=daily.unquoted_securities/daily.eligible_listed_securities
    daily['reconstructed_quote_at']=daily.observation_date.dt.tz_localize('Asia/Shanghai')+pd.Timedelta(hours=18)
    daily['research_available_at']=pd.to_datetime(daily.latest_parent_retrieved_at,utc=True).dt.tz_convert('Asia/Shanghai')
    daily['quality_status']='QUALIFIED_RECONSTRUCTED_ALL_A_PROXY'
    daily['quality_reason']='Historical listed universe, including delisted; CDR excluded. Quote-based breadth uses exchange reference returns and traded denominator. Unquoted fraction is not assumed suspension. Ex-post suspension certificates are audit-only. No precise index-member claim; historical identity/correction completeness remains qualified.'
    for col in ['declining_fraction_traded','amihud_per_100m_cny','amount_cny']:
        for n in [5,20,60]:daily[col+f'_ma{n}']=daily[col].rolling(n,min_periods=n).mean()
    frame(OUT/'all_a_daily.parquet',daily);c.close();return daily


def correlation_weekly(market):
    c=db();calendar=c.execute('SELECT cal_date FROM '+rel('trade_calendar')+" WHERE exchange='SSE' AND is_open=1 AND cal_date BETWEEN '20140101' AND '20260922' ORDER BY cal_date").df().cal_date.tolist()
    position={d:i for i,d in enumerate(calendar)};rows=[];parents=[]
    for year in sorted(market.asof_date.dt.year.unique()):
        points=market[market.asof_date.dt.year.eq(year)];first=min(position[x.strftime('%Y%m%d')] for x in points.asof_date)
        begin=calendar[max(0,first-60)];end=points.asof_date.max().strftime('%Y%m%d')
        # Year-bounded projection, not a full raw-stock load. Only daily returns
        # on consecutive observed exchange days enter the 60-day balanced panel.
        d=c.execute(f"SELECT instrument_id,trade_date,close/pre_close-1 r,source_record_id FROM {rel('stock_daily_observations')} WHERE trade_date BETWEEN ? AND ? AND ts_code NOT LIKE '689%'",[begin,end]).df()
        d['day_position']=d.trade_date.map(position);d=d.sort_values(['instrument_id','trade_date'])
        d.loc[d.groupby('instrument_id').day_position.diff().ne(1),'r']=np.nan
        panel=d.pivot(index='trade_date',columns='instrument_id',values='r').reindex([x for x in calendar if begin<=x<=end])
        for p in points.itertuples(index=False):
            date=p.asof_date.strftime('%Y%m%d');window=panel.loc[:date].tail(60).dropna(axis=1);window=window.loc[:,window.std(ddof=1)>0]
            n=len(window.columns);value=np.nan
            if len(window)==60 and n>=2:
                z=((window-window.mean())/window.std(ddof=1)).to_numpy();value=((z.sum(axis=1)**2).sum()/59-n)/(n*(n-1))
            rows.append({'sample_id':p.sample_id,'asof_time':p.asof_time,'average_pairwise_correlation_60d':value,'eligible_balanced_securities':n,
                         'window_start':pd.to_datetime(window.index.min()),'window_end':p.asof_date,
                         'quality_status':'QUALIFIED_BALANCED_TRADED_PANEL_PROXY',
                         'quality_reason':'All-A equal-weight Pearson pair correlation for securities observed on all 60 days, with consecutive-day quote returns. Excludes suspension gaps, zero-variance series and IPO incomplete windows; this is a documented conditional panel, not exact index membership.'})
            ids=set(window.columns);subset=d[d.instrument_id.isin(ids)&d.trade_date.isin(window.index)]
            parents.append({'sample_id':p.sample_id,'parent_rows':len(subset),'parent_record_digest':hashlib.sha256('\n'.join(sorted(subset.source_record_id)).encode()).hexdigest(),
                            'parent_query_start':str(window.index.min()),'parent_query_end':date,'selected_instrument_ids':json.dumps(sorted(ids))})
    c.close();frame(OUT/'all_a_correlation_weekly.parquet',pd.DataFrame(rows));frame(OUT/'correlation_lineage.parquet',pd.DataFrame(parents));return pd.DataFrame(rows)


def index_dimensions():
    c=db();d=c.execute('SELECT * FROM '+rel('index_daily')+' ORDER BY ts_code,trade_date').df();c.close()
    frame(OUT/'index_dimensions_daily.parquet',calculate_index_dimensions(d))


def calculate_index_dimensions(d):
    # Audit conflicts are quality exclusions, not values silently substituted.
    conflicts=pd.read_parquet(ROOT/'data/metadata/index_price_conflicts.parquet')
    conflict_keys=set(conflicts.loc[conflicts.price_resolution.eq('MATERIAL_DIFFERENCE_REQUIRES_REVIEW'),['ts_code','trade_date']].itertuples(index=False,name=None))
    out=[]
    for code,g in d.groupby('ts_code'):
        g=g.sort_values('trade_date').copy();r=g.close/g.pre_close-1
        for n in [5,20,60]:
            g[f'return_{n}d']=g.close/g.close.shift(n)-1
            g[f'volatility_{n}d']=r.rolling(n,min_periods=n).std(ddof=1)*np.sqrt(252)
            g[f'max_drawdown_{n}d']=g.close.rolling(n,min_periods=n).apply(lambda x:np.min(x/np.maximum.accumulate(x)-1),raw=True)
        g['downside_rms_20d']=np.sqrt(r.clip(upper=0).pow(2).rolling(20).mean()*252)
        g['amount_ma20_cny']=g.amount_cny.rolling(20).mean();g['prelaunch_backcast']=(code=='000852.SH')&g.trade_date.lt('20141017')
        conflict=pd.Series([(code,x) in conflict_keys for x in g.trade_date],index=g.index)
        g['source_price_conflict']=conflict
        # A return at the following date can use the conflicted prior close;
        # exclude the full price dependency window, not only the event day.
        for n in [5,20,60]:
            eligible=~conflict.rolling(n+1,min_periods=1).max().astype(bool)&~g.prelaunch_backcast
            g[f'price_window_{n}d_eligible']=eligible
            for field in [f'return_{n}d',f'volatility_{n}d',f'max_drawdown_{n}d']:
                g[field+'__candidate']=g[field]
                g.loc[~eligible,field]=np.nan
        g['downside_rms_20d__candidate']=g.downside_rms_20d
        g.loc[~g.price_window_20d_eligible,'downside_rms_20d']=np.nan
        g['feature_quality']=np.where(~g.price_window_60d_eligible,'BLOCKED_PRICE_CONFLICT_WINDOW_OR_PRELAUNCH','RECONSTRUCTED_QUOTE_CONTINUOUS_EXTENSION');out.append(g)
    return pd.concat(out,ignore_index=True)


def assemble_weekly():
    market=pd.read_parquet(ROOT/'data/research_v2/market_features_weekly.parquet');d=pd.read_parquet(OUT/'all_a_daily.parquet');corr=pd.read_parquet(OUT/'all_a_correlation_weekly.parquet')
    d['reconstructed_quote_at']=d.reconstructed_quote_at.astype('datetime64[ns, Asia/Shanghai]')
    cols=['observation_date','reconstructed_quote_at','declining_fraction_traded','unquoted_fraction_listed','amihud_per_100m_cny','reference_return_dispersion','amount_cny']+[c for c in d if '_ma' in c]
    weekly=pd.merge_asof(market[['sample_id','asof_time']].sort_values('asof_time'),d[cols].sort_values('reconstructed_quote_at'),left_on='asof_time',right_on='reconstructed_quote_at',direction='backward')
    weekly=weekly.merge(corr.drop(columns='asof_time'),on='sample_id',validate='one_to_one');frame(OUT/'market_extensions_weekly.parquet',weekly)
    write(OUT/'authority.json',{'version':VERSION,'frozen_formal_market_features':'data/research_v2/market_features_weekly.parquet',
       'extensions':'data/features/market/v4/market_extensions_weekly.parquet','extension_quality':'Conditional reconstructed proxies, not fully certified index structure or impact measures.',
       'strict_vintage_available':False,'input_authority':['stock_daily_observations','stock_trading_status','stock_master_history'],
       'no_label_or_threshold_changes':True,'correlation_formula':'(sum_t(sum_i z_ti)^2/(T-1)-N)/(N*(N-1)); sample-standardized columns; T=60'})
    print('Market extensions',len(weekly),'weekly samples',flush=True)


def build():
    market=pd.read_parquet(ROOT/'data/research_v2/market_features_weekly.parquet');cross_section();correlation_weekly(market);index_dimensions();assemble_weekly()


if __name__=='__main__':build()
