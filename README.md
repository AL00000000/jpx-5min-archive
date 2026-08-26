# 5分足アーカイブ (jpx-5min-archive)

非TOPIX・時価総額350億円超の211銘柄について、株探の5分足を毎営業日蓄積している。

**📊 閲覧用サイト: https://al00000000.github.io/jpx-5min-archive/**
(銘柄検索・表示日数切替つきのローソク足+出来高チャート。
[売買代金ランキング/その他](https://al00000000.github.io/kabutan-ranking/) の「5分足」タブからも開ける)

## 構成

- `symbols.csv` … 対象銘柄リスト(コード,銘柄名,市場,株価,時価総額)。銘柄を増減したい場合はこれを編集する
- `fetch_5min.py` … 取得スクリプト(Python標準ライブラリのみ)
- `docs/data/YYYY-MM-DD.json.gz` … その日の全銘柄の5分足
- `docs/data/manifest.json` … 保存済み日付一覧と銘柄マスタ
- `docs/index.html` … 閲覧サイト
- `logs/` … 実行ログ(gitには含めない)

## データ形式

`docs/data/YYYY-MM-DD.json.gz` を gzip 展開すると:

```json
{"date":"2026-08-26","generated":"...","bars":{"6594":[["09:00",2590.0,2622.0,2586.0,2602.0,320400], ...]}}
```

1本 = `[時刻, 始値, 高値, 安値, 終値, 出来高]`。1日67本(9:00〜15:25の66本 + 15:30の引け)。

Pythonでの読み込み例:

```python
import gzip, json

with gzip.open("docs/data/2026-08-26.json.gz", "rt", encoding="utf-8") as f:
    day = json.load(f)

bars = day["bars"]["6594"]          # ニデックの5分足
close = bars[-1][4]                 # 終値
volume = sum(b[5] for b in bars)    # 出来高合計
```

## 自動実行

Windowsタスクスケジューラ `\StockAutomation\jpx-5min-archive`(平日16:55)。
実体は `C:\Users\yt\automation\run_task.py` + `tasks.json` の汎用ランナーで、
取得からgit pushまで無人で完遂する。

```
py fetch_5min.py                                          # 手動取得
py C:\Users\yt\automation\run_task.py jpx-5min-archive --check   # 事前チェック
py -m http.server 8647 --directory docs                   # ローカル閲覧
```

## 仕様上の注意

- 株探の5分足エンドポイント(`stock/read?c=<code>&m=5&k=1`)は**直近5営業日分**を返す。
  そのため取得に失敗した日やPCが落ちていた日があっても、**4営業日以内に実行すれば自動で埋め戻る**
  (既存ファイルにマージする実装になっている)。
- `m` が足種。1=日足 / 2=週足 / 3=月足 / 4=1分足 / 5=5分足 / 6=年足。`k` は効かない。
- レスポンス1行目の2列目は**市場コード**(0=指数, 1=東証, 3=名証, 6=福証, 8=札証)。
  「0か1のみ有効」と判定すると名証・福証・札証の銘柄が丸ごと欠落するので注意。
  株価の除数は指数のみ100、それ以外は全市場10。
- 2763(エフティグループ)と3271(THEグローバル社)は上場廃止済みでデータが返らない。

## 注意

データの取得元は株探(kabutan.jp)です。データの正確性は保証しません。
投資判断は自己責任でお願いします。市場休場日は更新されません。
