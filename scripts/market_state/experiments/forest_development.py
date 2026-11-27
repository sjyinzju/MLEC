"""Explicit bounded RF development contrasts. No C reads or formal lock."""
from argparse import ArgumentParser
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from ..common import CORE, KEY, ROOT, digest
from ..framework import load_dataset, paired_losses
from ..interface_acceptance import assert_interface_accepted
from .artifacts import atomic_json, atomic_parquet, native_path, read_json
from .config import RF_INFORMATION, candidates, data_store, load_config
from .forest_mechanism import FinancialResiduals, LAMBDAS
from .forest_selection import probability_grid
from .runtime import environment, fold_lists, versions
from .technical import _TechnicalRunner


RECEIPTS = ROOT / 'reports/model_build/random_forest/final_optimization'
MARKETS = ('000300.SH', '000905.SH')
FOLDS = ('2020-03', '2020-08', '2021-03', '2021-09', '2022-04', '2022-11')
def design(config, development):
    clf = candidates(config, 'classification')
    layouts = {name: clf[index]['parameters'] for name, index in [
        ('shallow_natural', 17), ('balanced_all_features', 2), ('mid_depth_natural', 4)]}
    reg = candidates(config, 'regression')[2]['parameters']
    for market in MARKETS:
        for info in RF_INFORMATION:
            full = (market, info) == (MARKETS[0], 'M+Z_star')
            for fold in development if full else FOLDS:
                for seed in config['search']['stability_seeds']:
                    for name, parameters in layouts.items():
                        yield dict(task='classification', market=market, fold=fold, information=info,
                                   parameters=parameters, seed=seed), name
            for fold in FOLDS:
                for seed in (3060, 3061):
                    for name in ('native', 'independent'):
                        yield dict(task='regression', market=market, fold=fold, information=info,
                                   parameters=dict(reg, regression_architecture=name), seed=seed), name


def classification_tables(probabilities, ids, alphas):
    summaries = []
    for (market, information, label, seed), group in probabilities.groupby(
            ['market_id', 'information_set', 'layout', 'seed']):
        native = group[['native_state_prob_' + str(c) for c in ids]].to_numpy()
        hit = (native[np.arange(len(group)), [ids.index(v) for v in group.observed_state_id]] <= 1e-15)
        history = float(probability_grid(group, ids, [1.])[0][1].log_loss.mean())
        for alpha, losses in probability_grid(group, ids, alphas):
            summaries.append(dict(market_id=market, information_set=information, layout=label, seed=seed,
                alpha=alpha, rows=len(group), log_loss=float(losses.log_loss.mean()), brier=float(losses.brier.mean()),
                floor_hits=int(hit.sum()) if alpha == 0 else 0, loss_on_native_floor_rows=float(losses.log_loss[hit].sum()),
                historical_log_loss=history))
    by_seed = pd.DataFrame(summaries)
    choices = []
    for (market, information), group in by_seed.groupby(['market_id', 'information_set']):
        grid = group[group.alpha.gt(0)]
        first = grid[grid.seed.eq(3060)].sort_values(['log_loss', 'brier']).iloc[0]
        reviewed = grid.groupby(['layout', 'alpha'], as_index=False).agg(
            mean_log_loss=('log_loss', 'mean'), seed_std=('log_loss', 'std'), mean_brier=('brier', 'mean'))
        winner = reviewed.sort_values(['mean_log_loss', 'mean_brier']).iloc[0]
        original = group[group.alpha.eq(0) & group.layout.eq(winner.layout)]
        held = grid[grid.layout.eq(first.layout) & grid.alpha.eq(first.alpha)]
        choices.append(dict(market_id=market, information_set=information, rows=int(group.rows.max()),
            screening_layout=first.layout, screening_alpha=float(first.alpha), screening_loss=float(first.log_loss),
            screening_choice_three_seed_loss=float(held.log_loss.mean()), winner_layout=winner.layout,
            winner_alpha=float(winner.alpha), stabilized_log_loss=float(winner.mean_log_loss),
            stabilized_brier=float(winner.mean_brier), stabilized_seed_std_population=float(
                grid[grid.layout.eq(winner.layout) & grid.alpha.eq(winner.alpha)].log_loss.std(ddof=0)),
            matched_native_log_loss=float(original.log_loss.mean()), matched_native_brier=float(original.brier.mean()),
            matched_native_floor_hits=int(original.floor_hits.sum()), historical_log_loss=float(original.historical_log_loss.mean())))
    return by_seed, pd.DataFrame(choices)


