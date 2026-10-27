"""Small interface/invariant checks; no real recording alignment or rendering."""
import importlib.util
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from score_sync.advanced_alignment.guarded_alignment_v3 import source_tempo_hypothesis
from score_sync.alignment_pipeline import correct_guide


def test_unknown_tempo_is_dimensionless_flat():
    guide,rate,meta=source_tempo_hypothesis(np.array([0.,1.,2.]),[3.,7.],
        [{'q':0.,'tempo_metadata':None},{'q':1.,'tempo_metadata':120.}],1.)
    np.testing.assert_allclose(guide,[3.,5.,7.])
    np.testing.assert_allclose(rate,2.)
    assert meta['missing_tempo_metadata'] and meta['effective_exponent']==0


def test_time_domain_warp_preserves_nonlinear_guide_order():
    q=np.array([0.,1.,2.,3.]); t=np.array([0.,.01,.02,10.])
    warped=correct_guide(q,t,{0.:{'seconds':0.},3.:{'seconds':1.}})
    assert np.all(np.diff(warped)>0)
    np.testing.assert_allclose(warped,t/10)


def test_worker_rejects_package_escape_and_uses_current_host_env(tmp_path):
    spec=importlib.util.spec_from_file_location('remote_worker',Path(__file__).resolve().parents[1]/'scripts/remote_render_worker.py')
    worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
    with pytest.raises(ValueError):worker.checked_path(tmp_path,'../outside')
    env=worker.env_for({'runtime':{'tools':{'ffmpeg':'/opt/bin/ffmpeg','chrome':'/opt/chrome'}}})
    assert env['SCORE_SYNC_CHROME']=='/opt/chrome'
    assert env['PATH'].startswith('/opt/bin:')


def test_global_dp_keeps_positive_connected_path_and_fit_rows():
    from score_sync.advanced_alignment.full_alignment_core import global_banded_path,STEPS
    x=np.ones((5,1),np.float32)
    centers=np.arange(5,dtype=np.int64)
    lower=np.array([0,-1,2,-1,4],np.int64)
    upper=lower.copy()
    path,_=global_banded_path.py_func(x,x,x,x,centers,2,np.ones(5),lower,upper,STEPS)
    assert tuple(path[0])==(0,0) and tuple(path[-1])==(4,4)
    assert np.all(np.diff(path,axis=0)>0)


def test_source_tempo_boundary_survives_fit_endpoint_partition():
    from score_sync.advanced_alignment.source_tempo_boundary_policy import complete_source_tempo_boundaries
    cuts,evidence=complete_source_tempo_boundaries(0,20,
        [{'q':0,'tempo_metadata':60},{'q':5,'tempo_metadata':120},
         {'q':10,'tempo_metadata':120},{'q':15,'tempo_metadata':30}],
        [{'effective_tempo_boundaries_q':[15]}])
    assert cuts==[5.,15.]
    assert evidence['previously_omitted_cuts']==[5.]
