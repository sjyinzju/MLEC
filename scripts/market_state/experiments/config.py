"""Versioned formal configuration and reproducible, symmetric candidate budgets."""
from copy import deepcopy
from pathlib import Path
import json
import numpy as np
from ..common import ROOT, MARKETS, digest

CONFIG = ROOT / 'config/experiments/elastic_net.yaml'
MODES = ['retuned_core', 'fixed_full_params']


def load_config(path=CONFIG):
    # JSON is a YAML 1.2 subset: a .yaml file needs no extra YAML dependency.
    config = json.loads(Path(path).read_text(encoding='utf8'))
    validate_config(config)
    return config


def validate_config(c):
    if c['schema_version'] != 'experiments-v1' or c['purpose'] != 'RESEARCH':
        raise ValueError('Formal commands require a RESEARCH experiments-v1 config')
    if c['markets'] != list(MARKETS) or c['tasks'] != ['classification', 'regression']:
        raise ValueError('Formal scope requires four markets and both primary tasks')
    s, p, r = c['search'], c['policy'], c['resources']
    if s['candidate_count'] < 32 or s['finalists'] < 4 or s['finalists'] > s['candidate_count']:
        raise ValueError('Formal two-stage search budget may not shrink below 32/4')
    if s['development_years'] != [2020, 2021, 2022] or s['coarse_months'] != [1, 4, 7, 10]:
        raise ValueError('Use the fixed development schedule')
    if s['classification_C'] != [1e-4, 1e4] or s['regression_alpha'] != [1e-5, 10.]:
        raise ValueError('Formal regularization ranges changed')
    if s['l1_ratios'] != [.05, .25, .5, .75, .95, 1.]:
        raise ValueError('Formal l1_ratio support changed')
    if s['stability_seeds'] != [3060, 3061, 3062] or s['screening_seed'] != 3060 or s['regression_deterministic_seeds'] != [3060]:
        raise ValueError('Use the registered seeds; cyclic regression is deterministic')
    integer_fields = [s['candidate_count'], s['finalists'], s['max_iter'], p['convergence_retries'],
        p['iteration_multiplier'], p['task_attempts'], r['cpu_workers'], r['threads_per_task'], r['transform_cache_entries']]
    if any(type(v) is not int for v in integer_fields):
        raise ValueError('Budgets, iterations, retries and CPU/cache counts must be integers')
    if not np.isfinite(s['tol']) or s['tol'] <= 0 or s['max_iter'] < 1 or p['convergence_retries'] < 0 or p['iteration_multiplier'] < 1 or p['task_attempts'] < 1:
        raise ValueError('Invalid convergence/retry rule')
    if r['cpu_workers'] != 1 or r['threads_per_task'] < 1 or r['transform_cache_entries'] < 1 or r['max_run_gb'] <= 0:
        raise ValueError('This bounded scheduler uses one outer worker and positive task thread/cache limits')
    if c['backend'] != 'cpu' or c['quality'] != 'historical_reconstructed':
        raise ValueError('Only the registered CPU/main data-view route is implemented')
    if c['warning']['burdens'] != [.05, .1, .2, .3] or not c['warning']['calendar_gap_breaks_segment']:
        raise ValueError('Warning burden/segment rules must be fixed before testing')
    if c['statistics']['block_weeks'] != [8, 4, 12] or c['statistics']['repetitions'] < 2000:
        raise ValueError('Use the registered bootstrap budget and sensitivity blocks')
    expected = {
        'tie_rule': 'score_then_stronger_regularization_then_lower_l1_ratio_then_candidate_id',
        'seed_aggregation': 'mean_loss_per_sample_not_probability_ensemble',
        'failed_candidate': 'exclude_entire_candidate_if_any_required_month_fails'}
    if any(s[k] != v for k, v in expected.items()):
        raise ValueError('Unsupported selection rule')
    if p['single_class'] != 'error' or p['missing_class'] not in ['error', 'zero_for_absent'] or p['numerical_warning'] != 'error':
        raise ValueError('Unsupported class/numerical failure policy')
    if p['class_weight'] not in [None, 'balanced']:
        raise ValueError('Class weight must be null or balanced')
    stats = c['statistics']
    if (stats['primary_market'], stats['primary_task'], stats['primary_metric'], stats['confidence']) != ('000985.SH', 'classification', 'log_loss', .95) or stats['holm_families'] != ['rbf_svm', 'random_forest', 'catboost']:
        raise ValueError('The common preregistered primary test family cannot change')
    if c['warning']['risk_flags'] != ['risk_downside', 'risk_liquidity', 'risk_broad_decline']:
        raise ValueError('Use fixed training-profile risk definitions')
    if not np.isfinite(c['baselines']['history_dirichlet_alpha']) or c['baselines']['history_dirichlet_alpha'] <= 0:
        raise ValueError('Positive prespecified historical frequency smoothing required')
    if c['warning']['threshold_rule'] != 'largest_attainable_development_burden_not_exceeding_target':
        raise ValueError('Unsupported warning threshold rule')
    if c['retention'] != {'candidate_weights': 'full_review_final_month_only', 'selected_weights': 'test_core_monthly_and_other_final_month', 'coefficients': 'all_successful_fits'}:
        raise ValueError('Unsupported retention policy')
    return c


