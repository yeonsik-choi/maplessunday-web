#!/usr/bin/env bash
# 끝 N스텝만 verbose 백테스트 (기본 13스텝, iterations 80). 숫자 바꾸려면 export 후 실행.
set -euo pipefail
cd "$(dirname "$0")"
export SUNDAY_WF_LAST_N="${SUNDAY_WF_LAST_N:-13}"
export SUNDAY_CATBOOST_ITERATIONS="${SUNDAY_CATBOOST_ITERATIONS:-80}"
exec .venv/bin/python sunday_predictor.py backtest --verbose
