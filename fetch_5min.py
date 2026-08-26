# -*- coding: utf-8 -*-
"""symbols.csv の全銘柄について株探から5分足を取得し、日付ごとにgzip JSONで蓄積する。

株探の5分足エンドポイント(m=5)は直近5営業日分をまとめて返すため、
取得に失敗した日や PC が落ちていた日があっても、4営業日以内の実行で自動的に埋め戻される。

出力:
  data/YYYY-MM-DD.json.gz  … その日の全銘柄の5分足 {"bars": {code: [[t,o,h,l,c,v], ...]}}
  data/manifest.json       … 保存済み日付一覧と銘柄マスタ(閲覧サイト用)
"""
import csv
import gzip
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent
DATA = BASE / "docs" / "data"
SYMBOLS_CSV = BASE / "symbols.csv"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
URL = "https://kabutan.jp/stock/read?c={code}&m=5&k=1"
SLEEP = 1.0        # リクエスト間隔(秒)
RETRIES = 3
TIMEOUT = 20


def load_symbols():
    """symbols.csv から (code, name, market) を読む。BOM付きUTF-8に対応。"""
    out = []
    with SYMBOLS_CSV.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = (row.get("コード") or "").strip()
            if not code:
                continue
            out.append({
                "code": code,
                "name": (row.get("銘柄名") or "").strip(),
                "market": (row.get("市場") or "").strip(),
            })
    return out


def fetch(code):
    last = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(URL.format(code=code),
                                         headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if attempt < RETRIES - 1:
                time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"fetch failed for {code}: {last}")


def parse(raw):
    """レスポンスを {日付: [[t,o,h,l,c,v], ...]} に変換(時刻昇順)。

    先頭行は銘柄ヘッダで、2列目は市場コード(0=指数, 1=東証, 3=名証, 6=福証, 8=札証)。
    指数のみ株価が100倍のため除数を変える。銘柄が無い場合はボディが "0" だけになる。
    """
    lines = raw.strip().split("\n")
    if not lines:
        return {}
    hdr = lines[0].split(",")
    if len(hdr) < 3 or not hdr[1].isdigit():
        return {}
    div = 100 if hdr[1] == "0" else 10

    days = {}
    for ln in lines[1:]:
        p = ln.split(",")
        if len(p) < 7 or not p[0] or "/" not in p[0]:
            continue
        try:
            o, h, l, c = (float(p[i]) / div for i in (1, 2, 3, 4))
            v = int(p[5])
        except ValueError:
            continue
        date = p[6].replace(".", "-")
        if len(date) != 10:
            continue
        days.setdefault(date, []).append([p[0].split("/")[1], o, h, l, c, v])

    for bars in days.values():
        bars.reverse()          # 新しい順で返ってくるので時刻昇順に直す
    return days


def read_day(path):
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def write_day(path, payload):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(path)           # 書き込み途中のファイルを残さない


def main():
    symbols = load_symbols()
    DATA.mkdir(parents=True, exist_ok=True)
    print(f"対象: {len(symbols)} 銘柄", file=sys.stderr)

    collected = {}      # {日付: {コード: bars}}
    empty, failed = [], []

    for i, s in enumerate(symbols, 1):
        code = s["code"]
        try:
            days = parse(fetch(code))
        except Exception as e:
            failed.append(code)
            print(f"  [{i}/{len(symbols)}] {code} ERROR: {e}", file=sys.stderr)
            time.sleep(SLEEP)
            continue

        if not days:
            empty.append(code)
        for date, bars in days.items():
            collected.setdefault(date, {})[code] = bars

        if i % 50 == 0:
            print(f"  [{i}/{len(symbols)}] ...", file=sys.stderr)
        time.sleep(SLEEP)

    if not collected:
        print("ERROR: 1銘柄もデータを取得できませんでした(仕様変更の可能性)",
              file=sys.stderr)
        sys.exit(1)

    # 日付ごとに保存。既存ファイルがあればマージして更新する
    # (前回失敗した銘柄の穴埋め・暫定値の訂正がこれで効く)
    now = datetime.now().isoformat(timespec="seconds")
    for date in sorted(collected):
        path = DATA / f"{date}.json.gz"
        existing = read_day(path)
        bars = dict(existing["bars"]) if existing else {}
        before = len(bars)
        bars.update(collected[date])
        write_day(path, {"date": date, "generated": now, "bars": bars})
        added = len(bars) - before
        state = "new" if existing is None else f"updated +{added}"
        size_kb = path.stat().st_size / 1024
        print(f"{date}: {len(bars)} 銘柄 ({state}, {size_kb:.0f} KB)", file=sys.stderr)

    # 閲覧サイト用のマニフェスト。
    # 対象銘柄を絞って部分実行してもマニフェストが縮まないよう、
    # 既存マニフェストの銘柄と今回データが取れた銘柄の和集合にする。
    dates = sorted(p.name[:10] for p in DATA.glob("????-??-??.json.gz"))
    manifest_path = DATA / "manifest.json"
    known = set()
    if manifest_path.exists():
        try:
            prev = json.loads(manifest_path.read_text(encoding="utf-8"))
            known = {x["code"] for x in prev.get("symbols", [])}
        except (ValueError, KeyError, TypeError):
            known = set()
    got = {c for by_code in collected.values() for c in by_code}
    listed = known | got
    by_code = {s["code"]: s for s in load_symbols()}
    manifest_path.write_text(
        json.dumps({
            "updated": now,
            "dates": list(reversed(dates)),
            "symbols": [by_code[c] for c in by_code if c in listed],
        }, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")

    print(f"保存済み日付: {len(dates)} 日分 (最新 {dates[-1]})", file=sys.stderr)
    if empty:
        print(f"データなし {len(empty)}銘柄(上場廃止等): {','.join(empty)}",
              file=sys.stderr)
    if failed:
        print(f"取得失敗 {len(failed)}銘柄: {','.join(failed)}", file=sys.stderr)
        sys.exit(1)      # 失敗があればタスクを異常終了扱いにする


if __name__ == "__main__":
    main()
