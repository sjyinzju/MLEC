"""Analytic certificates and mocked optimizers only. Never fit a real model."""
from copy import deepcopy
from types import SimpleNamespace
import numpy as np
import pytest
from scripts.market_state.models.svm_quality import solution_quality, weight_hash
from scripts.market_state.models.rbf_svm import relative_gamma
from scripts.market_state.models.calibration import TimeSigmoid
from scripts.market_state.models.errors import FitFailure
from scripts.market_state.experiments.config import load_config


def test_analytic_svr_and_binary_svc_kkt():
    x=np.array([[-1.],[1.]])
    a=.9/(1-np.exp(-2))
    e=SimpleNamespace(_gamma=.5,tol=.001,C=2.,epsilon=.1,support_=np.array([0,1]),
        dual_coef_=np.array([[-a,a]]),intercept_=np.zeros(1))
    q=solution_quality(e,x,np.array([-1.,1.]))
    assert q['accepted'] and abs(q['checks'][0]['gap'])<1e-12
    e.intercept_[:]=10.
    assert not solution_quality(e,x,np.array([-1.,1.]))['accepted']
    a=1/(1-np.exp(-2));e.dual_coef_=np.array([[-a,a]]);e.intercept_[:]=0
    e.classes_=np.array([0,1]);e.n_support_=np.array([1,1])
    assert solution_quality(e,x,np.array([0,1]))['accepted']


def test_analytic_multiclass_ovo_kkt():
    x=np.array([[0.,0.],[1.,0.],[.5,np.sqrt(.75)]])
    a=1/(1-np.exp(-1.))
    e=SimpleNamespace(_gamma=1.,tol=.001,C=2.,support_=np.arange(3),classes_=np.arange(3),n_support_=np.ones(3,dtype=int),
        dual_coef_=a*np.array([[1.,-1.,-1.],[1.,1.,-1.]]),intercept_=np.zeros(3))
    q=solution_quality(e,x,np.arange(3))
    assert q['accepted'] and len(q['checks'])==3


def test_canonical_state_ignores_views_but_binds_private_prediction_weights():
    a=SimpleNamespace(support_vectors_=np.arange(12.).reshape(3,4),_dual_coef_=np.ones((2,3)),_gamma=.1)
    b=deepcopy(a);b.support_vectors_=np.asfortranarray(a.support_vectors_)
    assert weight_hash([a])==weight_hash([b])
    b._dual_coef_[0,0]+=1
    assert weight_hash([a])!=weight_hash([b])


def test_gamma_finite_extremes_are_not_silently_zero_variance():
    x=np.array([[-1e150],[1e150]])
    assert relative_gamma(x,1.)==pytest.approx(1e-300,abs=0,rel=1e-14)
    with pytest.raises(FitFailure): relative_gamma(np.array([[-1e-250],[1e-250]]),1.)
    for value in [0,-1,np.nan,np.inf]:
        with pytest.raises(ValueError): relative_gamma(np.ones((2,1)),value)


def test_false_optimizer_success_is_rejected_without_real_polish(monkeypatch):
    rules=load_config('config/experiments/rbf_svm.yaml')['calibration']
    c=TimeSigmoid(rules)
    monkeypatch.setattr(TimeSigmoid,'optimize',lambda *args:SimpleNamespace(x=np.array([20.,20.]),fun=0.,jac=np.zeros(2),success=True,nit=1,status=0,message='FAKE_SUCCESS'))
    monkeypatch.setattr(TimeSigmoid,'polish',lambda self,p,x,y,t:(p,100.,np.ones(2),0))
    with pytest.raises(FitFailure):c.fit(np.tile([-1.,0.,1.],(9,1)),np.tile([0,1,2],3),[0,1,2])
    assert c.diagnostics_[0]['quality']['accepted'] is False
