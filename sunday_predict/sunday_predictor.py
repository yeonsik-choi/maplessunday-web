"""썬데이 예측 CLI: predict | backtest | add (CatBoost 체인 + 워크포워드).

코드 읽는 순서(흐름):
  · 데이터: load_data → add_category_labels → build_features (features.py) → 주별 dict + y_*
  · 모델: pick_active_cats로 학습 가능한 cat만 → CatBoostMultiLabelChain(cats 순 이진, 앞 단계
    확률/라벨을 X에 이어 붙임) → train_chain / predict_proba_batch(선택 Platt)
  · 학습: 검증 꼬리 Platt → 전 구간 재학습(train_and_calibrate). predict 유력은 확률 Top-K(백테 Top-3와 동일 스케일)
  · predict: 체인+Platt → 카테고리별 α shrink(marginal) → reliability·확률표·prior·gap
    (--dry-run 시 predictions만 미저장)
  · backtest: Top-3·gap·BSS·logloss·per_category (워크포워드에서도 predict와 동일 α shrink)

환경변수: SUNDAY_TRAIN_RECENT_WEEKS, SUNDAY_WF_MIN_TRAIN(45), SUNDAY_WF_MAX_STEPS(0=전체),
  SUNDAY_CATBOOST_ITERATIONS(100), SUNDAY_META_PATH, SUNDAY_WF_LAST_N(0=전 구간 평가),
  SUNDAY_SPW_MAX(2) — CatBoost scale_pos_weight 상한 min(SPW_MAX, neg/pos).
  데이터: sunday_15tags.csv."""
import csv
import json
import math
import os
import sys
from datetime import datetime, timedelta

# features.py: ALL_CATEGORIES, FEATURE_COLS, PREV_GROUP_* 등 피처 정의. 여기선 아래만 import.
from features import (
    MAIN_CATS,
    add_category_labels,
    build_features,
    build_next_features,
    matrix_from_rows,
)

import numpy as np

# =============================================================================
# 0) 경로·환경 — SCRIPT_DIR, DATA/META, TRAIN_RECENT_WEEKS, WF_*, catboost_iterations
# =============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(SCRIPT_DIR, ".env"))
except ImportError:
    pass  # dotenv 없어도 환경변수 직접 지정하면 동작
DATA_PATH = os.path.join(SCRIPT_DIR, "sunday_15tags.csv")
META_PATH = os.path.join(SCRIPT_DIR, "sunday_predict_meta.json")
_meta_override = os.environ.get("SUNDAY_META_PATH", "").strip()
if _meta_override:
    META_PATH = (
        _meta_override
        if os.path.isabs(_meta_override)
        else os.path.join(SCRIPT_DIR, _meta_override)
    )

TRAIN_RECENT_WEEKS = int(os.environ.get("SUNDAY_TRAIN_RECENT_WEEKS", "0"))
WF_MIN_TRAIN = int(os.environ.get("SUNDAY_WF_MIN_TRAIN", "45"))
WF_MAX_STEPS = int(os.environ.get("SUNDAY_WF_MAX_STEPS", "0"))
WF_LAST_N = int(os.environ.get("SUNDAY_WF_LAST_N", "0"))  # >0이면 끝에서 N스텝만 평가(t만 밀고 학습은 여전히 tr[0:t])
# CatBoost scale_pos_weight 상한: min(SPW_MAX, neg/pos) (ablation.py 독립모델과 별개)
SPW_MAX = max(1, int(os.environ.get("SUNDAY_SPW_MAX", "2")))


def catboost_iterations() -> int:
    """CatBoost 트리 개수 (SUNDAY_CATBOOST_ITERATIONS, 기본 100)."""
    return max(1, int(os.environ.get("SUNDAY_CATBOOST_ITERATIONS", "100")))


# =============================================================================
# 1) Supabase — add/predict 시 선택적 upsert (환경변수 없으면 스킵)
# =============================================================================

def _get_supabase():
    """SUPABASE_* 환경변수 있으면 클라이언트, 없거나 실패 시 None."""
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    if not url or not key:
        return None
    try:
        from supabase import create_client

        return create_client(url, key)
    except Exception as e:
        print(f"  (Supabase 연결 실패, 무시: {e})")
        return None


def push_sunday_to_supabase(date_str: str, event: str, tag_row: dict):
    """add 후 ssunday 테이블 upsert."""
    sb = _get_supabase()
    if sb is None:
        return
    try:
        payload = {"date": date_str, "event": event}
        for k, v in tag_row.items():
            payload[k] = int(v)
        sb.table("ssunday").upsert(payload).execute()
        print("  → Supabase ssunday 반영 완료")
    except Exception as e:
        print(f"  (Supabase ssunday 실패, 무시: {e})")


def push_prediction_to_supabase(target_date, preds, picked, week_confidence=None):
    """predict 후 predictions upsert. week_confidence는 jsonb 컬럼이 있을 때만 페이로드에 포함.

    threshold: 일부 DB 스키마가 NOT NULL이라 유지. 앱 로직은 Top-K만 사용(값은 placeholder).
    """
    sb = _get_supabase()
    if sb is None:
        return
    payload = {
        "target_date": target_date.strftime("%Y-%m-%d"),
        "probs": {k: round(float(v), 4) for k, v in preds.items()},
        "picked_cats": list(picked),
        # 레거시 스키마 NOT NULL 대응 (실제 의사결정에는 미사용)
        "threshold": float(os.environ.get("SUNDAY_SUPABASE_THRESHOLD_PLACEHOLDER", "0")),
    }
    if week_confidence is not None:
        payload["week_confidence"] = week_confidence

    def _upsert_predictions(pl: dict) -> None:
        sb.table("predictions").upsert(pl, on_conflict="target_date").execute()

    try:
        _upsert_predictions(payload)
        print("  → Supabase predictions 반영 완료")
    except Exception as e:
        err_s = str(e).lower()
        if "week_confidence" in payload and (
            "week_confidence" in err_s or "pgrst204" in err_s
        ):
            pl2 = {k: v for k, v in payload.items() if k != "week_confidence"}
            try:
                _upsert_predictions(pl2)
                print(
                    "  → Supabase predictions 반영 완료 "
                    "(week_confidence 컬럼 없음 → probs·picked만 저장)"
                )
            except Exception as e2:
                print(f"  (Supabase predictions 실패, 무시: {e2})")
        else:
            print(f"  (Supabase predictions 실패, 무시: {e})")


# =============================================================================
# 2) 검증 꼬리·predict Top-K — Platt용 VAL_HOLDOUT, 유력 후보 개수 PREDICT_TOP_K
# =============================================================================

VAL_HOLDOUT = 20
PREDICT_TOP_K = int(os.environ.get("SUNDAY_PREDICT_TOP_K", "3"))

# =============================================================================
# 3) 데이터 — CSV 로드, active cat 선별, Y 행렬(labels_matrix)
# =============================================================================

