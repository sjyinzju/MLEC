"""Static, exportable development calibration curves from saved OOF predictions."""
from pathlib import Path
import os
import sys
ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'audit/framework/matplotlib_cache'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
sys.path.insert(0,str(ROOT))
from scripts.experiment_framework.common import read_json
from scripts.experiment_framework.evaluation import reliability

def build(run_id):
    data=pd.read_parquet(ROOT/f'experiments/predictions/{run_id}.parquet')
    data=data[data.sample_version.eq('common_core_v1')&data.feature_set_id.isin(['M','M_plus_Z_core'])]
    fig,axes=plt.subplots(2,2,figsize=(9,8),sharex=True,sharey=True,layout='constrained')
    for ax,algorithm in zip(axes.flat,['historical_rate','logistic','random_forest','gradient_boosting']):
        ax.plot([0,1],[0,1],color='.6',linestyle=':',linewidth=1)
        for feature,color in [('M','#355C7D'),('M_plus_Z_core','#C06C36')]:
            d=data[data.algorithm_id.eq(algorithm)&data.feature_set_id.eq(feature)]
            for column,style in [('predicted_probability','-'),('calibrated_probability','--')]:
                r=reliability(d.y_true.to_numpy(),d[column].to_numpy())
                ax.plot(r.mean_probability,r.observed_rate,style,color=color,marker='o',markersize=3,label=feature+(' native' if style=='-' else ' calibrated'))
        ax.set(title=algorithm,xlim=(0,1),ylim=(0,1),xlabel='Mean predicted risk',ylabel='Observed frequency')
        ax.grid(alpha=.15)
    axes[0,0].legend(fontsize=7,loc='upper left')
    fig.suptitle('Development 2020-2022: 99 paired OOF weeks\n10 fixed bins; sparse-bin uncertainty is large',fontsize=12)
    folder=ROOT/'reports/benchmark/figures';folder.mkdir(parents=True,exist_ok=True)
    fig.savefig(folder/'core_calibration.png',dpi=180);fig.savefig(folder/'core_calibration.pdf');plt.close(fig)
    return folder/'core_calibration.png'

if __name__=='__main__':print(build(read_json(ROOT/'experiments/registry/latest.json')['run_id']))
