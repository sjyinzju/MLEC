"""Targeted stock dependency certification and explicitly descriptive observed-stock proxies."""
from __future__ import annotations
import gc
import numpy as np
import pandas as pd
from common import *

A_SCOPE="((ts_code LIKE '6%.SH' AND substr(ts_code,1,3) IN ('600','601','603','605','688','689')) OR (ts_code LIKE '%.SZ' AND substr(ts_code,1,3) IN ('000','001','002','003','300','301')))"

def run_extensions():
    log('extensions_start',budget=budget());c=db()
    master=query(c,f"SELECT ts_code,list_status,list_date,delist_date,exchange FROM ({latest('stock_basic')}) WHERE {A_SCOPE}",'stock_master_history')
    mapping=query(c,f"SELECT * EXCLUDE(_row_hash,_batch_id,_ingested_at,_available_at,_event_date,_period_date,_announcement_date,_actual_announcement_date,_revision,_knowledge_quality,_event_available_at,_transform_version) FROM ({latest('bse_mapping')})",'code_mapping_scope')
    saveframe(AUDIT/'stock_master_scope.parquet',master);saveframe(AUDIT/'available_code_mapping.parquet',mapping)
    c.register('master_input',master);c.execute('CREATE TEMP TABLE master AS SELECT * FROM master_input')
    obs=pd.read_parquet(DATA/'market_observations_daily.parquet');dates=obs.date;date_to_pos={d.strftime('%Y%m%d'):i for i,d in enumerate(dates)}
    codes=sorted(master.ts_code.unique());code_to_pos={s:i for i,s in enumerate(codes)}
    shape=(len(dates),len(codes));tmp_paths=[AUDIT/'temp/stock_returns.float64',AUDIT/'temp/stock_illiquidity.float64']
    jsonwrite(AUDIT/'temporary_files.json',{'owner':'research_v2 extensions','paths':[str(p) for p in tmp_paths],'shape':shape,'estimated_bytes':2*8*shape[0]*shape[1]})
    budget()
    ret=np.memmap(tmp_paths[0],dtype='float64',mode='w+',shape=shape);ret[:]=np.nan
    ami=np.memmap(tmp_paths[1],dtype='float64',mode='w+',shape=shape);ami[:]=np.nan
    cert=[];exclusions=[];codeissues=[];reason_counts={};source_rows=0
    try:
        for year in range(2015,2027):
            year_dates=dates[dates.dt.year.eq(year)]
            if year_dates.empty:continue
            first=dates.index[dates.eq(year_dates.min())][0]
            lower=dates.iloc[max(first-1,0)].strftime('%Y%m%d');upper=year_dates.max().strftime('%Y%m%d')
            pred=f"trade_date BETWEEN '{lower}' AND '{upper}' AND {A_SCOPE}"
            dsql=latest('daily',pred);fsql=latest('adj_factor',pred);ssql=latest('suspend_d',pred)
            c.execute(f'CREATE OR REPLACE TEMP TABLE d AS SELECT ts_code,trade_date,close,vol,amount FROM ({dsql})')
            c.execute(f'CREATE OR REPLACE TEMP TABLE f AS SELECT ts_code,trade_date,adj_factor FROM ({fsql})')
            c.execute(f"CREATE OR REPLACE TEMP TABLE s AS SELECT ts_code,trade_date,bool_or(suspend_type='S') suspended FROM ({ssql}) GROUP BY 1,2")
            frame=query(c,"SELECT d.*,f.adj_factor,m.list_date,m.delist_date,coalesce(s.suspended,false) suspended FROM d LEFT JOIN f USING(ts_code,trade_date) LEFT JOIN master m USING(ts_code) LEFT JOIN s USING(ts_code,trade_date) ORDER BY ts_code,trade_date",f'stock_dependency_{year}')
            source_rows+=frame.trade_date.str.startswith(str(year)).sum()
            frame['position']=frame.trade_date.map(date_to_pos);frame['code_position']=frame.ts_code.map(code_to_pos)
            g=frame.groupby('ts_code',sort=False)
            for col in ['close','adj_factor','position','suspended','amount','vol','trade_date']:frame['previous_'+col]=g[col].shift(1)
            unknown_master=frame.code_position.isna()
            outside=(frame.trade_date<frame.list_date)|((frame.delist_date.notna())&(frame.trade_date>frame.delist_date))|(frame.previous_trade_date<frame.list_date)
            nonadj=frame.position.sub(frame.previous_position).ne(1)|frame.position.isna()
            suspended=frame.suspended|frame.previous_suspended.eq(True)
            badprice=frame.close.le(0)|frame.previous_close.le(0)|frame.close.isna()|frame.previous_close.isna()
            badfactor=frame.adj_factor.le(0)|frame.previous_adj_factor.le(0)|frame.adj_factor.isna()|frame.previous_adj_factor.isna()
            badamount=frame.amount.le(0)|frame.vol.le(0)|frame.previous_amount.le(0)|frame.previous_vol.le(0)|frame.amount.isna()|frame.previous_amount.isna()
            frame['reason']=np.select([unknown_master,outside,nonadj,suspended,badprice,badfactor,badamount],['absent_master','outside_reconstructed_listing_span','nonadjacent_or_first_price','suspension_endpoint','invalid_price','invalid_adjacent_factor','zero_or_invalid_turnover'],default='')
            actual=frame.trade_date.str.startswith(str(year))
            good=actual&frame.reason.eq('')
            rr=(frame.close/frame.previous_close)*(frame.adj_factor/frame.previous_adj_factor)-1
            assert np.isfinite(rr[good]).all()
            ii=frame.loc[good,'position'].to_numpy(dtype=int);jj=frame.loc[good,'code_position'].to_numpy(dtype=int)
            ret[ii,jj]=rr[good].to_numpy();ami[ii,jj]=np.abs(rr[good].to_numpy())/(1000*frame.loc[good,'amount'].to_numpy())
            panel=frame.loc[good,['ts_code','trade_date']].copy()
            panel['adjusted_return']=rr[good].to_numpy()
            panel['amihud_daily']=np.abs(rr[good].to_numpy())/(1000*frame.loc[good,'amount'].to_numpy())
            saveframe(DATA/f'stock_proxy_inputs/{year}.parquet',panel)
            bad=frame.loc[actual&frame.reason.ne(''),['ts_code','trade_date','reason']]
            exclusions.append(bad)
            for reason,n in bad.reason.value_counts().items():reason_counts[reason]=reason_counts.get(reason,0)+int(n)
            if unknown_master.any() or outside.any():
                codeissues.append(frame.loc[actual&(unknown_master|outside),['ts_code','trade_date','list_date','delist_date','reason']])
            cal_y=pd.DataFrame({'trade_date':year_dates.dt.strftime('%Y%m%d')});c.register('calendar_input',cal_y)
            # Full expected-date diagnostic within reconstructed dated listing spans, not a certified historical universe.
            coverage=query(c,"""WITH expected AS (
                SELECT m.ts_code,cal.trade_date FROM master m JOIN calendar_input cal
                ON cal.trade_date>=m.list_date AND (m.delist_date IS NULL OR cal.trade_date<=m.delist_date))
                SELECT e.trade_date,count(*) reconstructed_listed_pool,
                count(*) FILTER(WHERE d.ts_code IS NOT NULL) observed_listed_pool,
                count(*) FILTER(WHERE d.ts_code IS NULL) missing_expected_prices,
                count(*) FILTER(WHERE d.ts_code IS NULL AND s.suspended) missing_with_same_day_suspension,
                count(*) FILTER(WHERE d.ts_code IS NULL AND NOT coalesce(s.suspended,false) AND f.ts_code IS NOT NULL) factor_only_unexplained,
                count(*) FILTER(WHERE d.ts_code IS NULL AND NOT coalesce(s.suspended,false) AND f.ts_code IS NULL) missing_price_and_factor_unexplained
                FROM expected e LEFT JOIN d USING(ts_code,trade_date) LEFT JOIN s USING(ts_code,trade_date)
                LEFT JOIN f USING(ts_code,trade_date) GROUP BY 1 ORDER BY 1""",f'listing_suspension_coverage_{year}')
            goodcounts=frame.loc[good].groupby('trade_date').size()
            coverage['valid_adjacent_return_stocks']=coverage.trade_date.map(goodcounts).fillna(0).astype(int)
            cert.append(coverage);ret.flush();ami.flush();budget();log('stock_year_complete',year=year,observations=int(actual.sum()),valid_returns=int(good.sum()))
        cert=pd.concat(cert,ignore_index=True);cert['date']=pd.to_datetime(cert.trade_date,format='%Y%m%d')
        cert['valid_return_coverage_reconstructed_pool']=cert.valid_adjacent_return_stocks/cert.reconstructed_listed_pool
        cert['unexplained_missing_prices']=cert.factor_only_unexplained+cert.missing_price_and_factor_unexplained
        cert['status']='PROXY: reconstructed master and unresolved code/suspension coverage'
        saveframe(AUDIT/'stock_certification_daily.parquet',cert)
        ex=pd.concat(exclusions,ignore_index=True);saveframe(AUDIT/'stock_exclusions.parquet',ex)
        issues=pd.concat(codeissues,ignore_index=True) if codeissues else pd.DataFrame(columns=['ts_code','trade_date','list_date','delist_date','reason'])
        saveframe(AUDIT/'stock_code_listing_issues.parquet',issues)
        rows=[]
        for i,day in enumerate(dates):
            x=np.asarray(ret[i]);valid=np.isfinite(x);n=int(valid.sum())
            row={'date':day,'down_fraction_proxy':float(np.mean(x[valid]<0)) if n else np.nan,'valid_return_stocks':n,
                 'mean_corr_60d_proxy':np.nan,'correlation_stocks':0,'correlation_observations_per_stock':0,
                 'amihud_20d_proxy':np.nan,'amihud_20d_median_proxy':np.nan,'amihud_20d_stocks':0}
            if i>=19:
                ar=np.asarray(ami[i-19:i+1]);ok=np.isfinite(ar).all(axis=0)
                means=ar[:,ok].mean(axis=0)
                if len(means):row.update(amihud_20d_proxy=float(means.mean()),amihud_20d_median_proxy=float(np.median(means)),amihud_20d_stocks=int(ok.sum()))
            if i>=59:
                window=np.asarray(ret[i-59:i+1]);ok=np.isfinite(window).all(axis=0)
                window=window[:,ok];std=window.std(axis=0,ddof=1) if window.shape[1] else np.array([])
                window=window[:,std>0];N=window.shape[1]
                row.update(correlation_stocks=N,correlation_observations_per_stock=60 if N else 0)
                if N>=2:
                    z=(window-window.mean(axis=0))/window.std(axis=0,ddof=1)
                    rho=(np.square(z.sum(axis=1)).sum()-N*59)/(N*(N-1)*59)
                    assert -1-1e-10<=rho<=1+1e-10
                    row['mean_corr_60d_proxy']=float(rho)
            rows.append(row)
        proxies=pd.DataFrame(rows).merge(cert[['date','reconstructed_listed_pool','observed_listed_pool','valid_return_coverage_reconstructed_pool','unexplained_missing_prices']],on='date',validate='one_to_one')
        proxies['breadth_change_5d_proxy']=proxies.down_fraction_proxy-proxies.down_fraction_proxy.shift(5)
        proxies['correlation_pool_coverage']=proxies.correlation_stocks/proxies.reconstructed_listed_pool
        proxies['amihud_pool_coverage']=proxies.amihud_20d_stocks/proxies.reconstructed_listed_pool
        proxies['proxy_status']='PROXY_observed_SH_SZ_sample_not_CSI300_or_certified_full_market'
        proxies['proxy_available_at']=stamp(proxies.date)
        proxies['proxy_availability_basis']='historical reconstructed prices/factors assumed available at 18:00; historical revisions and master/code completeness UNKNOWN'
        proxy_thresholds={}
        for field in ['down_fraction_proxy','mean_corr_60d_proxy','amihud_20d_proxy']:
            ref=proxies.loc[proxies.date.le('2019-12-31'),field].dropna()
            q=float(np.quantile(ref,.8,method='linear')) if len(ref) else None
            proxy_thresholds[field]={'q80':q,'reference_n':len(ref),'status':'PROXY','not_part_of_main_stress':True}
            proxies['high_'+field]=(proxies[field]>q).where(proxies[field].notna()).astype('Int8') if q is not None else pd.Series(pd.NA,index=proxies.index,dtype='Int8')
        jsonwrite(CONFIG/'proxy_thresholds.json',proxy_thresholds)
        saveframe(DATA/'stock_market_proxies_daily.parquet',proxies)
        evidence={'master_stocks':len(master),'listed_status_counts':master.list_status.value_counts().to_dict(),'delisted_stocks_retained':int(master.list_status.eq('D').sum()),'source_observations':int(source_rows),'excluded_observations_by_reason':reason_counts,'listing_or_code_issue_rows':len(issues),'expected_price_gaps':int(cert.missing_expected_prices.sum()),'gaps_with_same_day_suspension':int(cert.missing_with_same_day_suspension.sum()),'unexplained_price_gaps':int(cert.unexplained_missing_prices.sum()),'available_mapping_rows':len(mapping),'mapping_scope':'BSE only; no complete historical SH/SZ code-change ledger','universe_certification':'BLOCKED for exact CSI300/full historical market universe; dated master includes delisted but observed-revision and code-history gaps remain','suspension_interpretation':'S day records excluded on both return endpoints; R is resumption, not suspension. Missing S record does not certify normal trading; unresolved gaps reported','proxy_qualification':'conditional observed stock pairs; complete 20/60 same-date windows, no pairwise missing deletion or zero imputation','proxy_research_status':'PROXY, optional inputs disabled in default main whitelist'}
        jsonwrite(AUDIT/'stock_scope_certification.json',evidence)
        jsonwrite(AUDIT/'dimension_availability.json',[
            {'dimension':'趋势','status':'FORMAL','fields':'ret_5d/20d/60d','limitation':'price index, no dividends; no bull/bear assignment'},
            {'dimension':'波动','status':'FORMAL','fields':'vol_5d/20d/60d, downside_vol_20d','limitation':'daily close-based annualized proxy, not high-frequency RV'},
            {'dimension':'下行损失','status':'FORMAL','fields':'mdd_20d/60d,current_drawdown_20d/60d','limitation':'observed window price losses only'},
            {'dimension':'活跃度及流动性','status':'FORMAL_ACTIVITY_AND_PROXY_LIQUIDITY','fields':'amount, lagged turnover; amihud stock proxy','limitation':'activity is not liquidity crisis; observed stock proxy not exact full-market illiquidity'},
            {'dimension':'市场结构','status':'PROXY','fields':'down_fraction_proxy,breadth_change_5d_proxy,mean_corr_60d_proxy','limitation':evidence['universe_certification']}])
        log('extensions_complete',certification=evidence)
    finally:
        c.close();ret.flush();ami.flush()
        # Array views can retain the mapping on Windows after del; close owned mappings explicitly.
        ret._mmap.close();ami._mmap.close();del ret,ami;gc.collect()
        for path in tmp_paths:
            resolved=path.resolve();assert resolved.is_relative_to((AUDIT/'temp').resolve())
            if resolved.exists():resolved.unlink()