def regression_tables(scores):
    records = []
    for (market, information, seed), group in scores.groupby(['market_id', 'information_set', 'seed']):
        native = group[group.layout.eq('native')].sort_values(KEY)
        independent = group[group.layout.eq('independent')].sort_values(KEY)
        paired_losses(native, independent, task='regression')
        for layout, part in [('native', native), ('independent', independent)]:
            records.append(dict(market_id=market, information_set=information, seed=seed, layout=layout,
                rows=len(part), loss=float(part.loss.mean()),
                **{k: float(part[k].mean()) for k in part if k.startswith('squared_') and not k.startswith('squared_error_')},
                **{'rmse_' + c: float(np.sqrt(part['squared_error_' + c].mean())) for c in CORE}))
    summaries = pd.DataFrame(records)
    grouped = summaries.groupby(['market_id', 'information_set', 'layout']).loss.mean().unstack()
    relative = (grouped.native - grouped.independent) / grouped.native
    eligible = relative.mean() >= .02 and int((relative > 0).sum()) >= 5
    return summaries, dict(independent_supported=bool(eligible), required_mean_relative_gain=.02,
        required_positive_cells=5, mean_relative_gain=float(relative.mean()),
        positive_cells=int((relative > 0).sum()), cells=len(relative))


def mechanism_tables(scores):
    scores = scores.assign(period=np.where(scores.fold_id.str.startswith('2022'), 'confirmation_2022', 'tune_2020_21'))
    grouped = scores.groupby(['market_id', 'correction', 'strength', 'period'], as_index=False).loss.mean()
    tune = grouped[grouped.period.eq('tune_2020_21')].sort_values(['loss', 'strength'])
    chosen = tune.drop_duplicates(['market_id', 'correction'])
    confirmed = grouped[grouped.period.eq('confirmation_2022')].merge(
        chosen[['market_id', 'correction', 'strength']], on=['market_id', 'correction', 'strength'], validate='one_to_one')
    anchor = grouped[grouped.period.eq('confirmation_2022') & grouped.strength.eq(0)
                     & grouped.correction.eq('M')].set_index('market_id').loss
    capacity = confirmed[confirmed.correction.eq('M')].set_index('market_id').loss
    confirmed['anchor_loss'] = confirmed.market_id.map(anchor)
    confirmed['financial_correction_loss'] = confirmed.market_id.map(capacity)
    confirmed['relative_gain_vs_anchor'] = 1 - confirmed.loss / confirmed.anchor_loss
    confirmed['relative_gain_vs_financial_correction'] = 1 - confirmed.loss / confirmed.financial_correction_loss
    supported = confirmed[confirmed.correction.isin(['M+Z', 'M+Z_star'])
                          & confirmed.relative_gain_vs_anchor.ge(.02)
                          & confirmed.relative_gain_vs_financial_correction.ge(.02)]
    deployed = [k for k, part in supported.groupby('correction') if part.market_id.nunique() == len(MARKETS)]
    return grouped, confirmed, deployed


