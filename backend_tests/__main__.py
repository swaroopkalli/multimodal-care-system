import argparse
import logging
import sys

from . import framework
from . import (t01_connectivity, t02_ingestion, t03_ewma_live, t04_history_anomaly, t05_graph_rag,  # noqa: F401
               t06_guardrails, t07_context_budget, t08_auth_isolation, t09_end_to_end)


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m backend_tests", description=__doc__)
    parser.add_argument("--only", help="run areas whose title contains this text (e.g. 7 or guard)")
    parser.add_argument("--strict", action="store_true", help="treat unavailable services as FAIL, not SKIP")
    parser.add_argument("--list", action="store_true", help="list checks and exit")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)            # keep the report readable; failures print their own details

    selected = framework.REGISTRY
    if args.only:
        selected = [c for c in selected if args.only.lower() in c.area.lower()]
    if args.list:
        for c in selected:
            print(f"{c.area}: {c.name}  [needs: {', '.join(c.needs) or '-'}]")
        return 0
    if not selected:
        print("no checks matched")
        return 2

    print("MindBridge backend verification (synthetic data only; fixtures are removed afterwards)")
    try:
        if framework.probe("postgres")[0]:
            framework.cleanup_marked()           # leftovers from an interrupted earlier run
    except Exception as exc:
        print(f"  ! could not clean leftovers: {exc}")
    code = framework.run_checks(selected, strict=args.strict)
    try:
        if framework.probe("postgres")[0]:
            framework.cleanup_marked()
    except Exception:
        pass
    return code


if __name__ == "__main__":
    sys.exit(main())
