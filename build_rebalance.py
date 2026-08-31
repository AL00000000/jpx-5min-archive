# -*- coding: utf-8 -*-
"""cache/ の生データから TOPIX定期入替(2026年10月)の採用/除外を推計し
docs/data/rebalance.json を書き出す。
"""
from __future__ import annotations

import datetime as dt
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rebalance_lib as R                    # noqa: E402
from fetch_rebalance import download_weights, load_candidates   # noqa: E402

BASE = Path(__file__).resolve().parent
OUT = BASE / "docs" / "data" / "rebalance.json"


def main() -> None:
    weights = download_weights()
    inel = R.fetch_ineligible()
    NG = {}
    for c in inel["alert"]:
        NG[c] = "特別注意銘柄"
    for c in inel["seiri"]:
        NG[c] = "整理銘柄"
    KANRI = set(inel["kanri"])
    idx = R.fetch_daily("0010")
    market_days = {m: sum(1 for d in idx if R.month_of(d) == m) for m in R.MONTHS}
    topix_aug = R.aug_avg_close(idx)
    topix_mar = statistics.mean(v["c"] for d, v in idx.items() if R.month_of(d) == "202603")
    topix_0731 = R.close_on_or_before(idx, R.WEIGHT_SNAPSHOT)

    # JPX公表値(691兆円 @ TOPIX 3,644.58)を指数水準でスケールして絶対額に直す
    total_0731 = R.JPX_TOTAL_FLOAT_MKTCAP * topix_0731 / R.JPX_TOPIX_MAR_AVG
    t97_anchor = R.JPX_T97_MAR * topix_aug / R.JPX_TOPIX_MAR_AVG

    # ---------------------------------------------------------- 現構成銘柄
    members, skipped = [], []
    for w in weights:
        code = w["code"]
        if not R.daily_path(code).exists():
            skipped.append({**w, "why": "日足なし"})
            continue
        daily = R.fetch_daily(code)
        p0731 = R.close_on_or_before(daily, R.WEIGHT_SNAPSHOT)
        aug = R.aug_avg_close(daily)
        if not p0731 or not aug:
            skipped.append({**w, "why": "8月の株価なし"})
            continue
        float_shares = (w["weight"] / 100.0) * total_0731 / p0731
        fmc = float_shares * aug
        months = sorted({R.month_of(d) for d in daily})
        lm = months[0] if months and months[0] > "202509" else None
        tr, detail, nmon = R.turnover_ratio(daily, market_days, float_shares, lm)
        members.append({**w, "float_mktcap": fmc, "float_shares": float_shares, "lm": lm,
                        "turnover": tr, "months": nmon, "aug_close": aug,
                        "monthly": detail})

    # ------------------------- 大株主ベースの浮動株比率を実測でキャリブレートする
    # 現構成銘柄については「ウエイトから逆算した浮動株比率」(=ほぼ正解)と
    # 「大株主上位10名から推計した浮動株比率」の両方が出せる。両者の比の中央値を取り、
    # 候補銘柄の浮動株比率に掛けて系統誤差を補正する。
    # 上位10名しか見えないため11位以下の政策保有株を拾えず、大株主ベースは過大に出る。
    # (JPXが一部銘柄に適用している調整係数0.75の影響もこの比に混ざっているが、
    #  比の分布は単峰で二峰性がないため、支配的なのは大株主ベースの過大推計と判断した)
    ratios = []
    for m in members:
        pf = R.CACHE / "profile" / f"{m['code']}.json"
        fl = R.CACHE / "float" / f"{m['code']}.json"
        if not (pf.exists() and fl.exists()):
            continue
        shares = json.loads(pf.read_text(encoding="utf-8")).get("shares")
        hr = json.loads(fl.read_text(encoding="utf-8")).get("ratio")
        if not shares or not hr:
            continue
        implied = m["float_shares"] / shares
        m["implied_ratio"], m["holder_ratio"] = round(implied, 4), round(hr, 4)
        if 0.2 <= implied / hr <= 2.0:
            ratios.append(implied / hr)
    float_calib = statistics.median(ratios) if len(ratios) >= 30 else 1.0

    # ------------------------------------------------------------ 候補銘柄
    topix_codes = {w["code"] for w in weights}
    cands = [c for c in load_candidates() if c["code"] not in topix_codes]
    candidates = []
    for c in cands:
        code = c["code"]
        if not R.daily_path(code).exists():
            continue
        daily = R.fetch_daily(code)
        aug = R.aug_avg_close(daily)
        if not aug:
            continue
        try:
            prof = R.fetch_profile(code)
            fl = R.fetch_float_ratio(code)
        except Exception:                                        # noqa: BLE001
            continue
        shares, ratio = prof.get("shares"), fl.get("ratio")
        if not shares or not ratio:
            continue
        ratio_adj = min(1.0, ratio * float_calib)
        float_shares = shares * ratio_adj
        fmc = float_shares * aug
        months = sorted({R.month_of(d) for d in daily})
        lm = months[0] if months and months[0] > "202509" else None
        tr, detail, nmon = R.turnover_ratio(daily, market_days, float_shares, lm)
        candidates.append({**c, "mktcap": prof.get("mktcap"), "float_ratio": ratio_adj,
                           "float_ratio_raw": ratio,
                           "float_shares": float_shares, "float_mktcap": fmc,
                           "turnover": tr, "months": nmon, "aug_close": aug,
                           "nonfloat_pct": fl.get("nonfloat_pct"),
                           "nonfloat": fl.get("nonfloat", [])[:5], "monthly": detail})

    # ------------------------------------------- 累積比率のカットオフを求める
    pool = [x for x in members + candidates if x["code"] not in NG]
    keep_pool = [x["float_mktcap"] for x in pool if (x["turnover"] or 0) >= R.TURNOVER_KEEP]
    add_pool = [x["float_mktcap"] for x in pool if (x["turnover"] or 0) >= R.TURNOVER_ADD]

    t97_self = R.cumulative_cutoff(keep_pool, R.CUM_KEEP)
    t96_self = R.cumulative_cutoff(add_pool, R.CUM_ADD)
    # 母集団に入れられていない小型の非TOPIX銘柄ぶんを、JPX公表値でキャリブレートする
    calib = t97_anchor / t97_self if t97_self else 1.0
    t96 = t96_self * calib
    t97 = t97_anchor

    for m in members:
        m["kanri"] = m["code"] in KANRI
        if m["code"] in NG:
            m["keep"], m["fail"] = False, ["母集団外(" + NG[m["code"]] + ")"]
            continue
        tr = m["turnover"]
        ok_t = tr is not None and tr >= R.TURNOVER_KEEP
        ok_c = m["float_mktcap"] >= t97
        m["keep"] = bool(ok_t and ok_c)
        m["fail"] = ([] if ok_t else ["回転率"]) + ([] if ok_c else ["浮動株時価総額"])
    for c in candidates:
        c["kanri"] = c["code"] in KANRI
        if c["code"] in NG:
            c["add"], c["fail"] = False, ["母集団外(" + NG[c["code"]] + ")"]
            continue
        tr = c["turnover"]
        ok_t = tr is not None and tr >= R.TURNOVER_ADD
        ok_c = c["float_mktcap"] >= t96
        c["add"] = bool(ok_t and ok_c)
        c["fail"] = ([] if ok_t else ["回転率"]) + ([] if ok_c else ["浮動株時価総額"])

    def slim(x, keys):
        return {k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in x.items() if k in keys}

    mk = ("code name sector size weight float_mktcap turnover months keep fail "
          "implied_ratio holder_ratio kanri").split()
    ck = ("code name market mktcap float_ratio float_mktcap turnover months add fail "
          "nonfloat_pct nonfloat kanri float_ratio_raw").split()

    excluded = sorted([m for m in members if not m["keep"]],
                      key=lambda x: -x["float_mktcap"])          # 大きい順
    kept = sorted([m for m in members if m["keep"]], key=lambda x: x["float_mktcap"])
    added = sorted([c for c in candidates if c["add"]], key=lambda x: x["float_mktcap"])  # 小さい順
    missed = sorted([c for c in candidates if not c["add"]], key=lambda x: -x["float_mktcap"])

    payload = {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "base_date": "2026-08-31",
        "announce_date": "2026-10-07",
        "effective_date": "2026-10-30",
        "meta": {
            "weight_date": weights[0]["date"] if weights else "",
            "topix_aug_avg": round(topix_aug, 2),
            "topix_mar_avg": round(topix_mar, 2),
            "topix_0731": round(topix_0731, 2),
            "total_float_mktcap": total_0731,
            "t97": t97, "t96": t96,
            "t97_self": t97_self, "t96_self": t96_self, "calib": round(calib, 4),
            "market_days": market_days,
            "n_members": len(members), "n_candidates": len(candidates),
            "n_keep": len(kept), "n_excluded": len(excluded), "n_added": len(added),
            "float_calib": round(float_calib, 4), "n_calib_sample": len(ratios),
            "ineligible": NG, "n_kanri": len(KANRI),
            "skipped": skipped,
        },
        "excluded": [slim(x, mk) for x in excluded],
        "kept": [slim(x, mk) for x in kept],
        "added": [slim(x, ck) for x in added],
        "missed": [slim(x, ck) for x in missed],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")

    print(f"TOPIX 8月平均 {topix_aug:.2f} / 3月平均 {topix_mar:.2f} (JPX公表 {R.JPX_TOPIX_MAR_AVG})")
    print(f"母集団の浮動株時価総額合計(7/31) {total_0731/1e12:.1f}兆円")
    print(f"継続の足切り(97%) {t97/1e8:,.0f}億円  自前計算 {t97_self/1e8:,.0f}億円  補正 x{calib:.3f}")
    print(f"追加の足切り(96%) {t96/1e8:,.0f}億円  自前計算 {t96_self/1e8:,.0f}億円")
    print(f"現構成 {len(members)} → 継続 {len(kept)} / 除外 {len(excluded)}")
    print(f"母集団から除外(整理・特別注意銘柄) {len(NG)}銘柄: {sorted(NG)}")
    print(f"浮動株比率のキャリブレーション x{float_calib:.3f} (実測{len(ratios)}銘柄)")
    print(f"候補 {len(candidates)} → 採用 {len(added)}")
    print(f"次期TOPIX 想定 {len(kept)+len(added)} 銘柄   -> {OUT}")


if __name__ == "__main__":
    main()
