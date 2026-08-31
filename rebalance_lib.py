# -*- coding: utf-8 -*-
"""TOPIX定期入替(2026年10月)の採用/除外を推計するための共通ライブラリ。

JPX総研「TOPIX算出要領」(2025-12-10版)の定義に従う:
  - 定期入替基準日 = 2026年8月最終営業日 (2026-08-31)
  - 浮動株時価総額の累積比率 … 基準日が属する月(2026年8月)の日次平均の浮動株時価総額
  - 年間売買代金回転率 … 基準日が属する月以前12か月(2025年9月〜2026年8月)の
      月次回転率の合計。月次 = (日次売買代金の中央値 x 営業日数) / 月末最終営業日の浮動株時価総額
  - 追加基準: 回転率 0.2 以上 かつ 累積比率 上位96%以内
  - 継続基準: 回転率 0.14 以上 かつ 累積比率 上位97%以内
"""
from __future__ import annotations

import gzip
import json
import re
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
CACHE = BASE / "cache"
CACHE.mkdir(exist_ok=True)

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")}

BASE_DATE = "20260831"          # 定期入替基準日
BASE_MONTH = "202608"
MONTHS = ["202509", "202510", "202511", "202512",
          "202601", "202602", "202603", "202604",
          "202605", "202606", "202607", "202608"]
WEIGHT_SNAPSHOT = "20260731"    # topixweight_j.csv の日付

# JPX資料「TOPIXの見直しについて」(2026年5月) p.6 の公表値
JPX_TOTAL_FLOAT_MKTCAP = 691e12   # 現行TOPIX 浮動株時価総額の合計 (2026/3末時点)
JPX_TOPIX_MAR_AVG = 3644.58       # 同資料の TOPIX 月間平均 (2026年3月)
JPX_T97_MAR = 360e8               # 累積比率上位97%以内の最小浮動株時価総額 (約360億円)

TURNOVER_ADD = 0.20
TURNOVER_KEEP = 0.14
CUM_ADD = 0.96
CUM_KEEP = 0.97


def fetch(url: str, retries: int = 3, sleep: float = 0.35) -> str:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                time.sleep(sleep)
                return r.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            time.sleep(1.0 + i * 1.5)
    raise RuntimeError(f"fetch failed: {url}: {last}")


# ---------------------------------------------------------------- 株探 日足

def daily_path(code: str) -> Path:
    return CACHE / "daily" / f"{code}.json.gz"


def fetch_daily(code: str, use_cache: bool = True) -> dict:
    """株探の日足を取得して {YYYYMMDD: {"c": 終値, "v": 出来高, "t": 売買代金(円)}} を返す。

    レスポンス1行目の2列目は市場コード(0=指数, 1=東証, 3=名証, 6=福証, 8=札証)。
    株価の除数は指数のみ100、それ以外は10。7列目は売買代金(百万円)。
    """
    p = daily_path(code)
    if use_cache and p.exists():
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return json.load(f)

    raw = fetch(f"https://kabutan.jp/stock/read?c={code}&m=1&k=1")
    lines = raw.strip().split("\n")
    if not lines:
        raise RuntimeError(f"empty response for {code}")
    head = lines[0].split(",")
    div = 100.0 if (len(head) > 1 and head[1] == "0") else 10.0

    out = {}
    for ln in lines[1:]:
        c = ln.split(",")
        if len(c) < 7 or not c[0] or not c[4]:
            continue
        d = c[0]
        if d < "202501":          # 12か月+αあれば十分
            break
        try:
            close = int(c[4]) / div
            vol = int(c[5]) if c[5] else 0
            tv = float(c[6]) * 1e6 if c[6] else 0.0   # 百万円 -> 円
        except ValueError:
            continue
        out[d] = {"c": close, "v": vol, "t": tv}

    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    return out


# ------------------------------------------------------- 指標の計算 (JPX定義)

