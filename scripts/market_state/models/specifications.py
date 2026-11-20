"""Family-specific search, solver and selection rules; no fitting on import."""
import numpy as np

SVM_TIE = 'score_then_lower_C_then_lower_gamma_factor_then_larger_epsilon_then_candidate_id'
EN_TIE = 'score_then_stronger_regularization_then_lower_l1_ratio_then_candidate_id'


def validate_family(c):
    s, p = c['search'], c['policy']
    family = c['model']
    if family == 'elastic_net':
        if s['classification_C'] != [1e-4, 1e4] or s['regression_alpha'] != [1e-5, 10.]:
            raise ValueError('Formal regularization ranges changed')
        if s['l1_ratios'] != [.05, .25, .5, .75, .95, 1.] or s['tie_rule'] != EN_TIE:
            raise ValueError('Formal Elastic Net ratio/tie rules changed')
        if s['stability_seeds'] != [3060, 3061, 3062]:
            raise ValueError('Use the registered Elastic Net stability seeds')
        if c['retention'].get('coefficients') != 'all_successful_fits':
            raise ValueError('Elastic Net coefficient retention required')
    elif family == 'rbf_svm':
        if s['candidate_count'] != 48 or s['finalists'] != 4:
            raise ValueError('Formal SVM budget is 48 candidates / 4 finalists')
        if s['classification_C'] != [1e-3, 1e3] or s['regression_C'] != [1e-3, 1e3] or s['epsilon'] != [.001, 1.]:
            raise ValueError('Formal SVM C/epsilon ranges changed')
        if s['gamma_factors'] != [.01, .1, 1., 10., 100.] or s['tie_rule'] != SVM_TIE:
            raise ValueError('Formal relative gamma/tie rule changed')
        if s['stability_seeds'] != [3060] or s['gamma_rule'] != 'factor_over_n_features_times_population_variance_zero_variance_base_one':
            raise ValueError('SVM is deterministic; use training-only relative gamma')
        if s['tol'] != .001 or s['max_iter'] != 100000 or p['convergence_retries'] != 1 or p['iteration_multiplier'] != 4:
            raise ValueError('SVM uses fixed 1e-3 tolerance and 100000/400000 iteration limits')
        solver = c['solver']
        if solver['kernel'] != 'rbf' or solver['probability'] is not False or solver['decision_function_shape'] != 'ovr' or solver['shrinking'] is not True:
            raise ValueError('Use the registered RBF solver without built-in probability')
        if not np.isfinite(solver['cache_size_mb']) or not 1 <= solver['cache_size_mb'] <= 1024:
            raise ValueError('SVM per-process kernel cache must be 1..1024 MiB')
        expected = dict(version='svm-time-sigmoid-v2', initial_train_weeks=13, block_weeks=26,
            min_train_rows=8, min_train_per_class=1, min_oof_per_class=2,
            min_oof_rows=26, min_accepted_blocks=2, missing_inner='skip_block_unless_all_dictionary_classes_in_train',
            invalid_calibration='fail_entire_outer_task', sigmoid='platt_smoothed_binary_cross_entropy',
            normalization='clip_expit_1e-15_then_divide_row_sum', probability_floor=1e-15,
            max_iter=1000, ftol=1e-12, gtol=1e-8, maxls=50, optimization_retries=0, optimality_gradient=1e-8, newton_steps=20)
        if c['calibration'] != expected:
            raise ValueError('Unregistered time calibration rules')
        if c['retention'].get('diagnostics') != 'all_successful_fits':
            raise ValueError('SVM kernel/calibration diagnostic retention required')
    else:
        raise ValueError('Family rules are not implemented: ' + family)
    if s['screening_seed'] != 3060 or s['regression_deterministic_seeds'] != [3060] or s['generator_seed'] != 3059:
        raise ValueError('Use the registered deterministic generation and fit seeds')


def validate_parameters(family, task, p):
    if family == 'elastic_net':
        key = 'C' if task == 'classification' else 'alpha'
        expected = {key, 'l1_ratio', 'tol', 'max_iter'}
        valid = p.get(key, 0) > 0 and 0 <= p.get('l1_ratio', -1) <= 1
    elif family == 'rbf_svm':
        expected = {'C', 'gamma_factor', 'tol', 'max_iter'} | ({'epsilon'} if task == 'regression' else set())
        valid = .001 <= p.get('C', 0) <= 1000 and p.get('gamma_factor') in [.01, .1, 1., 10., 100.]
        valid = valid and (task != 'regression' or .001 <= p.get('epsilon', 0) <= 1)
    else:
        raise ValueError('No candidate rules for ' + family)
    if set(p) != expected or not valid or not np.isfinite(list(p.values())).all() or p['tol'] <= 0 or type(p['max_iter']) is not int or p['max_iter'] < 1:
        raise ValueError('Illegal ' + family + ' candidate parameters')


def complexity(family, task, p):
    if family == 'elastic_net':
        return [p['C'] if task == 'classification' else -p['alpha'], p['l1_ratio']]
    return [p['C'], p['gamma_factor']] + ([-p['epsilon']] if task == 'regression' else [])


def generate_parameters(config, task):
    s = config['search']
    rng = np.random.default_rng(s['generator_seed'])
    if config['model'] == 'elastic_net':
        values = np.geomspace(*s['classification_C' if task == 'classification' else 'regression_alpha'], s['candidate_count'])
        ratios = np.resize(s['l1_ratios'], s['candidate_count'])
        rng.shuffle(ratios)
        return [dict(**{('C' if task == 'classification' else 'alpha'): float(v)}, l1_ratio=float(r),
            tol=s['tol'], max_iter=s['max_iter']) for v, r in zip(values, ratios)]
    values = np.geomspace(*s['classification_C' if task == 'classification' else 'regression_C'], s['candidate_count'])
    gammas = np.resize(s['gamma_factors'], s['candidate_count'])
    rng.shuffle(gammas)
    eps = np.geomspace(*s['epsilon'], s['candidate_count']) if task == 'regression' else None
    if eps is not None:
        rng.shuffle(eps)
    return [dict(C=float(v), gamma_factor=float(g), tol=s['tol'], max_iter=s['max_iter'],
        **({'epsilon': float(eps[j])} if eps is not None else {})) for j, (v, g) in enumerate(zip(values, gammas))]
