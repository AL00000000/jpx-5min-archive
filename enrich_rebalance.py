# -*- coding: utf-8 -*-
"""当落線上の現構成銘柄について、調整係数(0.75)の適用有無を推定するための追加取得。

TOPIXのウエイトは「算出浮動株比率 = 浮動株比率 x 調整係数(0.75) x 移行係数」で計算されるが、
銘柄選定に使う浮動株時価総額は「浮動株比率」(調整係数なし)で計算される。
調整係数が適用されている銘柄(第1段階の移行措置を生き残った銘柄、および2022年4月以降に
プライム市場へ新規上場・市場区分変更した銘柄)は、ウエイトから逆算した浮動株時価総額が
本来より25%低く出てしまい、当落線上で誤判定になる。

発行済株式数と大株主から推計した浮動株比率と、ウエイトから逆算した実効浮動株比率を
突き合わせ、比が 0.75 に近い銘柄を「調整係数あり」とみなして補正する。

  py enrich_rebalance.py          # 当落線上(既定 200〜900億円)の銘柄だけ取得
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rebalance_lib as R                                  # noqa: E402
from fetch_rebalance import download_weights               # noqa: E402

BAND_LO, BAND_HI = 200e8, 900e8      # 補正の有無で当落が変わりうる帯


def boundary_codes() -> list[str]:
    """docs/data/rebalance.json から当落線上の現構成銘柄コードを拾う。"""
    p = Path(__file__).resolve().parent / "docs" / "data" / "rebalance.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for r in d["excluded"] + d["kept"]:
        if BAND_LO <= r["float_mktcap"] <= BAND_HI:
            out.append(r["code"])
    return out


def main() -> None:
    codes = boundary_codes()
    print(f"当落線上の銘柄 {len(codes)} 件を取得します", flush=True)
    t0, ng = time.time(), 0
    for i, code in enumerate(codes, 1):
        for fn in (R.fetch_profile, R.fetch_float_ratio):
            try:
                fn(code)
            except Exception:                              # noqa: BLE001
                ng += 1
        if i % 50 == 0:
            print(f"  {i}/{len(codes)}  {time.time()-t0:.0f}s  ng={ng}", flush=True)
    print(f"完了 {time.time()-t0:.0f}s  失敗 {ng}", flush=True)


if __name__ == "__main__":
    main()