def month_of(d: str) -> str:
    return d[:6]


def turnover_ratio(daily: dict, market_days: dict[str, int],
                   float_shares: float, listing_month: str | None = None):
    """年間売買代金回転率 = 12か月分の月次回転率の合計。

    月次 = (その月の日次売買代金の中央値 x その月の営業日数) / 月末浮動株時価総額
    月末浮動株時価総額 = float_shares x 月末最終営業日の終値

    基準日時点で上場1年未満の銘柄は、算出要領のとおり
    「新規上場日の翌月から基準日の月までの月次回転率の合計 / 月数 x 12」で年換算する。
    """
    if not float_shares or float_shares <= 0:
        return None, {}, 0
    detail = {}
    for m in MONTHS:
        days = sorted(d for d in daily if month_of(d) == m)
        if not days:
            continue
        if listing_month is not None and m <= listing_month:
            continue                       # 新規上場日の属する月までは除く
        tvs = [daily[d]["t"] for d in days]
        mend_close = daily[days[-1]]["c"]
        fmc = float_shares * mend_close
        if fmc <= 0:
            continue
        detail[m] = round(statistics.median(tvs) * market_days.get(m, len(days)) / fmc, 5)
    if not detail:
        return None, {}, 0
    if len(detail) == len(MONTHS):
        return sum(detail.values()), detail, len(detail)
    return sum(detail.values()) / len(detail) * 12, detail, len(detail)


def aug_avg_close(daily: dict) -> float | None:
    v = [daily[d]["c"] for d in sorted(daily) if month_of(d) == BASE_MONTH]
    return statistics.mean(v) if v else None


def close_on_or_before(daily: dict, date: str) -> float | None:
    ds = [d for d in daily if d <= date]
    return daily[max(ds)]["c"] if ds else None


def cumulative_cutoff(items: list[float], ratio: float) -> float:
    """浮動株時価総額のリストから、累積比率 ratio 以内に入る最小値を返す。"""
    xs = sorted(items, reverse=True)
    tot = sum(xs)
    if tot <= 0:
        return 0.0
    c = 0.0
    for x in xs:
        c += x
        if c / tot >= ratio:
            return x
    return xs[-1]


# ------------------------------------------------- 株探 銘柄ページ / 大株主

_NUM = r"([0-9,]+(?:\.[0-9]+)?)"


def fetch_profile(code: str, use_cache: bool = True) -> dict:
    """株探の銘柄ページから 時価総額(円) と 発行済株式数(株) を取る。

    時価総額の表記は「46 兆 618 億円」「6,405 億円」の2通りがある。
    """
    p = CACHE / "profile" / f"{code}.json"
    if use_cache and p.exists():
        return json.loads(p.read_text(encoding="utf-8"))

    h = fetch(f"https://kabutan.jp/stock/?code={code}")
    txt = re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", h).replace("&nbsp;", " "))
    out = {"code": code, "mktcap": None, "shares": None}

    m = re.search(r"時価総額 (?:" + _NUM + r" 兆 )?" + _NUM + r" 億円", txt)
    if m:
        cho = float(m.group(1).replace(",", "")) if m.group(1) else 0.0
        oku = float(m.group(2).replace(",", ""))
        out["mktcap"] = cho * 1e12 + oku * 1e8
    m = re.search(r"発行済株式数 " + _NUM + r" 株", txt)
    if m:
        out["shares"] = float(m.group(1).replace(",", ""))
    m = re.search(r"単元株数 " + _NUM + r" 株", txt)
    if m:
        out["unit"] = float(m.group(1).replace(",", ""))

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


# 大株主上位10名を「浮動株 / 非浮動株」に振り分けるためのパターン。
# JPXの浮動株比率は「政策保有株」を除外する。したがって
#   非浮動 … 自己株式・持株会・親会社や事業会社の政策保有・銀行/生保の政策保有・創業家
#   浮動   … 信託口やカストディアン、証券会社、運用ファンド(アクティビストを含む)
# 判定は下の3段階を上から順に当てる。どれにも当たらなければ非浮動(事業会社・創業家とみなす)。
# 「日本マスタートラスト信託銀行」のように、銀行なのに浮動株であるものを先に拾う必要がある。