def load_data():
    """sunday_15tags.csv 읽기. 각 행에 _dt(일요일 datetime) 부여."""
    rows = []
    with open(DATA_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        raw_fn = list(reader.fieldnames or [])
        fieldnames = [c.strip().strip("\ufeff") for c in raw_fn]
        for row in reader:
            cleaned = {k.strip().strip("\ufeff"): v for k, v in row.items()}
            raw = cleaned.get("date", "").replace("(월)", "").strip()
            try:
                cleaned["_dt"] = datetime.strptime(raw, "%Y.%m.%d")
            except ValueError:
                continue
            rows.append(cleaned)
    return rows, fieldnames


def active_cats_in_train_rows(train_rows):
    """학습 행에서 cat_* 양성이 한 번이라도 있는 카테고리만."""
    active = []
    for c in MAIN_CATS:
        s = sum(int(r[f"cat_{c}"]) for r in train_rows)
        if s > 0:
            active.append(c)
    return active


def pick_active_cats(train_rows):
    """체인에 넣을 cat 목록. 전부 0이면 MAIN_CATS로 폴백."""
    # 라벨이 전부 0인 카테고리는 제외
    ac = active_cats_in_train_rows(train_rows)
    return ac if ac else list(MAIN_CATS)


def _row_binary_label(row: dict, cat: str) -> int:
    """주·카테고리 양성 라벨. 피처 행은 y_* , 원본 CSV 행(백테 마진용)은 cat_*."""
    yk = f"y_{cat}"
    if yk in row:
        return int(row[yk])
    ck = f"cat_{cat}"
    if ck in row:
        return int(row[ck])
    return 0


def labels_matrix(rows, cats):
    """cats 순서대로 열 = 이진 라벨 y (행=주)."""
    return np.column_stack(
        [np.array([_row_binary_label(r, c) for r in rows], dtype=np.int32) for c in cats]
    )


# =============================================================================
# 4) 모델 — train_chain, predict_proba_batch, CatBoostMultiLabelChain.raw_proba_matrix
# =============================================================================

class CatBoostMultiLabelChain:
    """cats 순 이진 분류기 나열. 각 단계 후 X에 해당 cat 라벨(학습 시) 또는 확률(추론 시) concat."""

    def __init__(self, cats):
        """cats: 체인 순서 (= 학습·추론 헤드 순서)."""
        self.cats = list(cats)
        self.models_ = []

    def fit(self, X, Y):
        """X에 대해 순서대로 학습; 희소 라벨 cat은 None(추론 시 0.05 고정)."""
        from catboost import CatBoostClassifier

        self.models_ = []
        X_curr = np.asarray(X, dtype=object)
        n = X_curr.shape[0]
        for i in range(len(self.cats)):
            y = Y[:, i].astype(np.float64)
            pos = int(y.sum())
            neg = n - pos
            if pos < 3:
                self.models_.append(None)
            else:
                m = CatBoostClassifier(
                    iterations=catboost_iterations(),
                    depth=3,
                    learning_rate=0.03,
                    l2_leaf_reg=10,
                    scale_pos_weight=min(SPW_MAX, neg / max(1, pos)),
                    random_seed=42,
                    verbose=0,
                    allow_writing_files=False,
                )
                m.fit(X_curr, y)
                self.models_.append(m)
            X_curr = np.hstack([X_curr, Y[:, i].reshape(-1, 1)])
        return self

    def raw_proba_matrix(self, X):
        """행×cat 확률 행렬 (체인 순서대로 순전파)."""
        X_curr = np.asarray(X, dtype=object)
        n = X_curr.shape[0]
        k = len(self.cats)
        P = np.zeros((n, k), dtype=np.float64)
        for i, m in enumerate(self.models_):
            if m is None:
                pr = np.full((n,), 0.05, dtype=np.float64)
                P[:, i] = pr
                aug = pr.reshape(-1, 1)
            else:
                pr = m.predict_proba(X_curr)[:, 1].astype(np.float64)
                P[:, i] = pr
                aug = pr.reshape(-1, 1)
            X_curr = np.hstack([X_curr, aug])
        return P


def train_chain(rows, cats):
    """피처 dict 행들로 X,Y 만들어 체인 학습."""
    if not rows:
        return None
    X = matrix_from_rows(rows)
    Y = labels_matrix(rows, cats)
    return CatBoostMultiLabelChain(cats).fit(X, Y)


# =============================================================================
# 5) 임계값·지표 — 「모델 평가」 핵심 유틸 (검증 꼬리·워크포워드에서 재사용)
#     predict_proba_batch: raw; calibrators 넘기면 Platt(검증 꼬리에서 학습)
# =============================================================================

def predict_proba_batch(chain, X, cats, calibrators=None):
    """각 샘플마다 cat→P(양성) dict 리스트. calibrators 있고 일부가 비-None이면 Platt 적용."""
    if chain is None:
        return [{c: 0.05 for c in cats} for _ in range(len(X))]
    cal = calibrators or []
    if not cal or all(c is None for c in cal):
        P = chain.raw_proba_matrix(X)
        out = []
        for i in range(P.shape[0]):
            d = {cats[j]: float(P[i, j]) for j in range(len(cats))}
            out.append(d)
        return out
    P = chain.raw_proba_matrix(np.asarray(X, dtype=object))
    P2 = apply_platt_matrix(P, cal)
    return [{cats[j]: float(P2[i, j]) for j in range(len(cats))} for i in range(P2.shape[0])]


def fit_platt_calibrators(chain, X_val, val_rows, cats):
    """검증 구간 raw 확률·라벨로 카테고리별 Platt(로지스틱 on logit(p)). scikit-learn 없거나 표본 부족 시 None."""
    k = len(cats)
    if chain is None or k == 0:
        return [None] * k
    try:
        from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
    except ImportError:
        print("  (경고: scikit-learn 없음 → Platt 보정 생략, raw 확률 사용)", flush=True)
        return [None] * k
    P = chain.raw_proba_matrix(np.asarray(X_val, dtype=object))
    Y = labels_matrix(val_rows, cats)
    n = P.shape[0]
    if n < 10:
        return [None] * k
    eps = 1e-6
    min_each_class = 5
    out: list = []
    for j in range(k):
        if j < len(chain.models_) and chain.models_[j] is None:
            out.append(None)
            continue
        y = Y[:, j].astype(np.int32)
        pos, neg = int(y.sum()), n - int(y.sum())
        if pos < min_each_class or neg < min_each_class:
            out.append(None)
            continue
        z = np.clip(P[:, j].astype(np.float64), eps, 1.0 - eps)
        Xl = np.log(z / (1.0 - z)).reshape(-1, 1)
        lr = LogisticRegression(C=1e12, solver="lbfgs", random_state=42, max_iter=500)
        lr.fit(Xl, y)
        out.append(lr)
    return out


def apply_platt_matrix(P: np.ndarray, calibrators: list) -> np.ndarray:
    """열 j에 calibrators[j] 적용. None이면 해당 열 raw 유지."""
    out = np.array(P, dtype=np.float64, copy=True)
    eps = 1e-6
    for j, cal in enumerate(calibrators):
        if j >= out.shape[1] or cal is None:
            continue
        z = np.clip(out[:, j], eps, 1.0 - eps)
        Xl = np.log(z / (1.0 - z)).reshape(-1, 1)
        out[:, j] = cal.predict_proba(Xl)[:, 1].astype(np.float64)
    return out


def week_confidence_gap(preds: dict, cats: list[str]) -> dict:
    """주간 애매함: 1위와 2위 확률 차(gap). 작을수록 상위 두 후보가 붙어 있음. active 1개면 score null."""
    if not cats:
        return {"mode": "gap", "score": None, "hint": "active 카테고리 없음"}
    probs = [max(0.0, float(preds.get(c, 0.0))) for c in cats]
    desc = sorted(probs, reverse=True)
    n = len(desc)
    if n < 2:
        return {
            "mode": "gap",
            "score": None,
            "hint": "active 1개라 1·2위 차 없음",
        }
    g = desc[0] - desc[1]
    return {
        "mode": "gap",
        "score": round(float(g), 4),
        "hint": "작을수록 1·2위 근접(애매)",
    }


def _val_reliability_bins(
    chain,
    val_rows: list[dict],
    cats: list[str],
    X_val,
    calibrators: list | None,
    *,
    n_bins: int = 10,
    min_pairs: int = 30,
) -> list[dict] | None:
    """검증 꼬리·보정 후 (p,y) 풀을 확률 구간으로 나눠 평균 p vs 실제 양성률(reliability)."""
    if chain is None or not val_rows or not cats:
        return None
    batch = predict_proba_batch(chain, X_val, cats, calibrators or [])
    pairs: list[tuple[float, int]] = []
    for i, pr in enumerate(batch):
        for c in cats:
            if c not in pr:
                continue
            pairs.append((float(pr[c]), _row_binary_label(val_rows[i], c)))
    if len(pairs) < min_pairs:
        return None
    ps = np.array([p for p, _ in pairs], dtype=np.float64)
    ys = np.array([y for _, y in pairs], dtype=np.int64)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    out: list[dict] = []
    for b in range(n_bins):
        lo, hi = float(edges[b]), float(edges[b + 1])
        if b == n_bins - 1:
            mask = (ps >= lo) & (ps <= hi)
        else:
            mask = (ps >= lo) & (ps < hi)
        n = int(mask.sum())
        if n == 0:
            continue
        mp = float(ps[mask].mean())
        obs = float(ys[mask].mean())
        out.append(
            {
                "p_lo": round(lo, 3),
                "p_hi": round(hi, 3),
                "n": n,
                "mean_predicted": round(mp, 4),
                "observed_positive_rate": round(obs, 4),
            }
        )
    return out


def _mean_brier_step(pr: dict, row: dict, cats: list[str]) -> float:
    """active 헤드에 대한 스텝 Brier (p−y)² 평균. 모델 내부 진단용으로만 사용."""
    if not cats:
        return 0.0
    s = 0.0
    for c in cats:
        p = float(pr[c])
        y = _row_binary_label(row, c)
        s += (p - y) ** 2
    return s / len(cats)


# 베이스라인 고정 확률(체인 None 헤드와 동일 스케일)
_BASELINE_CONST_P = 0.05

# Platt 보정 후 → 학습구간 marginal로 shrink: p' = α·p + (1−α)·marginal (per_category BSS 기준 수동 α)
SHRINKAGE_ALPHA: dict[str, float] = {
    "사냥": 0.4,
    "샤이닝": 0.9,
    "미라클": 0.7,
    "몬컬": 0.8,
    "소울": 0.9,
    "헥사": 0.9,
    "어빌리티": 0.9,
    "주흔반값": 0.9,
    "몬스터파크": 0.7,
}
assert set(SHRINKAGE_ALPHA) == set(MAIN_CATS), "SHRINKAGE_ALPHA 키는 MAIN_CATS와 일치해야 함"


def _binary_logloss(p: float, y: int, eps: float = 1e-15) -> float:
    pc = min(1.0 - eps, max(eps, float(p)))
    if y == 1:
        return -math.log(pc)
    return -math.log(1.0 - pc)


def _mean_logloss_step(pr: dict, row: dict, cats: list[str]) -> float:
    """active 헤드에 대한 평균 이진 로그손실."""
    if not cats:
        return 0.0
    return sum(_binary_logloss(float(pr[c]), _row_binary_label(row, c)) for c in cats) / len(cats)


def _bss(mean_model: float, mean_baseline: float) -> float | None:
    """Brier skill score: 1 − mean_model / mean_baseline. 베이스라인 분산이 0이면 None."""
    if mean_baseline <= 1e-20:
        return None
    return 1.0 - mean_model / mean_baseline


def _round_opt(x: float | None, nd: int = 6) -> float | None:
    if x is None:
        return None
    return round(float(x), nd)


def _fmt_bss_console(v: float | None) -> str:
    return f"{v:+.4f}" if v is not None else "N/A"


def _pr_baseline_marginal(rows_hist: list[dict], active_cats: list[str]) -> dict[str, float]:
    """과거 학습 행만으로 각 active cat의 양성 비율을 확률로 사용."""
    if not active_cats:
        return {}
    if not rows_hist:
        return {c: float(_BASELINE_CONST_P) for c in active_cats}
    n = len(rows_hist)
    return {c: float(sum(_row_binary_label(r, c) for r in rows_hist) / n) for c in active_cats}


def _wf_step_metrics(
    pr: dict[str, float],
    next_row: dict,
    active_cats: list[str],
    *,
    record_gap: bool,
) -> tuple[int, int, float, dict | None]:
    """한 스텝 Top-3 적중·active Brier(진단). record_gap이면 gap 분위용 dict 반환."""
    k_top = min(3, len(active_cats))
    actual_keys = {c for c in active_cats if _row_binary_label(next_row, c) == 1}
    topk_keys = (
        sorted(active_cats, key=lambda c: float(pr[c]), reverse=True)[:k_top] if k_top else []
    )
    topk_hits = len(set(topk_keys) & actual_keys)
    br = _mean_brier_step(pr, next_row, active_cats)
    rec = None
    if record_gap:
        gap_sc = week_confidence_gap(pr, active_cats).get("score")
        rec = {"gap": gap_sc, "topk_hits": topk_hits, "k_top": k_top}
    return topk_hits, k_top, br, rec


def _baseline_probs(rows_hist: list[dict], active_cats: list[str]) -> dict[str, dict[str, float]]:
    """베이스라인 3종: 고정 prior, active 균등, 학습구간 마진(양성률)."""
    p0 = float(_BASELINE_CONST_P)
    const = {c: p0 for c in active_cats}
    if not active_cats:
        uni: dict[str, float] = {}
    else:
        u = 1.0 / len(active_cats)
        uni = {c: u for c in active_cats}
    return {
        "constant_0.05": const,
        "uniform_active": uni,
        "train_marginal": _pr_baseline_marginal(rows_hist, active_cats),
    }


def _shrink_probs_to_marginal(
    preds: dict[str, float],
    rows_hist: list[dict],
    active_cats: list[str],
) -> dict[str, float]:
    """p' = α_c·p + (1−α_c)·marginal_c. α는 SHRINKAGE_ALPHA 고정값, marginal은 rows_hist 기준."""
    if not active_cats:
        return dict(preds)
    mar = _pr_baseline_marginal(rows_hist, active_cats)
    out = dict(preds)
    for c in active_cats:
        if c not in out:
            continue
        a = min(1.0, max(0.0, float(SHRINKAGE_ALPHA[c])))
        m = float(mar.get(c, _BASELINE_CONST_P))
        p = float(out[c])
        out[c] = a * p + (1.0 - a) * m
    return out


def _serialize_predict_baselines(
    baselines: dict[str, dict[str, float]],
    preds: dict[str, float],
    active_cats: list[str],
    *,
    n_hist_weeks: int,
) -> dict:
    """메타 predict_baselines: 백테 베이스라인과 동일 정의 + 보정 후 모델 확률."""
    by_cat: dict[str, dict] = {}
    for c in active_cats:
        by_cat[c] = {
            "train_marginal": round(float(baselines["train_marginal"][c]), 4),
            "uniform_active": round(float(baselines["uniform_active"][c]), 4),
            "constant_0_05": round(float(baselines["constant_0.05"][c]), 4),
            "model_calibrated": round(float(preds[c]), 4),
        }
    return {
        "definition": "백테 워크포워드와 동일(_baseline_probs)",
        "hist_weeks_for_marginal": n_hist_weeks,
        "by_category": by_cat,
    }


def _print_predict_baseline_prior_table(
    baselines: dict[str, dict[str, float]],
    preds: dict[str, float],
    active_cats: list[str],
    *,
    n_hist_weeks: int,
) -> None:
    """predict 콘솔: 카테고리별 marginal / uniform / const / 모델(보정 후)."""
    if not active_cats:
        return
    print(f"\n  [베이스라인 prior] 백테와 동일 (학습 행 {n_hist_weeks}주로 마진 산출)")
    hdr = f"  {'cat':<14} {'marginal':>9} {'uniform':>9} {'0.05':>7} {'model':>7}"
    print(hdr)
    print(f"  {'─'*54}")
    for cat in sorted(active_cats, key=lambda c: float(preds[c]), reverse=True):
        mar = baselines["train_marginal"][cat]
        uni = baselines["uniform_active"][cat]
        con = baselines["constant_0.05"][cat]
        pm = preds[cat]
        print(f"  {cat:<14} {mar:>8.1%} {uni:>8.1%} {con:>6.1%} {pm:>6.1%}")


def _empty_cat_step_acc() -> dict[str, float]:
    return {
        "n": 0,
        "sum_bm": 0.0,
        "sum_bmar": 0.0,
        "sum_buni": 0.0,
        "sum_bcon": 0.0,
        "sum_llm": 0.0,
        "sum_llmar": 0.0,
        "sum_lluni": 0.0,
        "sum_llcon": 0.0,
    }


def _accumulate_per_category(
    cat_acc: dict[str, dict[str, float]],
    active_cats: list[str],
    next_row: dict,
    pr_model: dict[str, float],
    baselines: dict[str, dict[str, float]],
) -> None:
    """active인 스텝에서만 카테고리별 Brier·logloss 합산."""
    pb_mar = baselines["train_marginal"]
    pb_uni = baselines["uniform_active"]
    pb_con = baselines["constant_0.05"]
    for c in active_cats:
        y = _row_binary_label(next_row, c)
        pm = float(pr_model[c])
        a = cat_acc[c]
        a["n"] += 1
        a["sum_bm"] += (pm - y) ** 2
        a["sum_bmar"] += (float(pb_mar[c]) - y) ** 2
        a["sum_buni"] += (float(pb_uni[c]) - y) ** 2
        a["sum_bcon"] += (float(pb_con[c]) - y) ** 2
        a["sum_llm"] += _binary_logloss(pm, y)
        a["sum_llmar"] += _binary_logloss(float(pb_mar[c]), y)
        a["sum_lluni"] += _binary_logloss(float(pb_uni[c]), y)
        a["sum_llcon"] += _binary_logloss(float(pb_con[c]), y)


def _per_category_eval_blocks(cat_acc: dict[str, dict[str, float]]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for cat in MAIN_CATS:
        a = cat_acc[cat]
        n = int(a["n"])
        if n == 0:
            continue
        mb = a["sum_bm"] / n
        mmar = a["sum_bmar"] / n
        muni = a["sum_buni"] / n
        mcon = a["sum_bcon"] / n
        out[cat] = {
            "n_eval": n,
            "mean_brier_model": round(mb, 6),
            "mean_brier_train_marginal": round(mmar, 6),
            "mean_brier_uniform_active": round(muni, 6),
            "mean_brier_constant_0_05": round(mcon, 6),
            "BSS_vs_train_marginal": _round_opt(_bss(mb, mmar)),
            "BSS_vs_uniform_active": _round_opt(_bss(mb, muni)),
            "BSS_vs_constant_0_05": _round_opt(_bss(mb, mcon)),
            "mean_logloss_model": round(a["sum_llm"] / n, 6),
            "mean_logloss_train_marginal": round(a["sum_llmar"] / n, 6),
            "mean_logloss_uniform_active": round(a["sum_lluni"] / n, 6),
            "mean_logloss_constant_0_05": round(a["sum_llcon"] / n, 6),
        }
    return out


def _top3_eval_block(*, steps: int, hits: int, slots: int) -> dict:
    return {
        "steps": steps,
        "hits": hits,
        "slots": slots,
        "slot_hit_rate": round(hits / slots, 4) if slots else None,
        "mean_hits_per_step": round(hits / steps, 4) if steps else None,
    }


def _bucket_top3_by_gap(records: list[dict]) -> tuple[dict[str, dict], dict | None]:
    """records: gap(None|float), topk_hits, k_top. gap 낮을수록 애매 → 3분위별 Top-3. (구간 dict, q1/q2)."""
    out: dict[str, dict] = {}
    if not records:
        return out, None
    scored = [r for r in records if r["gap"] is not None]
    if not scored:
        return out, None
    arr = np.array([float(r["gap"]) for r in scored], dtype=np.float64)
    g1, g2 = np.quantile(arr, [1.0 / 3.0, 2.0 / 3.0])
    bins: dict[str, list[dict]] = {"gap_low_ambiguous": [], "gap_mid": [], "gap_high_clear": []}
    for r in scored:
        g = float(r["gap"])
        if g <= g1:
            bins["gap_low_ambiguous"].append(r)
        elif g <= g2:
            bins["gap_mid"].append(r)
        else:
            bins["gap_high_clear"].append(r)
    for name, sub in bins.items():
        if not sub:
            continue
        h, sl = sum(x["topk_hits"] for x in sub), sum(x["k_top"] for x in sub)
        out[name] = _top3_eval_block(steps=len(sub), hits=h, slots=sl)
    cut = {"q1": round(float(g1), 4), "q2": round(float(g2), 4)}
    return out, cut


# =============================================================================
# 6) 예측 일요일·학습 슬라이스 — resolve_prediction_sunday, slice_train_features, write_meta
# =============================================================================

def _calendar_next_sunday(from_day: datetime) -> datetime:
    """from_day 이후 첫 일요일(당일이 일요일이면 다음 주 일요일)."""
    d0 = from_day.replace(hour=0, minute=0, second=0, microsecond=0)
    dow = d0.weekday()
    days_ahead = (6 - dow) % 7
    if days_ahead == 0:
        days_ahead = 7
    return d0 + timedelta(days=days_ahead)


def resolve_prediction_sunday(last_row_dt: datetime):
    """예측 대상 일요일 datetime과, CSV 다음 주 vs 캘린더 근거 문자열."""
    last0 = last_row_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    from_csv = last0 + timedelta(days=7)
    today0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if from_csv >= today0:
        return from_csv, "마지막 데이터 다음 일요일"
    return _calendar_next_sunday(today0), "캘린더 다음 일요일"


def slice_train_features(features):
    """TRAIN_RECENT_WEEKS>0이면 피처 꼬리 N주만 학습에 사용."""
    if TRAIN_RECENT_WEEKS > 0:
        return features[-TRAIN_RECENT_WEEKS:]
    return features


def write_meta(meta: dict, path=None):
    """메타 JSON을 META_PATH(또는 path)에 기록."""
    target = path or META_PATH
    try:
        with open(target, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"에러: {e}")


def merge_predict_meta_week_confidence(
    wc: dict,
    target_date_iso: str,
    *,
    predict_baselines: dict | None = None,
) -> None:
    """학습 META_PATH에 주간 confidence·(선택) predict 베이스라인 prior 병합."""
    meta: dict = {}
    if os.path.isfile(META_PATH):
        try:
            with open(META_PATH, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            meta = {}
    meta.pop("week_confidence_raw_gap", None)
    meta.pop("predict_prob_raw_vs_cal", None)
    meta.pop("best_threshold", None)
    meta["week_confidence"] = wc
    meta["week_confidence_target_date"] = target_date_iso
    if predict_baselines is not None:
        meta["predict_baselines"] = predict_baselines
    write_meta(meta)


# =============================================================================
# 7) 운영 학습 — VAL_HOLDOUT주로 Platt → 전 구간 재학습 후 배포용 Platt 재적합
# =============================================================================

def train_and_calibrate(features, cats, *, persist_meta: bool):
    """검증 꼬리에서 Platt 보정 → 전 구간 체인 재학습 후 동일 검증으로 배포용 Platt 재적합.

    반환 (chain, cal_deploy, val_reliability_bins | None) — 마지막은 검증 꼬리 reliability(보정 후).
    """
    tr = slice_train_features(features)
    if len(tr) <= VAL_HOLDOUT + 10:
        chain = train_chain(tr, cats)
        if persist_meta:
            write_meta(
                {
                    "predict_top_k": PREDICT_TOP_K,
                    "note": "데이터 부족으로 Platt 미적합",
                    "catboost_iterations": catboost_iterations(),
                    "probability_calibration": "none",
                }
            )
        return chain, None, None
    train_core = tr[:-VAL_HOLDOUT]
    val = tr[-VAL_HOLDOUT:]
    chain_cv = train_chain(train_core, cats)
    X_val = matrix_from_rows(val)
    cal_cv = fit_platt_calibrators(chain_cv, X_val, val, cats)
    final_chain = train_chain(tr, cats)
    cal_deploy = fit_platt_calibrators(final_chain, X_val, val, cats)
    rel = _val_reliability_bins(final_chain, val, cats, X_val, cal_deploy)
    meta = {
        "predict_top_k": PREDICT_TOP_K,
        "catboost_iterations": catboost_iterations(),
        "probability_calibration": "platt_sigmoid",
        "platt_fitted_heads": sum(1 for c in cal_deploy if c is not None),
    }
    if rel is not None:
        meta["val_reliability_bins"] = rel
    if persist_meta:
        write_meta(meta)
    return final_chain, cal_deploy, rel


# =============================================================================
# 8) CLI — predict | backtest | add 및 __main__ 분기
# =============================================================================

def cmd_predict(*, dry_run: bool = False):
    """학습 후 다음 일요일 확률 출력. dry_run이면 Supabase predictions만 생략."""
    rows, _ = load_data()
    rows = add_category_labels(rows)
    features = build_features(rows, MAIN_CATS)
    tr_feat = slice_train_features(features)
    off = len(rows) - len(tr_feat)
    active_cats = pick_active_cats(rows[off:])

    print("모델 학습 중...", flush=True)
    chain, cal, val_rel = train_and_calibrate(features, active_cats, persist_meta=True)
    if cal and any(c is not None for c in cal):
        print("  확률 출력·저장: 검증 구간 Platt(sigmoid) 보정 적용", flush=True)
    if val_rel:
        print("\n  [보정 품질] 검증 꼬리 reliability (구간별 평균 p vs 실제 양성률, 보정 후)")
        for row in val_rel:
            if row["n"] < 3:
                continue
            print(
                f"    p∈[{row['p_lo']:.1f},{row['p_hi']:.1f})  n={row['n']:>3}  "
                f"평균p={row['mean_predicted']:.1%}  실제={row['observed_positive_rate']:.1%}"
            )
        print(
            "    → 두 값이 가까울수록 calibration 양호. 단일 주 '71%'와 구간 집계는 다름.",
            flush=True,
        )

    next_sunday, pred_reason = resolve_prediction_sunday(features[-1]["_dt"])
    nf = build_next_features(rows, MAIN_CATS, next_sunday)
    X = matrix_from_rows([nf])
    rows_hist = tr_feat
    preds = predict_proba_batch(chain, X, active_cats, cal)[0]
    preds = _shrink_probs_to_marginal(preds, rows_hist, active_cats)
    wc = week_confidence_gap(preds, active_cats)

    prev_cats = [c for c in active_cats if _row_binary_label(features[-1], c) == 1]
    k_pick = min(PREDICT_TOP_K, len(active_cats))
    picked = sorted(active_cats, key=lambda c: float(preds[c]), reverse=True)[:k_pick]
    picked_set = set(picked)

    baselines = _baseline_probs(rows_hist, active_cats)
    bl_meta = _serialize_predict_baselines(
        baselines, preds, active_cats, n_hist_weeks=len(rows_hist)
    )

    ds = next_sunday.strftime("%Y.%m.%d")
    merge_predict_meta_week_confidence(
        wc, next_sunday.strftime("%Y-%m-%d"), predict_baselines=bl_meta
    )
    print(f"\n{'='*70}\n다음 썬데이 예측 · 대상 일요일: {ds}\n{'='*70}")
    print(f"\n  CSV 마지막 주: {features[-1]['date']}")
    print(f"  예측 근거: {pred_reason}")
    if TRAIN_RECENT_WEEKS > 0:
        print(f"  학습 구간: 최근 {TRAIN_RECENT_WEEKS}주")
    print("  확률: Platt 보정 후 카테고리별 α·학습구간 marginal shrink 적용")
    print(f"  유력 후보 (확률 상위 Top-{k_pick}): {', '.join(picked) or '없음'}")
    print(f"  직전 데이터 주 실제 혜택: {', '.join(prev_cats) or '없음'}")
    sc = wc["score"]
    sc_s = f"{sc:.1%}" if isinstance(sc, (int, float)) else "N/A"
    print(f"  주간 confidence (Top1−Top2): {sc_s} — {wc['hint']}")

    print(f"\n  {'순위':>4} {'확률':>7}  {'카테고리'}")
    print(f"  {'─'*48}")

    if len(active_cats) < len(MAIN_CATS):
        hidden = [c for c in MAIN_CATS if c not in active_cats]
        print(f"  (학습 구간 미등장으로 제외: {', '.join(hidden)})")

    for i, (cat, prob) in enumerate(sorted(preds.items(), key=lambda x: -x[1]), 1):
        marker = "★" if cat in picked_set else " "
        print(f"  {i:>4} {prob:>6.1%} {marker} {cat}")

    _print_predict_baseline_prior_table(
        baselines, preds, active_cats, n_hist_weeks=len(rows_hist)
    )

    print(f"\n  {'─'*48}\n")
    if not dry_run:
        push_prediction_to_supabase(next_sunday, preds, picked, week_confidence=wc)
    else:
        print("  (--dry-run: Supabase predictions 미반영)", flush=True)


# 워크포워드 백테 — Top-3·Brier·gap·베이스라인 (cmd_backtest)

def run_walk_forward_backtest(*, verbose: bool, write_meta_file: bool):
    """워크포워드: Top-3·gap·BSS·(선택) logloss·per_category 집계·출력."""
    rows, _ = load_data()
    rows = add_category_labels(rows)
    features = build_features(rows, MAIN_CATS)
    tr = slice_train_features(features)
    off = len(rows) - len(tr)
    rows_tr = rows[off:]

    if len(tr) <= WF_MIN_TRAIN:
        print(
            f"데이터가 부족합니다 (워크포워드: 전체 {len(tr)}주, 필요 초기 학습 >{WF_MIN_TRAIN}주). "
            f"SUNDAY_WF_MIN_TRAIN으로 낮출 수 있음."
        )
        return None

    if WF_LAST_N > 0:
        t_start = max(WF_MIN_TRAIN, len(tr) - WF_LAST_N)
    else:
        t_start = WF_MIN_TRAIN

    t_end = len(tr)
    if WF_MAX_STEPS > 0:
        t_end = min(len(tr), t_start + WF_MAX_STEPS)
    n_planned = t_end - t_start
    cap_note = f", 평가 스텝 상한 {WF_MAX_STEPS}" if WF_MAX_STEPS > 0 else ""
    lastn_note = f", 끝에서 {WF_LAST_N}스텝만 평가" if WF_LAST_N > 0 else ""
    print(
        f"워크포워드 백테스트… (초기 학습 {WF_MIN_TRAIN}주, 스텝 {n_planned}회{cap_note}{lastn_note})",
        flush=True,
    )

    n_steps = 0
    tail_logs = []
    top3_hits_sum = 0
    top3_k_sum = 0
    brier_sum = 0.0
    ll_sum = 0.0
    eval_records: list[dict] = []
    cat_acc: dict[str, dict[str, float]] = {c: _empty_cat_step_acc() for c in MAIN_CATS}
    bl_accum = {
        "constant_0.05": {"brier": 0.0, "ll": 0.0},
        "uniform_active": {"brier": 0.0, "ll": 0.0},
        "train_marginal": {"hits": 0, "slots": 0, "brier": 0.0, "ll": 0.0},
    }

    # 모델 평가 루프: 매 스텝 검증 꼬리로 Platt → 그다음 한 주만 예측·Top-3·gap·BSS용 집계
    for t in range(t_start, t_end):
        # hist = 과거 주차 피처만 사용 (미래 누수 없음). next_row = 이번에 맞출 한 주.
        hist = tr[0:t]
        next_row = tr[t]
        rows_hist = rows_tr[0:t]
        active_cats = pick_active_cats(rows_hist)

        if len(hist) >= VAL_HOLDOUT + 15:
            val = hist[-VAL_HOLDOUT:]
            X_val = matrix_from_rows(val)
            chain = train_chain(hist, active_cats)
            cal_deploy = fit_platt_calibrators(chain, X_val, val, active_cats)
        else:
            chain = train_chain(hist, active_cats)
            cal_deploy = None

        baselines = _baseline_probs(rows_hist, active_cats)
        X_next = matrix_from_rows([next_row])
        pr = predict_proba_batch(chain, X_next, active_cats, cal_deploy)[0]
        pr = _shrink_probs_to_marginal(pr, rows_hist, active_cats)
        n_steps += 1

        h, k, br, rec = _wf_step_metrics(pr, next_row, active_cats, record_gap=True)
        top3_hits_sum += h
        top3_k_sum += k
        brier_sum += br
        ll_sum += _mean_logloss_step(pr, next_row, active_cats)
        eval_records.append(rec)
        _accumulate_per_category(cat_acc, active_cats, next_row, pr, baselines)

        for bname, pr_b in baselines.items():
            ba = bl_accum[bname]
            if bname == "train_marginal":
                hb, kb, brb, _ = _wf_step_metrics(pr_b, next_row, active_cats, record_gap=False)
                ba["hits"] += hb
                ba["slots"] += kb
                ba["brier"] += brb
            else:
                ba["brier"] += _mean_brier_step(pr_b, next_row, active_cats)
            ba["ll"] += _mean_logloss_step(pr_b, next_row, active_cats)

        if verbose:
            wc_step = week_confidence_gap(pr, active_cats)
            k_top = k
            topk_hits = h
            topk_keys = (
                sorted(active_cats, key=lambda c: float(pr[c]), reverse=True)[:k_top] if k_top else []
            )
            topk_display = list(topk_keys)
            tail_logs.append(
                (
                    next_row["date"],
                    topk_hits,
                    k_top,
                    topk_display,
                    wc_step,
                    br,
                )
            )

    if n_steps == 0:
        print("평가 스텝이 없습니다.", flush=True)
        return None

    mean_bm = brier_sum / n_steps
    mean_ll_m = ll_sum / n_steps
    mean_b_con = bl_accum["constant_0.05"]["brier"] / n_steps
    mean_b_uni = bl_accum["uniform_active"]["brier"] / n_steps
    mean_b_mar = bl_accum["train_marginal"]["brier"] / n_steps
    bss_mar = _bss(mean_bm, mean_b_mar)
    bss_uni = _bss(mean_bm, mean_b_uni)
    bss_con = _bss(mean_bm, mean_b_con)
    top3_block = _top3_eval_block(steps=n_steps, hits=top3_hits_sum, slots=top3_k_sum)
    by_gap, gap_cut = _bucket_top3_by_gap(eval_records)
    per_cat = _per_category_eval_blocks(cat_acc)
    eval_baselines: dict[str, dict] = {}
    for name, a in bl_accum.items():
        row: dict = {
            "mean_brier_active_heads": round(a["brier"] / n_steps, 6),
            "mean_logloss_active_heads": round(a["ll"] / n_steps, 6),
        }
        if name == "train_marginal":
            row["top3"] = _top3_eval_block(
                steps=n_steps, hits=a["hits"], slots=a["slots"]
            )
        eval_baselines[name] = row
    meta = {
        "backtest_mode": "walk_forward",
        "catboost_iterations": catboost_iterations(),
        "wf_min_train_weeks": WF_MIN_TRAIN,
        "wf_max_steps_cap": WF_MAX_STEPS,
        "wf_last_n_eval": WF_LAST_N,
        "wf_steps": n_steps,
        "eval": {
            "top3": top3_block,
            "BSS_vs_train_marginal": _round_opt(bss_mar),
            "BSS_vs_uniform_active": _round_opt(bss_uni),
            "BSS_vs_constant_0_05": _round_opt(bss_con),
            "mean_brier_baselines": {
                "train_marginal": round(mean_b_mar, 6),
                "uniform_active": round(mean_b_uni, 6),
                "constant_0_05": round(mean_b_con, 6),
            },
            "mean_logloss_active_heads": {
                "model": round(mean_ll_m, 6),
                "train_marginal": round(bl_accum["train_marginal"]["ll"] / n_steps, 6),
                "uniform_active": round(bl_accum["uniform_active"]["ll"] / n_steps, 6),
                "constant_0_05": round(bl_accum["constant_0.05"]["ll"] / n_steps, 6),
            },
            "by_confidence_gap": by_gap,
            "diagnostics": {
                "mean_brier_active_heads_per_step": round(mean_bm, 6),
            },
            "per_category": per_cat,
        },
        "eval_baselines": eval_baselines,
    }
    if gap_cut is not None:
        meta["eval"]["gap_tertile_cutpoints"] = gap_cut
    if write_meta_file:
        write_meta(meta)

    print(f"\n{'='*60}")
    print("백테스트 (워크포워드 · expanding window)")
    print("  학습 구간에 미등장한 카테고리는 예측에서 제외됩니다.")
    print(f"  CatBoost iterations: {catboost_iterations()}")
    print(f"  스텝 수: {n_steps} (t={t_start}…{t_end - 1})")
    if TRAIN_RECENT_WEEKS > 0:
        print(f"  전체 풀: 최근 {TRAIN_RECENT_WEEKS}주")
    print(f"{'='*60}")
    print("\n  [평가] Top-3 슬롯 적중률")
    r3 = top3_hits_sum / top3_k_sum if top3_k_sum else 0.0
    print(f"    {top3_hits_sum}/{top3_k_sum} 슬롯 → {r3:.1%}")
    print("\n  [평가] Top-3 스텝당 평균 hits")
    mh = top3_hits_sum / max(1, n_steps)
    print(f"    {mh:.3f} (총 hits {top3_hits_sum} / 스텝 {n_steps})")
    print("\n  [평가] Brier skill score (BSS = 1 − 모델/베이스라인, active-heads 평균 Brier)")
    print(f"    대 train_marginal: {_fmt_bss_console(bss_mar)}  (베이스 Brier {mean_b_mar:.6f})")
    print(f"    대 uniform_active: {_fmt_bss_console(bss_uni)}  (베이스 Brier {mean_b_uni:.6f})")
    print(f"    대 constant_0.05: {_fmt_bss_console(bss_con)}  (베이스 Brier {mean_b_con:.6f})")
    print("\n  [진단] 스텝당 active-heads Brier·logloss (내부 참고, 주 지표 아님)")
    print(f"    Brier: {mean_bm:.6f}  |  logloss 모델: {mean_ll_m:.6f}")
    print("\n  [평가] confidence(gap=Top1−Top2) 구간별 Top-3 슬롯 적중")
    labels = {
        "gap_high_clear": "높은 gap(선명)",
        "gap_mid": "중간 gap",
        "gap_low_ambiguous": "낮은 gap(애매)",
    }
    for key in ("gap_high_clear", "gap_mid", "gap_low_ambiguous"):
        if key not in by_gap:
            continue
        lab = labels[key]
        b = by_gap[key]
        sr = b.get("slot_hit_rate")
        sr_s = f"{sr:.1%}" if sr is not None else "N/A"
        print(f"    {lab}: 스텝 {b['steps']}  {b['hits']}/{b['slots']} → {sr_s}  (평균 hits/스텝 {b.get('mean_hits_per_step')})")
    if "gap_tertile_cutpoints" in meta["eval"]:
        q = meta["eval"]["gap_tertile_cutpoints"]
        print(f"    (gap 3분위 경계: q1={q['q1']}, q2={q['q2']})")
    baseline_labels = (
        ("constant_0.05", "고정 prior 0.05"),
        ("uniform_active", "균등 1/k"),
        ("train_marginal", "학습구간 양성 비율"),
    )
    print("\n  [베이스라인] 동일 스텝·active, 비학습 3종 (Top-3 적중은 train_marginal만)")
    for nm, lab in baseline_labels:
        e = eval_baselines[nm]
        if nm == "train_marginal":
            t3 = e["top3"]
            sr = t3.get("slot_hit_rate")
            sr_s = f"{sr:.1%}" if sr is not None else "N/A"
            print(
                f"    [{lab}] Top-3 {t3['hits']}/{t3['slots']} → {sr_s}  "
                f"Brier {e['mean_brier_active_heads']:.6f}  logloss {e['mean_logloss_active_heads']:.6f}"
            )
        else:
            print(
                f"    [{lab}] Brier {e['mean_brier_active_heads']:.6f}  "
                f"logloss {e['mean_logloss_active_heads']:.6f}"
            )
    print(f"\n  [카테고리별] Brier·BSS·logloss → 메타 eval.per_category ({len(per_cat)}개 cat)")
    print(f"\n  → 메타 저장: {META_PATH}")

    if verbose:
        print(f"\n{'='*60}")
        print("주별 상세 (Top-3 / gap / active-Brier 진단)")
        print(f"{'='*60}")
        for date_s, tk_hit, tk_k, tk_names, wc_step, br in tail_logs:
            sc = wc_step.get("score")
            sc_s = f"{sc:.1%}" if isinstance(sc, (int, float)) else "N/A"
            print(f"\n  [{date_s}] Top-{tk_k}: {tk_hit}/{tk_k}  active-Brier(진단)={br:.4f}")
            print(f"    gap Top1−Top2: {sc_s}")
            if tk_k:
                print(f"    상위→{tk_names}")
    else:
        print(f"\n  (주별 로그는 `python sunday_predictor.py backtest --verbose`)")
    print()
    return {"eval": meta["eval"], "eval_baselines": eval_baselines}


def cmd_last12_table() -> None:
    """최근 12주(학습 가능하면) 워크포워드와 동일 파이프로 표만 출력."""
    rows, _ = load_data()
    rows = add_category_labels(rows)
    features = build_features(rows, MAIN_CATS)
    tr = slice_train_features(features)
    off = len(rows) - len(tr)
    rows_tr = rows[off:]
    if len(tr) <= WF_MIN_TRAIN:
        print(f"데이터 부족: 학습 주 {len(tr)}주 ≤ WF_MIN_TRAIN={WF_MIN_TRAIN}")
        return

    def fmt_gap(score: float | None) -> str:
        if score is None:
            return "N/A"
        g = float(score)
        lv = "높음" if g >= 0.12 else ("중" if g >= 0.06 else "낮음")
        return f"{g:.1%}({lv})"

    t_lo = max(WF_MIN_TRAIN, len(tr) - 12)
    print(f"최근 {len(tr) - t_lo}주 (t={t_lo}..{len(tr) - 1}, WF와 동일 학습·Platt·shrink)\n")
    hdr = f"{'날짜':<12} {'Top-3 예측':<28} {'실제 혜택':<28} {'Hit':>4} {'hits':>5} {'confidence':>14}"
    print(hdr)
    print("─" * len(hdr))
    for t in range(t_lo, len(tr)):
        hist = tr[0:t]
        next_row = tr[t]
        rows_hist = rows_tr[0:t]
        active_cats = pick_active_cats(rows_hist)
        if len(hist) >= VAL_HOLDOUT + 15:
            val = hist[-VAL_HOLDOUT:]
            X_val = matrix_from_rows(val)
            chain = train_chain(hist, active_cats)
            cal_deploy = fit_platt_calibrators(chain, X_val, val, active_cats)
        else:
            chain = train_chain(hist, active_cats)
            cal_deploy = None
        X_next = matrix_from_rows([next_row])
        pr = predict_proba_batch(chain, X_next, active_cats, cal_deploy)[0]
        pr = _shrink_probs_to_marginal(pr, rows_hist, active_cats)
        k_top = min(3, len(active_cats))
        topk = (
            sorted(active_cats, key=lambda c: float(pr[c]), reverse=True)[:k_top] if k_top else []
        )
        actual = [c for c in active_cats if _row_binary_label(next_row, c) == 1]
        hits = len(set(topk) & set(actual))
        hit01 = 1 if hits > 0 else 0
        wc = week_confidence_gap(pr, active_cats)
        pred_s = ",".join(topk) if topk else "-"
        act_s = ",".join(actual) if actual else "-"
        print(
            f"{next_row['date']:<12} {pred_s:<28} {act_s:<28} {hit01:>4} {hits:>5} {fmt_gap(wc.get('score')):>14}"
        )


def cmd_backtest():
    """argv의 --verbose로 워크포워드 백테 실행, 메타 파일 갱신."""
    verbose = "--verbose" in sys.argv
    run_walk_forward_backtest(verbose=verbose, write_meta_file=True)


def cmd_add(date_str, tags_str, event_name=None):
    """CSV에 한 주 추가, Supabase ssunday 반영 시도."""
    # CSV append → (선택) ssunday
    rows, all_cols = load_data()
    if event_name is None:
        event_name = rows[-1].get("event", "(-)") if rows else "(-)"
    tag_cols = [c for c in all_cols if c not in ("date", "event")]
    new_tags = [t.strip() for t in tags_str.split(",")]
    new_row = {"date": date_str, "event": event_name}
    for tc in tag_cols:
        new_row[tc] = "1" if tc in new_tags else "0"
    with open(DATA_PATH, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=all_cols)
        w.writerow(new_row)
    tag_row_for_sb = {tc: new_row[tc] for tc in tag_cols}
    push_sunday_to_supabase(date_str, event_name, tag_row_for_sb)
    print(f"✅ 추가: {date_str}  이벤트: {event_name}  태그: {new_tags}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print(
            "예:  python sunday_predictor.py predict [--dry-run]\n"
            "     python sunday_predictor.py backtest [--verbose]\n"
            "     python sunday_predictor.py last12\n"
            "\n"
            "백테스트 환경변수 (선택):\n"
            "  SUNDAY_WF_LAST_N=13     # 끝에서 N스텝만 평가\n"
            "  SUNDAY_WF_MAX_STEPS=0   # 0이면 t_start~끝까지\n"
            "  SUNDAY_CATBOOST_ITERATIONS=80\n"
            "  SUNDAY_PREDICT_TOP_K=3   # predict 유력 후보 개수(백테 Top-3와 맞추려면 3)\n"
            "  SUNDAY_SPW_MAX=2        # scale_pos_weight 상한 (CatBoost 체인만)\n"
            "  → cd sunday_predict && .venv/bin/python sunday_predictor.py backtest --verbose\n"
            "  또는 ./run_backtest_sample.sh"
        )
        sys.exit(0)
    c = sys.argv[1]
    if c == "predict":
        cmd_predict(dry_run="--dry-run" in sys.argv)
    elif c == "backtest":
        cmd_backtest()
    elif c == "last12":
        cmd_last12_table()
    elif c == "add":
        if len(sys.argv) < 4:
            print(
                '사용법: python sunday_predictor.py add 2026.04.12 "룬_콤보킬,몬스터파크"\n'
                "       (선택) 네 번째 인자로 이벤트명 지정. 생략 시 CSV 마지막 행의 이벤트명을 이어받음."
            )
            sys.exit(1)
        ev = sys.argv[4] if len(sys.argv) > 4 else None
        cmd_add(sys.argv[2], sys.argv[3], ev)
    else:
        print(f"알 수 없는 명령: {c}")
        print("predict | backtest | last12 | add")
