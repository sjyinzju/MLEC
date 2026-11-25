"""The ONLY past/future measurement implementation (protocol section 3)."""
import numpy as np
import pandas as pd
from .common import *

def price_measure(prices):
    p=np.asarray(prices,dtype=float);h=len(p)-1
    fields=['return','volatility','drawdown','downside_semivol','worst_daily_return','worst_cumulative_return','up_day_fraction','path_slope','vol_concentration']
    if h<1 or not np.isfinite(p).all() or (p<=0).any():return dict.fromkeys(fields,np.nan)
    r=np.diff(np.log(p));s=r*r
    return dict(zip(fields,[p[-1]/p[0]-1,np.sqrt(252/h*s.sum()),np.max(1-p/np.maximum.accumulate(p)),
        np.sqrt(252/h*np.minimum(r,0).dot(np.minimum(r,0))),np.expm1(r.min()),np.min(p[1:]/p[0]-1),
        (r>0).mean(),np.polyfit(np.arange(h+1),np.log(p/p[0]),1)[0],s.max()/s.sum() if s.sum()>0 else 0]))

def average_correlation(panel):
    x=np.asarray(panel,dtype=float)
    x=x[:,np.isfinite(x).all(axis=0)]
    x=x[:,x.std(axis=0,ddof=1)>0] if len(x)>1 else x[:,:0]
    h,n=x.shape
    if h<2 or n<2:return np.nan,n
    z=(x-x.mean(axis=0))/x.std(axis=0,ddof=1)
    return float(((z.sum(axis=1)**2).sum()/(h-1)-n)/(n*(n-1))),n

def window_measure(prices,daily,panel,membership):
    """prices H+1; daily/panel/membership H rows, identical calendar dates."""
    result=price_measure(prices);h=len(prices)-1
    if h<1 or len(daily)!=h:raise ValueError('H+1 anchor price contract')
    for name in ['amihud','turnover','breadth','return_dispersion','amount_cny','quote_coverage','return_coverage','float_coverage','suspension_fraction','unexplained_unquoted_fraction']:
        values=daily[name].to_numpy()
        result[name]=values.mean() if np.isfinite(values).all() else np.nan
    eligible=membership.all(axis=0)
    corr,n=average_correlation(panel[:,eligible]);result['correlation']=corr
    result['correlation_stocks']=n
    result['correlation_union_stocks']=int(membership.any(axis=0).sum())
    result['correlation_coverage']=n/max(1,result['correlation_union_stocks'])
    result['min_members']=int(daily.members.min());result['min_return_stocks']=int(daily.return_stocks.min())
    result['measurement_valid']=bool(np.isfinite([result[k] for k in CORE]).all())
    result['missing_reason']=';'.join('MISSING_'+k.upper() for k in CORE if not np.isfinite(result[k]))
    return result

def validity_masks(dates, master, imap):
    shape=(len(dates),len(imap))
    active=np.zeros(shape,bool)
    ordinary=np.zeros(shape,bool)
    for r in master.itertuples():
        valid=(dates>=r.valid_from)&(dates<r.valid_to)
        active[:,imap[r.instrument_id]]|=valid
        if r.security_type=='A_SHARE':ordinary[:,imap[r.instrument_id]]|=valid
    return active,ordinary

def market_membership(market,dates,weights,imap,aliasmap,active,ordinary):
    snapshot_age=np.full(len(dates),np.nan)
    if market=='000985.SH':
        return ordinary,snapshot_age
    membership=np.zeros(active.shape,bool)
    w=weights[weights.index_code.eq(market)]
    books={d:[imap[aliasmap[x]] for x in g.con_code if x in aliasmap and aliasmap[x] in imap]
        for d,g in w.groupby('snapshot_date')}
    snaps=sorted(books)
    for j,d in enumerate(dates):
        k=np.searchsorted(snaps,d,side='right')-1
        if k>=0:
            age=(d-snaps[k]).days;snapshot_age[j]=age
            if age<=45:membership[j,books[snaps[k]]]=True
    return membership & active,snapshot_age

def measure_record(dates,price,daily,returns,membership,key,a,b,direction):
    length=b-a
    meta=dict(key,window_length=length,window_start=dates[a+1] if a>=0 and a+1<len(dates) else pd.NaT,
        window_end=dates[b] if b<len(dates) else pd.NaT,price_count=length+1)
    if a<0 or b>=len(dates):
        outcome={**dict.fromkeys(CORE,np.nan), 'measurement_valid':False,
            'missing_reason':'FUTURE_WINDOW_NOT_MATURE' if direction=='future' else 'INSUFFICIENT_HISTORY'}
    else:
        outcome=window_measure(price[a:b+1],daily.iloc[a+1:b+1],returns[a+1:b+1],membership[a+1:b+1])
    rec=dict(meta,**outcome)
    if direction=='future':
        rec.update(label_start=meta['window_start'],label_end=meta['window_end'],
            label_available_at=clock(dates[b]) if b<len(dates) else pd.NaT)
    return rec

