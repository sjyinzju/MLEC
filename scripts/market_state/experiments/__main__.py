"""No-execute commands cannot reach the supervised fitting path."""
import argparse
from pathlib import Path
import json
from ..common import ROOT
from ..framework import DataStore
from ..models import REGISTRY, require_model
from .artifacts import atomic_json, exclusive_run
from .config import CONFIG, load_config
from .runtime import preview, preflight


def main(argv=None):
    parser = argparse.ArgumentParser(description='MLEC explicit B -> lock -> C experiment runner')
    parser.add_argument('command', choices=['plan', 'preflight', 'pipeline', 'run', 'lock', 'summarize', 'package', 'smoke'])
    parser.add_argument('--model', choices=list(REGISTRY))
    parser.add_argument('--config', type=Path)
    parser.add_argument('--suite', default='full')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--output-root', type=Path)
    parser.add_argument('--cpu-threads', type=int)
    parser.add_argument('--cpu-workers', type=int, help='outer processes; 0 selects CPU/memory bounded default')
    parser.add_argument('--run-id')
    parser.add_argument('--run', dest='runs', type=Path, action='append')
    parser.add_argument('--stage', choices=['development', 'test'])
    parser.add_argument('--lock', type=Path)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--plan-output', type=Path)
    args = parser.parse_args(argv)
    if args.config is None:
        args.config = ROOT / ('config/experiments/' + (args.model or 'elastic_net') + '.yaml')
    if args.model:
        require_model(args.model)
    if args.command == 'smoke':
        from .smoke import smoke
        return smoke(args)
    config = load_config(args.config)
    if args.model and args.model != config['model']:
        parser.error('--model and config model disagree')
    require_model(config['model'], config['backend'])
    for key in ['data_root', 'output_root']:
        value = getattr(args, key)
        config[key] = str((value if value is not None else ROOT / config[key]).resolve())
    if args.cpu_threads is not None:
        config['resources']['threads_per_task'] = args.cpu_threads
    if args.cpu_workers is not None:
        config['resources']['cpu_workers'] = args.cpu_workers
    from .config import validate_config
    validate_config(config)
    if args.command == 'summarize':
        if not args.runs:
            parser.error('summarize requires explicit --run directories; never selects latest')
        if len(args.runs) == 1:
            from .reports import summarize
            result = summarize(args.runs[0], stage=args.stage or 'test')
            print(json.dumps({k: len(v) for k, v in result.items()}, indent=2))
        else:
            if not args.destination:
                parser.error('cross-model summarize requires --destination')
            from .summary import summarize_runs
            print(summarize_runs(args.runs, args.destination))
        return
    store = DataStore(config['data_root'])
    if args.command in ['plan', 'pipeline', 'run'] and (args.command == 'plan' or not args.execute):
        result = preview(config, store, args.suite)
        if args.plan_output:
            atomic_json(args.plan_output, result)
        print(json.dumps({k: v for k, v in result.items() if k not in ['candidate_monthly_tasks', 'configurations', 'candidates', 'calibration_plans', 'calibration_fit_expansion']}, ensure_ascii=False, indent=2))
        return result
    if args.command == 'preflight':
        result = preflight(config, store, args.suite)
        atomic_json(ROOT / 'reports/model_build' / config['model'] / 'preflight.json', result)
        print('PREFLIGHT_PASSED; supervised fits=0; smoke=0')
        return result
    if args.command == 'package':
        if not args.destination:
            parser.error('package requires a new --destination directory')
        from .portable import package
        print(package(args.destination, store, model=config['model']))
        return
    from .pipeline import Pipeline
    pipeline = Pipeline(config, store, suite=args.suite, run_id=args.run_id, resume=args.resume)
    if args.command == 'pipeline':
        print(pipeline.run(execute=args.execute))
        return
    with exclusive_run(pipeline.root):
        pipeline.initialize()
        if args.command == 'lock':
            pipeline.lock()
            from .reports import summarize
            summarize(pipeline.root, stage='development')
            print(pipeline.root / 'selection.lock.json')
        elif args.command == 'run':
            if not args.stage:
                parser.error('run requires --stage development|test')
            if args.stage == 'development':
                pipeline.run_development(execute=args.execute)
            else:
                pipeline.run_test(execute=args.execute, lock_path=args.lock)
                from .reports import summarize
                summarize(pipeline.root, stage='test')
            print(pipeline.root)


if __name__ == '__main__':
    main()
