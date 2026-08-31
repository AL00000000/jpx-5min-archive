# -*- coding: utf-8 -*-
"""TOPIX入替推計に必要な生データ(株探の日足・銘柄情報・大株主)を cache/ に貯める。

  py fetch_rebalance.py            # 未取得ぶんだけ取る(再開可能)
  py fetch_rebalance.py --force    # 全部取り直す
"""
from __future__ import annotations

import csv
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rebalance_lib as R           # noqa: E402

TOPIX_WEIGHT_URL = "https://www.jpx.co.jp/automation/markets/indices/topix/files/topixweight_j.csv"
WEIGHT_CSV = R.CACHE / "topixweight_j.csv"


def download_weights(force: bool = False) -> list[dict]:
    if force or not WEIGHT_CSV.exists():
        req = urllib.request.Request(TOPIX_WEIGHT_URL, headers=R.UA)
        WEIGHT_CSV.write_bytes(urllib.request.urlopen(req, timeout=60).read())
    rows = list(csv.DictReader(WEIGHT_CSV.open(encoding="cp932", errors="replace")))
    out = []
    for r in rows:
        try:
            w = float(r["TOPIXに占める個別銘柄のウエイト"].strip().rstrip("%"))
        except (ValueError, KeyError):
            continue
        out.append({"code": r["コード"].strip(), "name": r["銘柄名"].strip(),
                    "sector": r.get("業種", "").strip(), "weight": w,
                    "size": r.get("ニューインデックス区分", "").strip(),
                    "date": r["日付"].strip()})
    return out


def load_candidates() -> list[dict]:
    p = Path(__file__).resolve().parent / "symbols.csv"
    out = []
    for r in csv.DictReader(p.open(encoding="utf-8-sig")):
        out.append({"code": r["コード"].strip(), "name": r["銘柄名"].strip(),
                    "market": r["市場"].strip()})
    return out


def main() -> None:
    force = "--force" in sys.argv
    weights = download_weights(force)
    cands = load_candidates()
    topix_codes = {w["code"] for w in weights}
    cands = [c for c in cands if c["code"] not in topix_codes]
    print(f"TOPIX構成銘柄 {len(weights)} / 非TOPIX候補 {len(cands)}", flush=True)

    # 1) 指数(TOPIX)の日足 … 営業日数の算定に使う
    R.fetch_daily("0010", use_cache=not force)

    # 2) 日足: TOPIX構成銘柄 + 候補
    targets = [w["code"] for w in weights] + [c["code"] for c in cands]
    t0, ng = time.time(), []
    for i, code in enumerate(targets, 1):
        if not force and R.daily_path(code).exists():
            continue
        try:
            R.fetch_daily(code, use_cache=not force)
        except Exception as e:                                  # noqa: BLE001
            ng.append((code, str(e)[:80]))
        if i % 100 == 0:
            print(f"  daily {i}/{len(targets)}  {time.time()-t0:.0f}s  ng={len(ng)}", flush=True)

    # 3) 候補のみ: 時価総額・発行済株式数・大株主(浮動株比率の推計用)
    for i, c in enumerate(cands, 1):
        for fn in (R.fetch_profile, R.fetch_float_ratio):
            try:
                fn(c["code"], use_cache=not force)
            except Exception as e:                              # noqa: BLE001
                ng.append((c["code"], f"{fn.__name__}: {str(e)[:60]}"))
        if i % 50 == 0:
            print(f"  profile/holder {i}/{len(cands)}  {time.time()-t0:.0f}s", flush=True)

    print(f"完了 {time.time()-t0:.0f}s  失敗 {len(ng)}件", flush=True)
    for c, e in ng[:30]:
        print("  NG", c, e, flush=True)


if __name__ == "__main__":
    main()