def build_measures(*,max_asof=None,stock_transform=None,price_transform=None,save=True):
    dates=pd.DatetimeIndex(read('calendar').date);master=read('security_history');weights=read('membership_snapshots')
    instruments=sorted(master.instrument_id.unique());imap={x:i for i,x in enumerate(instruments)}
    dmap={x:i for i,x in enumerate(dates)};shape=(len(dates),len(instruments))
    active,ordinary=validity_masks(dates,master,imap)
    arrays={col:np.full(shape,np.nan) for col in ['r','volume_shares','amount_cny','float_shares']}
    quote=np.zeros(shape,bool)
    for p in sorted((OUT/'cache/stocks').glob('*.parquet')):
        stocks=pd.read_parquet(p,columns=['date','instrument_id','close']+list(arrays))
        if stock_transform is not None:stocks=stock_transform(stocks.copy())
        di=stocks.date.map(dmap).to_numpy();si=stocks.instrument_id.map(imap).to_numpy()
        for col,a in arrays.items():a[di,si]=stocks[col]
        quote[di,si]=stocks.close.gt(0)
    del stocks
    # Confirmed suspension evidence remains distinct from missing quote/return.
    susp=np.zeros(shape,bool)
    from .sources import load_suspensions
    f=load_suspensions(master)
    alias=master[['ts_code','instrument_id']].drop_duplicates()
    if len(f):
        f=f[f.date.isin(dates)&f.instrument_id.isin(instruments)]
        susp[f.date.map(dmap),f.instrument_id.map(imap)]=True
    indices=read('index_prices');rows=[];past=[];daily_results=[]
    if price_transform is not None:indices=price_transform(indices.copy())
    # A week is complete only when its Friday has elapsed by the observed data end.
    weekly=pd.Series(dates,index=dates).groupby(dates.to_period('W-FRI')).max()
    points=[d for period,d in weekly.items() if period.end_time.normalize()<=dates.max() and d.year>=2015]
    if max_asof is not None:points=[d for d in points if d<=pd.Timestamp(max_asof)]
    aliasmap=alias.set_index('ts_code').instrument_id.to_dict()
    for market in MARKETS:
        membership,snapshot_age=market_membership(market,dates,weights,imap,aliasmap,active,ordinary)
        members=membership.sum(axis=1);valid=membership&np.isfinite(arrays['r'])
        liquid=valid & (arrays['amount_cny']>0)
        cap=membership & np.isfinite(arrays['volume_shares']) & (arrays['float_shares']>0)
        def masked_sum(a,mask):return np.where(mask,a,0).sum(axis=1)
        with np.errstate(all='ignore'):
            impact=np.where(liquid,np.abs(arrays['r'])/arrays['amount_cny'],np.nan)
            amihud=np.array([np.nanmedian(x) if np.isfinite(x).any() else np.nan for x in impact])
            turnover=masked_sum(arrays['volume_shares'],cap)/masked_sum(arrays['float_shares'],cap)
            breadth=((arrays['r']<0)&valid).sum(axis=1)/valid.sum(axis=1)
            rd=np.array([np.std(r[v]) if v.any() else np.nan for r,v in zip(arrays['r'],valid)])
        daily=pd.DataFrame(dict(date=dates,members=members,return_stocks=valid.sum(axis=1),amihud=amihud,turnover=turnover,breadth=breadth,
            return_dispersion=rd,amount_cny=masked_sum(arrays['amount_cny'],liquid),
            quote_coverage=np.divide((quote&membership).sum(axis=1),members,out=np.full(len(dates),np.nan),where=members>0),
            return_coverage=np.divide(valid.sum(axis=1),members,out=np.full(len(dates),np.nan),where=members>0),
            float_coverage=np.divide(cap.sum(axis=1),members,out=np.full(len(dates),np.nan),where=members>0),
            suspension_fraction=np.divide((susp&membership).sum(axis=1),members,out=np.full(len(dates),np.nan),where=members>0),
            unexplained_unquoted_fraction=np.divide((membership&~quote&~susp).sum(axis=1),members,out=np.full(len(dates),np.nan),where=members>0),snapshot_age_days=snapshot_age))
        daily['market_id']=market;daily_results.append(daily)
        price=indices[indices.ts_code.eq(market)].set_index('date').close.reindex(dates).to_numpy()
        for d in points:
            i=dmap[d];key=dict(market_id=market,asof_date=d,horizon=20,asof_time=clock(d))
            for length,direction in [(20,'future'),(5,'past'),(20,'past'),(60,'past')]:
                a,b=(i,i+length) if direction=='future' else (i-length,i)
                rec=measure_record(dates,price,daily,arrays['r'],membership,key,a,b,direction)
                if direction=='future':
                    rows.append(rec)
                else:past.append(rec)
        print('measured',market,len(points),flush=True)
    products={'market_daily':pd.concat(daily_results,ignore_index=True),'future_window_outcomes':pd.DataFrame(rows),'past_window_outcomes':pd.DataFrame(past)}
    if save:
        for name,value in products.items():frame(name,value)
    return products