# ① 確実に浮動株(信託口・カストディアン・証券会社・ファンド)
_FLOAT_STRONG = re.compile(
    r"信託口|マスタートラスト|カストデ|"
    r"ステート[･・]?ストリート|ノーザン[･・]?トラスト|"
    r"ＪＰモルガン|JPモルガン|JPMORGAN|ＪＰＭ|JPM|"
    r"ＢＮＹ|BNY|ニユ?ーヨーク|メロン|ＨＳＢＣ|HSBC|"
    r"バークレイズ|シティ|ゴールドマン|モルガン|メリルリンチ|ＵＢＳ|UBS|"
    r"チェース|マンハッタン|ＢＢＨ|BBH|ブラウン[･・]?ブラザーズ|"
    r"ＢＮＰ|BNP|パリバ|ソシエテ|ドイツ銀行|スタンダードチャータード|"
    r"証券|證券|ブローカー|セキュリティーズ|ノミニー|オムニバス|"
    r"クライアント|アカウント|"
    r"ファンド|ＦＵＮＤ|FUND|ポートフォリオ|ＵＣＩＴＳ|UCITS|SICAV|"
    r"ＤＦＡ|DFA|ヴァンガード|バンガード|ブラックロック|フィデリティ|"
    r"ノルウェー政府|ＧＩＣ|アブダビ|クウェート")

# ② 確実に非浮動(自己株・持株会・政策保有の金融機関・投資事業組合)
_NONFLOAT = re.compile(
    r"自己株|自社|持株会|共栄会|協力会|"
    r"投資事業有限責任組合|投資事業組合|財団|奨学会|"
    r"生命保険|損害保険|海上火災|火災海上|"
    r"銀行|信用金庫|信用組合|農林中央金庫|商工組合|信用農業")

# ③ ①に漏れた運用主体(社名だけでは断定しづらいが運用目的とみられるもの)
_FLOAT_HINT = re.compile(
    r"インベストメント|インベスターズ|アセット|"
    r"キャピタル|パートナーズ|アドバイザー|マネジメント|年金|運用")


def classify_holders(holders: list[dict]) -> tuple[float, list[dict]]:
    """大株主から (非浮動比率, 非浮動とみなした株主) を返す。"""
    nonfloat, detail = 0.0, []
    for h in holders:
        n = h["name"]
        if _FLOAT_STRONG.search(n):
            is_non = False
        elif _NONFLOAT.search(n):
            is_non = True
        elif _FLOAT_HINT.search(n):
            is_non = False
        else:
            is_non = True          # 事業会社・創業家など
        if is_non:
            nonfloat += h["pct"]
            detail.append({"name": n, "pct": h["pct"]})
    return nonfloat, detail


def parse_holders(html: str) -> list[dict]:
    m = re.search(r'(?s)<table class="stock_holder_1".*?</table>', html)
    if not m:
        return []
    rows = []
    for tr in re.findall(r"(?s)<tr[^>]*>(.*?)</tr>", m.group(0)):
        cells = [re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", "", c)).replace("&nbsp;", "").strip()
                 for c in re.findall(r"(?s)<t[dh][^>]*>(.*?)</t[dh]>", tr)]
        cells = [c for c in cells if c != ""]
        if len(cells) < 3:
            continue
        name, pct = cells[0], None
        for c in cells[1:]:
            try:
                pct = float(c)
                break
            except ValueError:
                continue
        if pct is None or name in ("株主名",):
            continue
        rows.append({"name": name, "pct": pct})
    return rows


