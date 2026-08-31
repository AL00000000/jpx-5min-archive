/* TOPIX定期入替(2026年10月)の採用/除外 推計ビュー */
const OKU = 1e8;
const fmtOku = v => v == null ? "－" : (v / OKU >= 10000
  ? (v / 1e12).toFixed(2).replace(/\.?0+$/, "") + "兆円"
  : Math.round(v / OKU).toLocaleString() + "億円");
const fmtNum = (v, d = 2) => v == null ? "－" : v.toFixed(d);
const esc = t => String(t == null ? "" : t).replace(/[&<>"]/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let RB = null;
let tabState = "add";
const sortState = {
  add:  { k: "float_mktcap", asc: true },
  out:  { k: "float_mktcap", asc: false },
  keep: { k: "float_mktcap", asc: true }
};

function barHtml(v, th) {
  if (v == null || !th) return "";
  const p = Math.max(0, Math.min(1, v / th / 1.5));
  return '<div class="bar"><i class="' + (v >= th ? "" : "ng") +
    '" style="width:' + (p * 100).toFixed(1) + '%"></i></div>';
}

const COLS = {
  add: [
    { k: "code",   t: "コード", l: 1, f: r => '<span class="cd">' + esc(r.code) + "</span>" },
    { k: "name",   t: "銘柄名", l: 1, f: r => '<span class="nm">' + esc(r.name) + "</span>" },
    { k: "market", t: "市場",   l: 1, f: r => esc(r.market) +
        (r.kanri ? ' <span class="pill near" title="監理銘柄">監理</span>' : "") },
    { k: "mktcap", t: "時価総額", f: r => fmtOku(r.mktcap) },
    { k: "float_ratio", t: "推定浮動株比率",
      f: r => r.float_ratio == null ? "－" : (r.float_ratio * 100).toFixed(1) + "%" +
        (r.float_ratio_raw ? '<span class="cd"> (大株主 ' + (r.float_ratio_raw * 100).toFixed(0) + "%)</span>" : "") },
    { k: "float_mktcap", t: "浮動株時価総額",
      f: r => fmtOku(r.float_mktcap) + barHtml(r.float_mktcap, RB.meta.t96) },
    { k: "turnover", t: "年間回転率", f: r => fmtNum(r.turnover) + barHtml(r.turnover, 0.20) },
    { k: "add", t: "判定", f: r => r.add
        ? '<span class="pill in">採用</span>'
        : '<span class="pill out">見送り</span> <span class="cd">' + esc((r.fail || []).join("・")) + "</span>" }
  ],
  out: [
    { k: "code", t: "コード", l: 1, f: r => '<span class="cd">' + esc(r.code) + "</span>" },
    { k: "name", t: "銘柄名", l: 1, f: r => '<span class="nm">' + esc(r.name) + "</span>" +
        (r.kanri ? ' <span class="pill near" title="監理銘柄。整理銘柄に指定されれば母集団から外れる">監理</span>' : "") },
    { k: "sector", t: "業種", l: 1, f: r => esc(r.sector) },
    { k: "size", t: "規模区分", l: 1, f: r => esc(r.size) },
    { k: "weight", t: "TOPIXウエイト", f: r => r.weight == null ? "－" : r.weight.toFixed(4) + "%" },
    { k: "float_mktcap", t: "浮動株時価総額",
      f: r => fmtOku(r.float_mktcap) + barHtml(r.float_mktcap, RB.meta.t97) },
    { k: "turnover", t: "年間回転率", f: r => fmtNum(r.turnover) + barHtml(r.turnover, 0.14) },
    { k: "fail", t: "不足している基準", l: 1, f: r => (r.fail || []).length
        ? '<span class="pill out">' + esc(r.fail.join("・")) + "</span>"
        : '<span class="pill in">継続</span>' }
  ]
};
COLS.keep = COLS.out;

function estCards() {
  const m = RB.meta;
  const c = (t, v, s2, cls) => '<div class="card"><div class="ttl">' + t + '</div><div class="val ' +
    (cls || "") + '">' + v + "</div>" + (s2 ? '<div class="sub2">' + s2 + "</div>" : "") + "</div>";
  return '<div class="cards">' +
    c("基準日", "8/31", "この日で全データ確定", "ok") +
    c("選定結果の公表", "10/07", "JPXサイト・10月第5営業日") +
    c("入替実施", "10/30", "10月最終営業日") +
    c("継続の足切り<br>(累積97%以内)", fmtOku(m.t97), "浮動株時価総額") +
    c("追加の足切り<br>(累積96%以内)", fmtOku(m.t96), "浮動株時価総額") +
    c("除外の推計", m.n_excluded + "銘柄", "現構成 " + m.n_members + " のうち", "warn") +
    c("新規採用の推計", m.n_added + "銘柄", "候補 " + m.n_candidates + " のうち", "ok") +
    c("次期TOPIX", (m.n_keep + m.n_added) + "銘柄", "JPX試算は約1,050") +
    "</div>";
}

function rowsFor(tab) {
  if (tab === "add") {
    const cb = document.getElementById("showMiss");
    return cb && cb.checked ? RB.added.concat(RB.missed) : RB.added;
  }
  if (tab === "out") return RB.excluded;
  return RB.kept;
}

function renderTable() {
  const cols = COLS[tabState], st = sortState[tabState];
  const box = document.getElementById("estq");
  const q = (box ? box.value : "").trim().toLowerCase();
  let rows = rowsFor(tabState).slice();
  if (q) rows = rows.filter(r => (r.code + " " + r.name).toLowerCase().indexOf(q) >= 0);
  rows.sort((a, b) => {
    let x = a[st.k], y = b[st.k];
    if (Array.isArray(x)) x = x.join("・");
    if (Array.isArray(y)) y = y.join("・");
    if (x == null) x = typeof y === "number" ? -Infinity : "";
    if (y == null) y = typeof x === "number" ? -Infinity : "";
    if (x < y) return st.asc ? -1 : 1;
    if (x > y) return st.asc ? 1 : -1;
    return 0;
  });
  const head = "<tr>" + cols.map(c => '<th class="' + (c.l ? "l" : "") + '" data-k="' + c.k + '">' +
    c.t + (st.k === c.k ? (st.asc ? " ▲" : " ▼") : "") + "</th>").join("") + "</tr>";
  const body = rows.map(r => "<tr>" + cols.map(c =>
    '<td class="' + (c.l ? "l" : "") + '">' + c.f(r) + "</td>").join("") + "</tr>").join("");
  document.getElementById("estTable").innerHTML =
    '<table class="grid"><thead>' + head + "</thead><tbody>" + body + "</tbody></table>";
  document.getElementById("estCount").textContent = rows.length + "銘柄";
  document.querySelectorAll("#estTable th").forEach(th => {
    th.onclick = () => {
      const k = th.dataset.k;
      if (st.k === k) st.asc = !st.asc;
      else { st.k = k; st.asc = (k === "code" || k === "name"); }
      renderTable();
    };
  });
}

function renderEst() {
  const m = RB.meta;
  const tabs = [["add", "新規採用の候補"], ["out", "除外の候補"], ["keep", "継続する銘柄"]];
  document.getElementById("view-est").innerHTML =
    estCards() +
    '<div class="note"><b class="warn">これはJPXの公表値ではなく当サイトの推計です。</b> ' +
    "確定した選定結果は <b>2026年10月7日(水)</b> にJPXが公表します。" +
    "選定に使うデータ自体は<b>2026年8月31日の大引けで確定済み</b>で、以後の株価・出来高は結果を動かしません" +
    "（基準日から入替日までの整理銘柄・特別注意銘柄の指定は勘案されることがあります）。<br>" +
    "除外された銘柄はすぐ指数から消えるのではなく、<b>2026年10月末の×0.875を皮切りに四半期ごと8段階でウエイトが下がり、2028年7月末に×0</b>になります" +
    "（2027年8月末を基準とした再評価で継続基準を満たせば×0.500で低減が止まります）。</div>" +
    '<details class="method"><summary>計算方法と精度（必ずお読みください）</summary><div class="body">' +
    'JPX総研「TOPIX算出要領」の定義どおりに計算しています。<br>' +
    "<b>追加基準</b>　年間売買代金回転率 0.2以上 かつ 浮動株時価総額の累積比率 上位96%以内<br>" +
    "<b>継続基準</b>　年間売買代金回転率 0.14以上 かつ 同 上位97%以内<br>" +
    "追加のほうが厳しいので、<b>" + fmtOku(m.t97) + "〜" + fmtOku(m.t96) + "の帯は「今いる銘柄は残れるが、外の銘柄は入れない」緩衝地帯</b>になります" +
    "（入れ替わりを減らすためのヒステリシス）。この帯に現構成銘柄が" + (m.n_band_keep || 0) + "銘柄、" +
    "あと一歩で採用だった候補が" + (m.n_band_miss || 0) + "銘柄います。<br>" +
    "<b>浮動株時価総額</b>＝基準日が属する月（2026年8月）の<b>日次平均</b>。単日の終値ではありません。<br>" +
    "<b>年間売買代金回転率</b>＝2025年9月〜2026年8月の月次回転率の合計。" +
    "月次＝(日次売買代金の中央値 × 営業日数) ÷ 月末最終営業日の浮動株時価総額。<br><br>" +
    "<b>現構成銘柄の浮動株時価総額は精度が高い</b>です。JPXが公開しているTOPIXウエイト（" +
    esc(m.weight_date || "") + "時点）から浮動株株数を逆算し、JPX資料の公表値" +
    "（浮動株時価総額の合計 691兆円 @ TOPIX 3,644.58pt）で絶対額に換算しています。" +
    "株探の日足から計算した2026年3月のTOPIX月間平均は <b>" + fmtNum(m.topix_mar_avg) +
    "pt</b> となり、JPX公表の3,644.58ptと一致しました。<br>" +
    "足切り値もJPXの公表値（累積97%以内の最小浮動株時価総額＝約360億円 @2026年3月末）を" +
    "8月の指数水準に換算した <b>" + fmtOku(m.t97) + "</b> を基準にしています" +
    "（自前計算では " + fmtOku(m.t97_self) + "、補正 ×" + fmtNum(m.calib, 3) + "）。<br><br>" +
    "<b>母集団から外れる銘柄</b>　基準日に<b>整理銘柄</b>または<b>特別注意銘柄</b>に指定されている銘柄は" +
    "母集団から除外されます（監理銘柄は除外対象ではありません）。JPXの一覧から自動で取り込んでおり、" +
    "今回は" + Object.keys(m.ineligible || {}).length + "銘柄が該当します。" +
    "たとえば<b>ニデック(6594)</b>と<b>エア・ウォーター(4088)</b>は浮動株時価総額だけ見れば余裕で基準を満たしますが、" +
    "いずれも特別注意銘柄のため今回は採用されません。<br><br>" +
    '<b class="warn">新規採用側は誤差が大きいです。</b>浮動株比率はJPXしか持っていない非公開データなので、' +
    "株探の大株主上位10名から「親会社・事業会社・創業家・自己株式・持株会」を非浮動として差し引いた推計値を使っています。" +
    "ただし上位10名しか見えず11位以下の政策保有株を拾えないため、この推計は<b>系統的に過大</b>に出ます。<br>" +
    "そこで現構成銘柄" + (m.n_calib_sample || 0) + "銘柄について「ウエイトから逆算した浮動株比率（ほぼ正解）」と" +
    "「大株主から推計した浮動株比率」を突き合わせ、その比の中央値 <b>×" + fmtNum(m.float_calib, 3) +
    "</b> を候補銘柄の浮動株比率に掛けて補正しています（表の括弧内が補正前の生の値）。" +
    "それでも銘柄ごとのブレは残るので、当落線上の銘柄は参考程度に見てください。<br>" +
    "候補の母集団は「非TOPIX・時価総額350億円超」の" + m.n_candidates +
    "銘柄です。それ未満の銘柄からの採用は拾えません。" +
    "</div></details>" +
    '<nav class="subtabs" id="estTabs">' + tabs.map(([k, t]) =>
      '<button class="stab' + (k === tabState ? " active" : "") + '" data-t="' + k + '">' + t + "</button>"
    ).join("") + "</nav>" +
    '<div class="filterrow"><input id="estq" type="search" placeholder="銘柄名・コードで絞り込み">' +
    '<label style="cursor:pointer"><input type="checkbox" id="showMiss"> 見送りの候補も表示</label>' +
    '<span class="cnt" id="estCount"></span></div>' +
    '<div class="tablewrap" id="estTable"></div>';

  document.querySelectorAll("#estTabs .stab").forEach(b => {
    b.onclick = () => {
      tabState = b.dataset.t;
      document.querySelectorAll("#estTabs .stab").forEach(x => x.classList.toggle("active", x === b));
      renderTable();
    };
  });
  document.getElementById("estq").oninput = renderTable;
  document.getElementById("showMiss").onchange = renderTable;
  renderTable();
}

async function initEst() {
  try {
    const r = await fetch("data/rebalance.json?" + Date.now());
    if (!r.ok) throw new Error("HTTP " + r.status);
    RB = await r.json();
    renderEst();
  } catch (e) {
    document.getElementById("view-est").innerHTML =
      '<div class="note"><b class="warn">推計データを読み込めませんでした</b><br>' + esc(e.message) + "</div>";
  }
}

document.querySelectorAll("nav.subtabs .stab[data-view]").forEach(b => {
  b.onclick = () => {
    document.querySelectorAll("nav.subtabs .stab[data-view]").forEach(
      x => x.classList.toggle("active", x === b));
    document.getElementById("view-est").hidden = b.dataset.view !== "est";
    document.getElementById("view-chart").hidden = b.dataset.view !== "chart";
  };
});
initEst();