def run(*, execute, workers, destination, scratch=None):
    if not execute:
        raise ValueError('Explicit --execute required for the bounded development experiment')
    start = perf_counter()
    config = load_config(ROOT / 'config/experiments/random_forest.yaml')
    config['data_root'] = str(ROOT / config['data_root'])
    store = data_store(config)
    assert_interface_accepted(data_root=store.root, feature_extension='z_star')
    env = environment()
    identity = versions(config, store)
    development, _ = fold_lists(store)
    workloads = list(design(config, development))
    destination.mkdir(parents=True, exist_ok=True)
    work = (scratch or ROOT / '.local_deps/rf-bounded-development') / digest(identity)[:16]
    from .artifacts import exclusive_run
    with exclusive_run(work):
        runner = _TechnicalRunner(config, store, work, workers)
        print('Bounded development monthly fits:', len(workloads), flush=True)
        items = [(runner.task(stage='development', mode='development_probe', **kwargs), False)
                 for kwargs, _ in workloads]
        try:
            records = runner.scheduler.map(items)
        finally:
            runner.scheduler.close()
        print('Classifier and regression fits complete. Processing time-forward residual corrections.', flush=True)
        probabilities, regressions, training, mechanism, provenance = [], [], [], [], []
        residual_services = {}
        for (kwargs, label), (task, _), record in zip(workloads, items, records):
            folder = runner.root / record['artifact']
            market, info, fold, seed = (kwargs[k] for k in ('market', 'information', 'fold', 'seed'))
            meta = dict(layout=label, information_set=info, fold_id=fold, seed=seed)
            if kwargs['task'] == 'classification':
                report = pd.read_parquet(folder / 'probability_evidence.parquet')
                probabilities.append(report[report.observed_state_id.notna()].assign(**meta))
                continue
            scores = pd.read_parquet(folder / 'losses.parquet')
            regressions.append(scores.assign(**meta))
            detail = read_json(folder / 'forest_diagnostics.json')
            training.extend(dict(meta, market_id=market, target=c, train_rmse=detail['train_rmse'][c],
                train_loss=detail['train_five_dimension_squared'],
                adapted_split_sse_share=detail['adapted_target_split_sse_reduction_share'][c])
                for c in CORE)
            if (info, label, seed) != ('M', 'native', 3060):
                continue
            service = residual_services.setdefault(market, FinancialResiduals(kwargs['parameters'], seed, config['policy']))
            ds_args = dict(market_id=market, fold_id=fold, task='regression', store=store, quality=config['quality'])
            train, pred = (load_dataset(**ds_args, information_set='M+Z_star', role=role) for role in ['train', 'prediction'])
            original_train, original_pred = (load_dataset(**ds_args, information_set='M+Z', role=role)
                                             for role in ['train', 'prediction'])
            truth = load_dataset(**ds_args, information_set='M+Z_star', role='validation')
            original_truth = load_dataset(**ds_args, information_set='M+Z', role='validation')
            expanded, trail = service.evaluate(train, pred, original_train, original_pred, truth, original_truth,
                pd.read_parquet(folder / 'predictions.parquet'), scores, store, runner.executor.scales[market])
            mechanism.append(expanded)
            provenance.extend(dict(row, market_id=market, fold_id=fold, outer_cutoff=str(train.metadata.fit_cutoff.iloc[0]))
                              for row in trail)
        probabilities = pd.concat(probabilities, ignore_index=True)
        regressions = pd.concat(regressions, ignore_index=True)
        mechanism = pd.concat(mechanism, ignore_index=True)
        class_grid, class_choices = classification_tables(probabilities, store.target_schema()['class_ids'],
                                                          config['search']['probability_alphas'])
        reg_summary, architecture = regression_tables(regressions)
        mech_grid, mech_selected, support = mechanism_tables(mechanism)
        tables = dict(classification_grid=class_grid, classification_selection=class_choices,
            regression_development=reg_summary, regression_training=pd.DataFrame(training),
            residual_grid=mech_grid, residual_confirmation=mech_selected, residual_time_blocks=pd.DataFrame(provenance))
        for name, frame in tables.items():
            frame.to_csv(destination / (name + '.csv'), index=False)
        for name, frame in dict(classification_weeks=probabilities, regression_weeks=regressions,
                                residual_weeks=mechanism).items():
            atomic_parquet(destination / (name + '.parquet'), frame)
        if versions(config, store) != identity:
            raise RuntimeError('Execution source or configuration changed during the development comparison')
        receipt = dict(status='COMPLETED', purpose='BOUNDED_DEVELOPMENT_ONLY', identity=identity,
            environment=env, markets=MARKETS, representative_folds=FOLDS,
            complete_classification_group=['000300.SH', 'M+Z_star', development],
            unchanged_scoring_floor=1e-15, held_out_stage='B', formal_C_fits=0, workers=workers,
            scheduled_monthly_tasks=len(records), scheduler_estimator_fit_calls=sum(r['estimator_fit_calls'] for r in records),
            correction_eligible=support, correction_strengths=LAMBDAS, exact_lambda_zero=True,
            correction_fits=int(len(mechanism.groupby(['market_id', 'fold_id', 'correction']))),
            inner_anchor_fits=sum(s.inner_fits for s in residual_services.values()),
            regression_architecture_evidence=architecture, elapsed_seconds=perf_counter() - start)
        atomic_json(destination / 'development_probe.json', receipt)
        print(receipt, flush=True)


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--destination', type=Path, default=RECEIPTS)
    parser.add_argument('--scratch', type=Path)
    args = parser.parse_args()
    run(execute=args.execute, workers=args.workers, destination=args.destination, scratch=args.scratch)