def fetch_float_ratio(code: str, use_cache: bool = True) -> dict:
    """大株主上位10名から浮動株比率を推計する。

    浮動株比率 ≒ 1 - Σ(非浮動とみなした大株主の比率)
    上位10名しか見えないため、11位以下に潜む政策保有株は拾えない(=過大推計になりうる)。
    キャッシュには生の大株主リストを保存し、比率は毎回引き直すので、
    分類パターンを直したら再取得なしで反映される。
    """
    p = CACHE / "float" / f"{code}.json"
    if use_cache and p.exists():
        holders = json.loads(p.read_text(encoding="utf-8")).get("holders", [])
    else:
        holders = parse_holders(fetch(f"https://kabutan.jp/stock/holder?code={code}"))

    nonfloat, detail = classify_holders(holders)
    ratio = max(0.05, min(1.0, 1.0 - nonfloat / 100.0)) if holders else None
    out = {"code": code, "ratio": ratio, "nonfloat_pct": round(nonfloat, 2),
           "holders": holders, "nonfloat": detail}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out



# --------------------------------------------------- 母集団から除外される銘柄

def _jpx_tables(url: str) -> list[tuple[str, list[list[str]]]]:
    """JPXのページを (直前の見出し, 行) の並びで返す。"""
    h = fetch(url)
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
    out, head = [], ""
    for m in re.finditer(r"(?s)(<h[1-4][^>]*>.*?</h[1-4]>)|(<table.*?</table>)", h):
        if m.group(1):
            head = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
            continue
        rows = []
        for tr in re.findall(r"(?s)<tr[^>]*>(.*?)</tr>", m.group(2)):
            c = [re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", "", x)).replace("&nbsp;", " ").strip()
                 for x in re.findall(r"(?s)<t[dh][^>]*>(.*?)</t[dh]>", tr)]
            c = [x for x in c if x]
            if c:
                rows.append(c)
        out.append((head, rows))
    return out


def _codes(rows: list[list[str]], on_or_before: str | None = None) -> dict[str, str]:
    """行から {コード: 指定日} を拾う。on_or_before を渡すとその日以前の指定だけ返す。"""
    out = {}
    for c in rows:
        d = next((x for x in c if re.fullmatch(r"20\d\d/\d\d/\d\d", x)), None)
        code = next((x for x in c if re.fullmatch(r"[0-9][0-9A-Z]{3}", x)), None)
        if not code:
            continue
        ymd = d.replace("/", "") if d else ""
        if on_or_before and ymd and ymd > on_or_before:
            continue
        out[code] = d or ""
    return out


def fetch_ineligible(use_cache: bool = True) -> dict:
    """定期入替基準日時点で母集団から除外される銘柄を JPX から取る。

    算出要領 Ⅱ-3-(1)-b-(a) より、母集団から除外されるのは
      ・基準日において整理銘柄に指定されている銘柄
      ・基準日において特別注意銘柄に指定されている銘柄
    の2つのみ。監理銘柄は除外対象ではないが、「指定されることが見込まれる銘柄は
    基準日から入替日までの状況も勘案することがある」とされているため、警告用に拾っておく。
    """
    p = CACHE / "ineligible.json"
    if use_cache and p.exists():
        return json.loads(p.read_text(encoding="utf-8"))

    alert, seiri, kanri = {}, {}, {}
    for head, rows in _jpx_tables("https://www.jpx.co.jp/listing/measures/alert/index.html"):
        if "指定状況" in head or not alert:
            alert.update(_codes(rows, BASE_DATE))
    for head, rows in _jpx_tables("https://www.jpx.co.jp/listing/market-alerts/supervision/index.html"):
        if head.startswith("整理銘柄"):
            seiri.update(_codes(rows, BASE_DATE))
        elif head.startswith("監理銘柄"):
            kanri.update(_codes(rows, BASE_DATE))

    out = {"alert": alert, "seiri": seiri, "kanri": kanri,
           "ineligible": sorted(set(alert) | set(seiri))}
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
