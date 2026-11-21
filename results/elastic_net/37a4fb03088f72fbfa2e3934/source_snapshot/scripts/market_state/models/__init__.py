"""Model registration; unimplemented families fail before any data or fitting."""
from ..model_contract import ModelCapabilities

REGISTRY = {
    'elastic_net': {'family': 'Elastic Net', 'implemented': True, 'backends': ['cpu'],
                    'regression': 'per_target', 'calibration': 'native', 'adapter': 'elastic_net.ElasticNetAdapter', 'deterministic_regression': True},
    'rbf_svm': {'family': 'RBF-SVM', 'implemented': True, 'backends': ['cpu'],
                'adapter': 'rbf_svm.RBFSVMAdapter', 'regression': 'per_target', 'calibration': 'training_time_ordered',
                'deterministic_classification': True, 'deterministic_regression': True},
    'random_forest': {'family': 'Random Forest', 'implemented': False, 'backends': ['cpu'],
                     'regression': 'native', 'calibration': 'native'},
    'catboost': {'family': 'CatBoost', 'implemented': False, 'backends': ['cpu', 'gpu'],
                 'regression': 'native', 'calibration': 'native'},
}


def capabilities(model, task):
    record = REGISTRY[model]
    return ModelCapabilities(record['family'], task,
        record['regression'] if task == 'regression' else 'not_applicable',
        missing_class_policy='explicit_error_or_zero_for_absent',
        probability_calibration=record['calibration'])


def require_model(model, backend='cpu'):
    if model not in REGISTRY:
        raise ValueError('Unknown model: ' + model)
    if not REGISTRY[model]['implemented']:
        raise ValueError('Model is registered but not implemented: ' + model)
    if backend not in REGISTRY[model]['backends']:
        raise ValueError('Unsupported backend: ' + backend)


def create_model(model, **kwargs):
    require_model(model)
    from importlib import import_module
    module, name = REGISTRY[model]['adapter'].rsplit('.', 1)
    return getattr(import_module(__name__ + '.' + module), name)(**kwargs)
