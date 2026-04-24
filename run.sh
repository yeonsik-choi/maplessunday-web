#!/usr/bin/env bash
# 썬데이 예측기 공용 진입점 (팀 확인용). sunday/.venv 권장.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/sunday"

PY=".venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "⚠️  .venv 없음 → 시스템 python3 사용. 'python3 -m venv .venv && .venv/bin/pip install -r requirements.txt' 권장" >&2
  PY="python3"
fi

usage() {
  sed 's/^    //' <<'EOF'
    사용법: ./run.sh <명령> [추가 인자…]

    predict          다음 썬데이 예측 (Supabase 등 기본 동작)
    predict-dry      predict --dry-run (supabase 저장안됨. 예측만 확인용)
    backtest         워크포워드 백테 (+메타 저장)
    backtest-verbose 백테 + 주별 로그
    backtest-sample  짧은 샘플 백테 (SUNDAY_WF_LAST_N·iterations 기본값, run_backtest_sample.sh와 동일 취지)
    last12           최근 12주 표 (날짜·Top-3·실제·Hit·confidence)

    환경변수 예: SUNDAY_CATBOOST_ITERATIONS, SUNDAY_WF_LAST_N, SUNDAY_PREDICT_TOP_K
    add는 CSV/인자 형식이 있어 CLI 직접: cd sunday && .venv/bin/python sunday_predictor.py add …
EOF
}

cmd="${1:-}"
shift || true

case "$cmd" in
  predict)
    exec "$PY" sunday_predictor.py predict "$@"
    ;;
  predict-dry)
    exec "$PY" sunday_predictor.py predict --dry-run "$@"
    ;;
  backtest)
    exec "$PY" sunday_predictor.py backtest "$@"
    ;;
  backtest-verbose)
    exec "$PY" sunday_predictor.py backtest --verbose "$@"
    ;;
  backtest-sample)
    export SUNDAY_WF_LAST_N="${SUNDAY_WF_LAST_N:-13}"
    export SUNDAY_CATBOOST_ITERATIONS="${SUNDAY_CATBOOST_ITERATIONS:-80}"
    exec "$PY" sunday_predictor.py backtest --verbose "$@"
    ;;
  last12)
    exec "$PY" sunday_predictor.py last12 "$@"
    ;;
  "" | -h | --help)
    usage
    ;;
  *)
    echo "알 수 없는 명령: $cmd" >&2
    usage >&2
    exit 1
    ;;
esac
