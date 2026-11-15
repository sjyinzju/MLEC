"""Apply last independently verified amendments and regenerate dependent data."""
import socket
import time
from .common import *


def run():
    from . import identity_amendment,market,adjudication,stock_identity_views,factor_repairs,factor_actions,deep_market_checks,reconcile,market_quality,market_features,macro,research_inputs,catalogue,source_coverage
    stages=[('register_code_evidence',identity_amendment.register),('identity_intervals',market.identities),('security_date_grid',market.stock_gaps),
      ('suspension_certificates',adjudication.certify_and_apply),('canonical_affected_years',lambda:stock_identity_views.build(range(2014,2019))),
      ('factor_vintages',factor_repairs.build),('official_factor',factor_actions.build),('factor_population',deep_market_checks.stock_adjustment_checks),
      ('factor_adjudication',factor_actions.classify),('full_numeric_recheck',reconcile.stock_numeric),('code_amendment_recheck',identity_amendment.verify),
      ('basic_arithmetic',deep_market_checks.basic_arithmetic_checks),('market_field_quality',market_quality.build),('market_features',market_features.build),
      ('macro_facts',macro.build),('weekly_views',research_inputs.build),('secondary_market_coverage',source_coverage.build),('catalogue',catalogue.build)]
    path=AUDIT/'reproducibility/final_refresh_stages.json';done=read(path) if path.exists() else []
    original=socket.socket.connect
    def forbidden(*args,**kwargs):raise RuntimeError('Network forbidden during retained-input refresh')
    socket.socket.connect=forbidden
    try:
        for name,fn in stages:
            if any(r['stage']==name and r['status']=='PASS' for r in done):continue
            print('REFRESH',name,flush=True);start=time.monotonic();fn()
            done.append({'stage':name,'status':'PASS','seconds':time.monotonic()-start});write(path,done)
    finally:socket.socket.connect=original


if __name__=='__main__':run()