def portable_config(c):
    result = deepcopy(c)
    result.pop('data_root', None)
    result.pop('output_root', None)
    for key in ['minimum_free_gb', 'max_run_gb', 'transform_cache_entries']:
        result['resources'].pop(key, None)  # operational limits do not alter a fit
    return result


def candidates(config, task):
    """Stratified log coverage includes both endpoints and every sparse ratio."""
    s = config['search']
    if 'candidates' in s:
        # Other registered families can supply pregenerated parameters and a
        # preregistered complexity order without changing the scheduler/scorer.
        result = []
        for entry in s['candidates'][task]:
            if config['model'] == 'elastic_net':
                p = entry['parameters']
                expected = {'C' if task == 'classification' else 'alpha', 'l1_ratio', 'tol', 'max_iter'}
                positive = p.get('C' if task == 'classification' else 'alpha', 0)
                if set(p) != expected or not np.isfinite(list(p.values())).all() or positive <= 0 or not 0 <= p['l1_ratio'] <= 1 or p['tol'] <= 0 or type(p['max_iter']) is not int or p['max_iter'] < 1:
                    raise ValueError('Illegal Elastic Net candidate parameters')
            result.append(dict(candidate_id=digest(entry['parameters'])[:16],
                parameters=deepcopy(entry['parameters']), complexity_order=entry['complexity_order']))
        if len(result) != s['candidate_count'] or len({r['candidate_id'] for r in result}) != len(result):
            raise ValueError('Explicit candidate budget/identity mismatch')
        return result
    if config['model'] != 'elastic_net':
        raise ValueError('This family must register explicit candidates')
    count, ratios = s['candidate_count'], s['l1_ratios']
    low, high = s['classification_C' if task == 'classification' else 'regression_alpha']
    rng = np.random.default_rng(s['generator_seed'])
    values = np.geomspace(low, high, count)
    ratio_order = np.resize(ratios, count)
    rng.shuffle(ratio_order)
    result = []
    for i, (value, ratio) in enumerate(zip(values, ratio_order)):
        parameters = {('C' if task == 'classification' else 'alpha'): float(value),
            'l1_ratio': float(ratio), 'tol': s['tol'], 'max_iter': s['max_iter']}
        result.append(dict(candidate_id=digest(parameters)[:16], parameters=parameters,
            complexity_order=[float(value) if task == 'classification' else -float(value), float(ratio)]))
    return result


def seeds(config, task):
    from ..models import REGISTRY
    deterministic = task == 'regression' and REGISTRY[config['model']].get('deterministic_regression', False)
    return config['search']['regression_deterministic_seeds' if deterministic else 'stability_seeds']


def scope(config, store, suite):
    if suite not in ['core', 'full']:
        extension = config['extensions'].get(suite)
        if extension:
            raise ValueError('Extension not implemented: ' + suite + '; requires ' + extension['requires'])
        raise ValueError('Unknown suite: ' + suite)
    sets = list(store.spec['sets'])
    if len(sets) != 12 or sets[:2] != ['M', 'M+Z']:
        raise ValueError('Expected the sealed twelve information sets')
    return [('retuned_core', i) for i in ['M', 'M+Z']] + (
        [('fixed_full_params', i) for i in sets] if suite == 'full' else [])
