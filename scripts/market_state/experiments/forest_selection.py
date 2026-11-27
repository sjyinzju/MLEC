"""Full-span forest selection using one probability forecast per structure and seed."""
import numpy as np

from ..evaluation import multiclass_losses
from ..models.random_forest import shrink_probabilities


def probability_grid(rows, ids, alphas, *, observed='observed_state_id'):
    native = rows[['native_state_prob_' + str(c) for c in ids]].to_numpy()
    prior = rows[['train_history_prob_' + str(c) for c in ids]].to_numpy()
    return [(float(alpha), multiclass_losses(rows[observed], shrink_probabilities(native, prior, alpha), ids))
            for alpha in alphas]


def summarize_seeds(candidate, per_seed, task, seed_ids):
    """Compare seed losses on exactly the same weeks, never ensemble the probabilities."""
    first = per_seed[0]
    result = {k: first[k] for k in ('expected_months', 'candidate_id', 'parameters', 'complexity_order')}
    result['per_seed'] = dict(zip(map(str, seed_ids), per_seed))
    if not all(row['valid'] for row in per_seed):
        return dict(result, valid=False, score=None, reason='REQUIRED_MONTH_OR_SEED_FAILED')
    if any(row['cohort_hash'] != first['cohort_hash'] for row in per_seed):
        raise RuntimeError('Forest seeds do not cover the same development weeks and labels')
    result.update(valid=True, n=first['n'], cohort_hash=first['cohort_hash'])
    if task == 'classification':
        grid = []
        for index, row in enumerate(first['probability_grid']):
            scores = [seed['probability_grid'][index] for seed in per_seed]
            grid.append(dict(alpha=row['alpha'], log_loss=float(np.mean([s['log_loss'] for s in scores])),
                             brier=float(np.mean([s['brier'] for s in scores]))))
        choice = min((s for s in grid if s['alpha'] > 0), key=lambda s: (s['log_loss'], -s['alpha']))
        index = grid.index(choice)
        losses = [row['probability_grid'][index]['log_loss'] for row in per_seed]
        result.update(parameters=dict(candidate['parameters'], probability_alpha=choice['alpha']),
                      probability_grid=grid, class_support=first['class_support'], event_runs=first['event_runs'])
    else:
        losses = [row['score'] for row in per_seed]
        result['target_scores'] = {c: float(np.mean([row['target_scores'][c] for row in per_seed]))
                                   for c in first['target_scores']}
    return dict(result, score=float(np.mean(losses)), seed_loss_std=float(np.std(losses)),
                seed_loss_range=[float(min(losses)), float(max(losses))],
                selected_scores_by_seed=dict(zip(map(str, seed_ids), losses)))
