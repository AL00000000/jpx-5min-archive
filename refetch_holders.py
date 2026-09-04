# -*- coding: utf-8 -*-
"""候補銘柄の大株主を取り直す(キャッシュに持ち株数を入れるため)。

株探の大株主の「比率」は公表時点の発行済株式数ベースなので、比率を現在ベースに
引き直すには持ち株数が要る。既存キャッシュには株数が入っていないので一度だけ取り直す。
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rebalance_lib as R
from fetch_rebalance import download_weights, load_candidates

topix = {w["code"] for w in download_weights()}
codes = [c["code"] for c in load_candidates() if c["code"] not in topix]
t0, n, ng = time.time(), 0, []
for i, code in enumerate(codes, 1):
    p = R.CACHE / "float" / f"{code}.json"
    j = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    if j.get("hdate") and any(h.get("shares") for h in j.get("holders", [])):
        continue
    try:
        R.fetch_float_ratio(code, use_cache=False)
        n += 1
    except Exception as e:                                       # noqa: BLE001
        ng.append(code)
    if i % 50 == 0:
        print(f"  {i}/{len(codes)}  {time.time()-t0:.0f}s", flush=True)
print(f"取り直し {n}銘柄 / 失敗 {len(ng)} {ng}  {time.time()-t0:.0f}s")
