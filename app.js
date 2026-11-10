"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d = 0) => (v == null || !isFinite(v) ? "–" : Number(v).toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d }));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

const CATS = {
  A: "매도 소진", B: "과매도·다이버전스", C: "바닥 패턴·전환", D: "수급",
  E: "가치 바닥", F: "내부자·자사주", G: "실적 바닥",
};
const SHORT = { A: "소진", B: "과매도", C: "패턴", D: "수급", E: "가치", F: "내부자", G: "실적" };
const STAGE = { 0: "해당 없음", 1: "① 과매도", 2: "② 바닥 형성", 3: "③ 전환 확인" };
const TABS = ["3", "2", "1", "all", "rules"];
const S = { tab: "3", D: null, items: [], byCode: {}, max: {}, catMax: {} };

/* ---------- 목록 ---------- */

function catMax(W) {
  const m = {};
  for (const [k, v] of Object.entries(W)) m[k[0]] = (m[k[0]] || 0) + v;
  return m;
}

function sinceText(it, asof) {
  if (!it.stage) return "";
  const a = new Date(asof), s = new Date(`${it.since.slice(0, 4)}-${it.since.slice(4, 6)}-${it.since.slice(6)}`);
  let n = 0;
  for (let d = new Date(s); d <= a; d.setDate(d.getDate() + 1)) if (d.getDay() % 6) n++;
  return `${STAGE[it.stage].slice(0, 1)} ${n <= 1 ? "오늘 진입" : n + "일째"}`;
}

function sounding(it, withKey = false) {
  const na = S.D.meta.na || {};
  const segs = Object.keys(CATS).map((c) => {
    const mx = S.catMax[c] || 1, v = it.cats[c] || 0;
    const allNa = Object.entries(it.subs).filter(([k]) => k[0] === c).every(([, s]) => s[0] == null);
    return `<span class="seg${allNa ? " na" : ""}" style="flex:${mx}" title="${CATS[c]} ${fmt(v, 1)}/${mx}"><b style="width:${Math.min(100, (v / mx) * 100)}%"></b></span>`;
  }).join("");
  const key = withKey ? `<div class="sound-key">${Object.keys(CATS).map((c) => `<span style="flex:${S.catMax[c]}">${SHORT[c]}</span>`).join("")}</div>` : "";
  return `<div class="sound" aria-hidden="true">${segs}</div>${key}`;
}

function topChips(it, n = 3) {
  const names = S.D.meta.items;
  return Object.entries(it.subs)
    .filter(([, s]) => s[0] > 0)
    .sort((a, b) => b[1][0] / S.max[b[0]] - a[1][0] / S.max[a[0]] || b[1][0] - a[1][0])
    .slice(0, n)
    .map(([k]) => `<span>${esc(names[k][1])}</span>`)
    .join("");
}

function card(it) {
  const chg = it.chg > 0 ? "up" : it.chg < 0 ? "down" : "";
  const pen = it.pen.length ? `<div class="pen">감점 ${fmt(it.pen.reduce((a, p) => a + p[1], 0))} ${it.pen.map((p) => esc(p[0])).join(", ")}</div>` : "";
  const st = it.stage ? `<span class="since s${it.stage}">${sinceText(it, S.D.meta.asof)}</span>` : "";
  return `<li><button class="card" data-code="${it.code}" aria-label="${esc(it.name)} ${fmt(it.score, 1)}점 상세 보기">
    <div class="row"><div><span class="nm">${esc(it.name)}</span><span class="cd">${it.code}</span></div>
      <div class="sc">${fmt(it.score, 1)}<small>/100</small></div></div>
    <div class="facts">${st}<span>${fmt(it.close)}원 <span class="${chg}">${it.chg > 0 ? "+" : ""}${fmt(it.chg, 2)}%</span></span>
      <span>60일 저점 +${fmt(it.low60, 1)}%</span><span>시총 ${it.rank}위</span></div>
    ${sounding(it)}
    <div class="chips">${topChips(it)}</div>${pen}
  </button></li>`;
}

function renderLists() {
  for (const s of [3, 2, 1]) {
    const xs = S.items.filter((i) => i.stage === s);
    $(`#n${s}`).textContent = xs.length;
    $(`#l${s}`).innerHTML = xs.length ? xs.map(card).join("")
      : `<li class="empty">지금 ${STAGE[s]} 단계 종목이 없습니다.${s > 1 ? ` <br><button data-go="${s - 1}">${STAGE[s - 1]} 보기</button>` : ""}</li>`;
  }
  const key = `<div class="sound">${Object.keys(CATS).map((c) => `<span class="seg" style="flex:${S.catMax[c]}"></span>`).join("")}</div><div class="sound-key">${Object.keys(CATS).map((c) => `<span style="flex:${S.catMax[c]}">${SHORT[c]}</span>`).join("")}</div>`;
  $$(".key-strip").forEach((k) => { k.innerHTML = key; k.title = "카드 막대는 왼쪽부터 이 순서, 폭은 배점 비중입니다"; });
  renderAll();
}

function renderAll() {
  const q = $("#q").value.trim().toLowerCase(), by = $("#sort").value;
  let xs = S.items.filter((i) => !q || i.name.toLowerCase().includes(q) || i.code.includes(q));
  xs = [...xs].sort((a, b) => by === "mcap" ? a.rank - b.rank : by === "low60" ? a.low60 - b.low60 : b.score - a.score);
  $("#lall").innerHTML = xs.length ? xs.map(card).join("") : `<li class="empty">'${esc(q)}'와 맞는 종목이 없습니다. 후보군에서 빠진 종목은 기준 탭의 제외 목록에 있습니다.</li>`;
}

/* ---------- 상세 ---------- */

async function openDetail(code) {
  const it = S.byCode[code];
  if (!it) return;
  $("#detail").innerHTML = detailHtml(it, null);
  $("#sheet").hidden = false;
  document.body.style.overflow = "hidden";
  history.pushState({ d: code }, "", "#" + code);
  $("#close").focus();
  try {
    const r = await fetch(`data/charts/${code}.json?t=${S.D.meta.updated}`);
    if (!r.ok) throw new Error(r.status);
    const ch = await r.json();
    $("#chart-box").innerHTML = chartSvg(ch);
    bindChart(ch);
  } catch (e) {
    $("#chart-box").innerHTML = `<p class="empty">차트 자료를 불러오지 못했습니다(${esc(e.message)}). 연결을 확인한 뒤 다시 열어 주세요.</p>`;
  }
}

function closeDetail(fromPop = false) {
  if ($("#sheet").hidden) return;
  $("#sheet").hidden = true;
  document.body.style.overflow = "";
  hideTip();
  if (!fromPop && location.hash) history.back();
}

function detailHtml(it) {
  const names = S.D.meta.items;
  const stageNote = {
    0: "과매도 조건(최근 20일 RSI 30 이하 또는 60일 이격도 90 이하)에 아직 들지 않았습니다.",
    1: "과매도 구간입니다. 매도 소진이나 다이버전스, 10거래일 신저가 없음이 확인되면 ②로 넘어갑니다.",
    2: "바닥을 다지는 중입니다. 패턴 돌파나 20일선 회복과 외국인·기관 순매수가 함께 나오면 ③으로 넘어갑니다.",
    3: "전환이 확인됐습니다. 저점 대비 이미 오른 만큼 손절 기준(최근 저점)을 함께 보세요.",
  }[it.stage];
  const cats = Object.keys(CATS).map((c) => {
    const subs = Object.entries(it.subs).filter(([k]) => k[0] === c);
    const mx = S.catMax[c], v = it.cats[c] || 0;
    return `<section class="cat"><div class="cat-h"><span>${CATS[c]}</span><small>${fmt(v, 1)} / ${mx}</small></div>
      <div class="meter"><b style="width:${(v / mx) * 100}%"></b></div>
      ${subs.map(([k, s]) => `<div class="sub-i${s[0] == null ? " na" : ""}"><span>${esc(names[k][1])}</span>
        <span class="pt${!s[0] ? " zero" : ""}">${s[0] == null ? "미수집" : fmt(s[0], 1)} <small>/ ${S.max[k]}</small></span>
        <span class="nt">${esc(s[1])}</span></div>`).join("")}</section>`;
  }).join("");
  const pen = it.pen.length ? `<section class="cat penbox"><div class="cat-h"><span>감점</span><small>${fmt(it.pen.reduce((a, p) => a + p[1], 0))} (최대 ${S.D.meta.penalties.cap})</small></div>
    ${it.pen.map((p) => `<div class="sub-i"><span>${esc(p[0])}</span><span class="pt">${p[1]}</span><span class="nt">${esc(p[2])}</span></div>`).join("")}</section>` : "";
  return `<div class="d-top"><div><h2 id="d-name">${esc(it.name)}</h2><div class="cd">${it.code} · 코스피 시총 ${it.rank}위 · ${fmt(it.mcap / 10000, 1)}조</div>
      <div class="links"><a href="https://finance.naver.com/item/main.naver?code=${it.code}" target="_blank" rel="noopener">네이버 증권</a>
      <a href="https://dart.fss.or.kr/dsab001/main.do?textCrpNm=${encodeURIComponent(it.name)}" target="_blank" rel="noopener">DART 공시</a></div></div>
    <div class="d-score"><div class="sc">${fmt(it.score, 1)}</div><small>100점 중${it.pen.length ? `, 감점 전 ${fmt(it.raw, 1)}` : ""}</small></div></div>
    <div class="steps">${[1, 2, 3].map((s) => `<div class="k${s}${it.stage >= s ? " on" : ""}">${STAGE[s]}</div>`).join("")}</div>
    <p class="stage-note">${it.stage ? `<b>${sinceText(it, S.D.meta.asof)}.</b> ` : ""}${stageNote}</p>
    ${sounding(it, true)}
    <div class="chart" id="chart-box"><p class="empty">차트를 불러오는 중…</p></div>
    ${pen}${cats}`;
}

/* ---------- 차트 ---------- */

const CW = 360, PH = 170, VH = 36, RH = 58, GAP = 10, PADL = 4, PADR = 44;

function chartSvg(ch) {
  const n = ch.c.length, xs = (i) => PADL + (i / (n - 1)) * (CW - PADL - PADR);
  const vals = [...ch.l, ...ch.h, ...ch.ma20, ...ch.ma60].filter((v) => v != null);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.06; lo -= pad; hi += pad;
  const ys = (v) => 8 + (1 - (v - lo) / (hi - lo)) * (PH - 16);
  const line = (a, col, w = 1.6, dash = "") => {
    let d = "", on = false;
    a.forEach((v, i) => { if (v == null) { on = false; return; } d += `${on ? "L" : "M"}${xs(i).toFixed(1)},${ys(v).toFixed(1)}`; on = true; });
    return `<path d="${d}" fill="none" stroke="${col}" stroke-width="${w}" ${dash ? `stroke-dasharray="${dash}"` : ""} stroke-linejoin="round"/>`;
  };
  const ink = css("--ink"), muted = css("--muted"), deep = css("--deep"), s2 = css("--s2"), s1 = css("--s1"), up = css("--up"), down = css("--down"), line_ = css("--line");
  const ticks = [lo + (hi - lo) * 0.15, (lo + hi) / 2, hi - (hi - lo) * 0.15];
  let g = ticks.map((t) => `<line x1="${PADL}" x2="${CW - PADR}" y1="${ys(t)}" y2="${ys(t)}" stroke="${line_}" stroke-width="0.6"/>
    <text x="${CW - PADR + 4}" y="${ys(t) + 3.5}" font-size="9.5" fill="${muted}">${fmt(t)}</text>`).join("");
  // 캔들
  const bw = Math.max(1, ((CW - PADL - PADR) / n) * 0.62);
  g += ch.c.map((c, i) => {
    const o = ch.o[i], col = c >= o ? up : down, x = xs(i);
    return `<line x1="${x}" x2="${x}" y1="${ys(ch.h[i])}" y2="${ys(ch.l[i])}" stroke="${col}" stroke-width="0.7" opacity="0.75"/>
      <rect x="${x - bw / 2}" y="${ys(Math.max(o, c))}" width="${bw}" height="${Math.max(0.8, Math.abs(ys(o) - ys(c)))}" fill="${col}" opacity="0.75"/>`;
  }).join("");
  g += line(ch.bb, muted, 1, "3 3") + line(ch.ma60, s1, 1.4) + line(ch.ma20, s2, 1.4);
  // 신호 표시
  const byPos = {};
  for (const [p, k] of ch.marks) (byPos[p] = byPos[p] || []).push(k);
  g += Object.entries(byPos).map(([p, ks]) => {
    const x = xs(+p), y = ys(ch.l[+p]) + 10;
    return `<g><circle cx="${x}" cy="${y}" r="3.2" fill="${deep}"/><text x="${x}" y="${y + 12}" font-size="8.5" text-anchor="middle" fill="${deep}" font-weight="700">${ks.join(" ")}</text></g>`;
  }).join("");
  // 거래량
  const vy = PH + GAP, vmax = Math.max(...ch.v);
  g += ch.v.map((v, i) => { const h = (v / vmax) * VH; return `<rect x="${xs(i) - bw / 2}" y="${vy + VH - h}" width="${bw}" height="${h}" fill="${muted}" opacity="0.45"/>`; }).join("");
  g += `<text x="${CW - PADR + 4}" y="${vy + 10}" font-size="9.5" fill="${muted}">거래량</text>`;
  // RSI
  const ry = vy + VH + GAP, rys = (v) => ry + (1 - v / 100) * RH;
  g += `<rect x="${PADL}" y="${rys(30)}" width="${CW - PADL - PADR}" height="${rys(0) - rys(30)}" fill="${deep}" opacity="0.08"/>`;
  g += [30, 70].map((t) => `<line x1="${PADL}" x2="${CW - PADR}" y1="${rys(t)}" y2="${rys(t)}" stroke="${line_}" stroke-width="0.6"/><text x="${CW - PADR + 4}" y="${rys(t) + 3.5}" font-size="9.5" fill="${muted}">${t}</text>`).join("");
  let d = "", on = false;
  ch.rsi.forEach((v, i) => { if (v == null) { on = false; return; } d += `${on ? "L" : "M"}${xs(i).toFixed(1)},${rys(v).toFixed(1)}`; on = true; });
  g += `<path d="${d}" fill="none" stroke="${ink}" stroke-width="1.3"/><text x="${PADL + 2}" y="${ry + 9}" font-size="9.5" fill="${muted}">RSI(14)</text>`;
  const dl = (s) => `${s.slice(4, 6)}/${s.slice(6)}`;
  g += `<text x="${PADL}" y="${ry + RH + 13}" font-size="9.5" fill="${muted}">${dl(ch.d[0])}</text><text x="${CW - PADR}" y="${ry + RH + 13}" font-size="9.5" fill="${muted}" text-anchor="end">${dl(ch.d[n - 1])}</text>`;
  g += `<line id="cur" x1="0" x2="0" y1="0" y2="${ry + RH}" stroke="${ink}" stroke-width="0.7" opacity="0"/>`;
  const H = ry + RH + 18;
  return `<svg viewBox="0 0 ${CW} ${H}" role="img" aria-label="최근 ${n}거래일 주가, 거래량, RSI 차트">${g}<rect id="hit" x="0" y="0" width="${CW}" height="${H}" fill="transparent"/></svg>
    <div class="legend"><span><i style="background:${s2}"></i>20일선</span><span><i style="background:${s1}"></i>60일선</span>
    <span><i style="background:${muted}"></i>볼린저 하단</span><span><i style="background:${deep};height:6px;width:6px;border-radius:50%"></i>신호 발생일(항목 기호)</span></div>`;
}

function bindChart(ch) {
  const svg = $("#chart-box svg"), cur = $("#cur", svg), n = ch.c.length;
  const move = (e) => {
    const r = svg.getBoundingClientRect(), vx = ((e.clientX - r.left) / r.width) * CW;
    const i = Math.max(0, Math.min(n - 1, Math.round(((vx - PADL) / (CW - PADL - PADR)) * (n - 1))));
    const x = PADL + (i / (n - 1)) * (CW - PADL - PADR);
    cur.setAttribute("x1", x); cur.setAttribute("x2", x); cur.setAttribute("opacity", 0.5);
    const d = ch.d[i], mk = ch.marks.filter((m) => m[0] === i).map((m) => S.D.meta.items[m[1]][1]);
    showTip(e.clientX, r.top, `${d.slice(0, 4)}.${d.slice(4, 6)}.${d.slice(6)} 종가 ${fmt(ch.c[i])} · RSI ${fmt(ch.rsi[i], 0)}${mk.length ? "<br>" + mk.map(esc).join(", ") : ""}`);
  };
  svg.addEventListener("pointermove", move);
  svg.addEventListener("pointerdown", move);
  svg.addEventListener("pointerleave", () => { cur.setAttribute("opacity", 0); hideTip(); });
}

function showTip(x, y, html) {
  const t = $("#tip");
  t.innerHTML = html; t.hidden = false;
  const w = t.offsetWidth;
  t.style.left = Math.max(6, Math.min(innerWidth - w - 6, x - w / 2)) + "px";
  t.style.top = Math.max(6, y - t.offsetHeight - 6) + "px";
}
function hideTip() { $("#tip").hidden = true; }

/* ---------- 기준 ---------- */

function renderRules() {
  const m = S.D.meta, W = m.weights, U = m.universe_cfg, P = m.penalties;
  const rows = Object.keys(CATS).map((c) => {
    const subs = Object.keys(W).filter((k) => k[0] === c);
    return `<tr class="cat-row"><td>${CATS[c]}</td><td class="r">${S.catMax[c]}</td></tr>` +
      subs.map((k) => `<tr><td>${esc(m.items[k][1])}${(m.na[k] || k === "D2") ? " <small class=\"err\">미수집</small>" : ""}</td><td class="r">${W[k]}</td></tr>`).join("");
  }).join("");
  const exByWhy = {};
  for (const e of m.excluded) (exByWhy[e.why.replace(/\(.*\)/, "").replace(/\d.*$/, "").trim()] ||= []).push(e);
  $("#rules").innerHTML = `
    <h3>후보군</h3>
    <p>코스피 보통주 시가총액 상위 ${U.top_n}개(우선주·스팩·리츠 제외)에서 관리종목, 거래정지, 투자경고·위험, 1년 내 불성실공시법인 지정, 감사의견 비적정, 자본잠식, 최근 3년 중 영업흑자 ${U.min_profit_years_of_3}년 미만, 이자보상배율 ${U.min_interest_coverage}배 이하, 20일 평균 거래대금 ${U.min_trading_value_eok}억 미만을 뺍니다. 금융업은 흑자·이자보상 조건을 적용하지 않습니다.</p>
    <p>이번 기준일 ${m.universe}개 중 <b>${m.scored}개 채점</b>, ${m.excluded.length}개 제외.</p>
    <details><summary>제외된 종목 ${m.excluded.length}개</summary>
      ${Object.entries(exByWhy).map(([w, es]) => `<p><b>${esc(w)}</b> ${es.length}개: ${es.map((e) => `${esc(e.name)}${e.why !== w ? `(${esc(e.why.replace(w, "").replace(/[()]/g, "").trim())})` : ""}`).join(", ")}</p>`).join("")}
    </details>
    <h3>배점</h3>
    <table><tbody>${rows}<tr class="cat-row"><td>감점(최대 ${P.cap})</td><td class="r"></td></tr>
      <tr><td>유상증자·CB·BW·EB 발행 결정(90일)</td><td class="r">${P.dilution}</td></tr>
      <tr><td>주요주주 지분 감소 보고(90일)</td><td class="r">${P.holder_sell}</td></tr>
      <tr><td>횡령·배임·소송 공시(180일)</td><td class="r">${P.legal}</td></tr></tbody></table>
    <p>기술적 신호는 발생 후 ${m.valid_days}거래일 안에서만 점수를 주고, 3일이 지나면 점점 줄여 유효기간 끝에는 40%까지 낮춥니다. 신용잔고는 종목별 공개 출처가 없어 아직 0점으로 둡니다.</p>
    <h3>단계</h3>
    <ol>
      <li><b class="s1">① 과매도</b>: 최근 20일 RSI 30 이하 또는 최근 10일 60일 이격도 90 이하.</li>
      <li><b class="s2">② 바닥 형성</b>: 60일 안에 과매도가 있었고, 대량거래 후 거래량 급감 또는 RSI·MACD 다이버전스가 나왔으며, 10거래일 넘게 신저가가 없고 60일 저점 대비 20% 이내.</li>
      <li><b class="s3">③ 전환 확인</b>: ②에 더해 이중바닥·N자 거래량 돌파 또는 20일선 2일 안착, 그리고 5일 외국인+기관 순매수.</li>
    </ol>
    <h3>시장 국면</h3>
    <p>오른쪽 위 표시는 증시 온도계의 과열·냉각 지표 수입니다. 점수에는 반영하지 않습니다.</p>
    <h3>수집 상태</h3>
    <p>${m.updated} 수집, ${m.asof} 종가 기준. 호출 수: 네이버 ${m.calls.naver}, 거래소 ${m.calls.krx}, DART ${m.calls.dart}.</p>
    ${m.errors.length ? `<details open><summary class="err">수집 중 문제 ${m.errors.length}건</summary>${m.errors.map((e) => `<p>${esc(e)}</p>`).join("")}</details>` : "<p>문제 없이 수집했습니다.</p>"}
    <p>점수는 바닥 가능성을 걸러 보는 도구일 뿐 매수 추천이 아닙니다.</p>`;
}

/* ---------- 탭·스와이프 ---------- */

function setTab(t, dir = 0) {
  S.tab = t;
  $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === t)));
  $$(".pane").forEach((p) => p.classList.toggle("on", p.dataset.pane === t));
  $(`.tabs button[data-tab="${t}"]`).scrollIntoView({ inline: "nearest", block: "nearest" });
  $("#main").scrollTop = 0;
  try { localStorage.setItem("badak.tab", t); } catch (e) { /* 저장 불가 */ }
}

(function swipe() {
  let x0 = null, y0 = 0, t0 = 0;
  const main = $("#main");
  main.addEventListener("touchstart", (e) => {
    if (e.touches.length !== 1 || e.target.closest(".chart, input, select")) { x0 = null; return; }
    x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; t0 = Date.now();
  }, { passive: true });
  main.addEventListener("touchend", (e) => {
    if (x0 == null) return;
    const dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
    x0 = null;
    if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 1.5 || Date.now() - t0 > 600) return;
    const i = TABS.indexOf(S.tab) + (dx < 0 ? 1 : -1);
    if (i >= 0 && i < TABS.length) setTab(TABS[i], dx < 0 ? 1 : -1);
  }, { passive: true });
})();

/* ---------- 시장 국면(증시 온도계와 같은 판정) ---------- */

async function heatBadge() {
  try {
    const r = await fetch("../heatmeter/data/data.json?t=" + Date.now(), { cache: "no-store" });
    if (!r.ok) return;
    const sig = Heat.signals(Heat.prep(await r.json()));
    const valid = sig.filter((s) => s.s !== "none"), hot = sig.filter((s) => s.s === "hot").length, cold = sig.filter((s) => s.s === "cold").length;
    if (!valid.length) return;
    const a = $("#heat");
    a.innerHTML = `<i></i>시장 과열 ${hot}, 냉각 ${cold} / ${valid.length}`;
    a.dataset.s = hot > cold ? "hot" : cold > hot ? "cold" : "mid";
    a.title = "증시 온도계 지표: " + valid.map((s) => `${s.name} ${({ hot: "과열", cold: "냉각", mid: "중립" })[s.s]}`).join(", ");
    a.hidden = false;
  } catch (e) { /* 온도계가 없으면 표시하지 않음 */ }
}

const Heat = (() => {
  const DAY = 864e5;
  const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
  const sd = (a) => { const m = mean(a); return Math.sqrt(mean(a.map((x) => (x - m) ** 2))); };
  const rank = (a, v) => (a.filter((x) => x <= v).length / a.length) * 100;
  const since = (rows, t0) => rows.filter((r) => r.t >= t0);
  const lastOf = (rows, f) => { for (let i = rows.length - 1; i >= 0; i--) if (rows[i][f] != null) return rows[i]; return null; };
  function prep(raw) {
    const gdp = raw.meta?.gdp || {}, gy = Object.keys(gdp).map(Number).sort((a, b) => a - b);
    const gdpFor = (y) => { let v = null; for (const k of gy) if (k <= y) v = gdp[k]; return v; };
    const dep = (raw.deposits || []).map((r) => ({ ...r, t: Date.parse(r.d) })).sort((a, b) => a.t - b.t);
    const mk = (raw.market || []).map((r) => ({ ...r, t: Date.parse(r.d) })).sort((a, b) => a.t - b.t);
    let j = 0, cur = null; const win = [];
    for (const r of mk) {
      const cap = (r.cap_k || 0) + (r.cap_q || 0), g = gdpFor(+r.d.slice(0, 4));
      r.buf = cap && g ? (cap / g) * 100 : null;
      r.trd = r.trd_k != null ? r.trd_k + (r.trd_q || 0) : null;
      if (r.trd != null) { win.push(r.trd); if (win.length > 20) win.shift(); }
      r.trd20 = win.length >= 5 ? mean(win) : null;
      while (j < dep.length && dep[j].t <= r.t) cur = dep[j++];
      r.dep = cur && r.t - cur.t < 7 * DAY ? cur.deposit : null;
      r.turn = r.trd20 != null && r.dep ? (r.trd20 / r.dep) * 100 : null;
    }
    const ipo = (raw.ipo || []).map((r) => ({ ...r, t: Date.parse(r.d) }));
    const retail = (raw.retail || []).map((r) => ({ ...r, t: Date.parse(r.m + "-15") })).sort((a, b) => a.t - b.t);
    return { mk, dep, ipo, retail, R: raw.meta?.rules || {} };
  }
  function bandOf(rows, f) {
    const last = rows[rows.length - 1]; if (!last) return null;
    const xs = since(rows, last.t - 10 * 365.25 * DAY).map((r) => r[f]).filter((v) => v != null);
    if (xs.length < 60) return null;
    const m = mean(xs), s = sd(xs); return { lo: m - s, hi: m + s };
  }
  function signals(D) {
    const R = D.R, out = [], mk = D.mk, endT = mk.length ? mk[mk.length - 1].t : Date.now();
    for (const [f, name] of [["per", "코스피 PER"], ["pbr", "코스피 PBR"]]) {
      const r = lastOf(mk, f), b = bandOf(mk, f);
      out.push({ name, s: !r || !b ? "none" : r[f] > b.hi ? "hot" : r[f] < b.lo ? "cold" : "mid" });
    }
    { const r = lastOf(mk, "buf"), hot = R.buffett_hot ?? 120; out.push({ name: "버핏지수", s: !r ? "none" : r.buf > hot ? "hot" : r.buf < 80 ? "cold" : "mid" }); }
    {
      const r = lastOf(D.dep, "credit");
      if (!r) out.push({ name: "신용거래융자 잔고", s: "none" });
      else {
        const yr = since(D.dep, r.t - 365 * DAY).map((x) => x.credit).filter((v) => v != null), pct = (r.credit / Math.max(...yr)) * 100;
        const k = lastOf(mk, "kospi"), k60 = mk.filter((x) => x.t <= (k ? k.t : 0) - 60 * DAY).pop();
        const rising = k && k60 ? k.kospi > k60.kospi : false;
        out.push({ name: "신용거래융자 잔고", s: pct >= (R.credit_near_high ?? 95) && rising ? "hot" : pct <= (R.credit_cold ?? 75) ? "cold" : "mid" });
      }
    }
    {
      const r = lastOf(D.dep, "deposit");
      if (!r) out.push({ name: "투자자예탁금", s: "none" });
      else {
        const idx = D.dep.indexOf(r), base = D.dep[Math.max(0, idx - 20)], ch = base ? (r.deposit / base.deposit - 1) * 100 : 0, surge = R.deposit_surge ?? 15;
        out.push({ name: "투자자예탁금", s: ch >= surge ? "hot" : ch <= -surge ? "cold" : "mid" });
      }
    }
    {
      const r = lastOf(mk, "turn");
      if (!r) out.push({ name: "예탁금 회전율", s: "none" });
      else { const p = rank(since(mk, r.t - 365 * DAY).map((x) => x.turn).filter((v) => v != null), r.turn); out.push({ name: "예탁금 회전율", s: p >= (R.turnover_rank_hot ?? 90) ? "hot" : p <= (R.turnover_rank_cold ?? 30) ? "cold" : "mid" }); }
    }
    {
      const rec = D.ipo.filter((r) => r.t >= endT - 60 * DAY), wc = rec.filter((r) => r.comp != null), wo = rec.filter((r) => r.open_pct != null);
      if (!rec.length) out.push({ name: "공모주 청약 열기", s: "none" });
      else {
        const share = wc.length ? (wc.filter((r) => r.comp >= 1000).length / wc.length) * 100 : null, open = wo.length ? mean(wo.map((r) => r.open_pct)) : null;
        const hot = (share != null && share >= (R.ipo_hot_share ?? 50)) || (open != null && open >= (R.ipo_hot_open ?? 100));
        const cold = share != null && share < (R.ipo_cold_share ?? 20) && (open == null || open < 20);
        out.push({ name: "공모주 청약 열기", s: hot ? "hot" : cold ? "cold" : "mid" });
      }
    }
    {
      const r = lastOf(D.retail, "kosdaq");
      if (!r) out.push({ name: "코스닥 개인 비중", s: "none" });
      else { const p = rank(since(D.retail, r.t - 3 * 365 * DAY).map((x) => x.kosdaq).filter((v) => v != null), r.kosdaq); out.push({ name: "코스닥 개인 비중", s: p >= (R.retail_rank_hot ?? 80) ? "hot" : p <= (R.retail_rank_cold ?? 20) ? "cold" : "mid" }); }
    }
    return out;
  }
  return { prep, signals };
})();

/* ---------- 시작 ---------- */

async function load() {
  try {
    const r = await fetch("data/latest.json?t=" + Date.now(), { cache: "no-store" });
    if (!r.ok) throw new Error(r.status === 404 ? "아직 첫 수집 전입니다. GitHub Actions에서 수집을 한 번 실행하세요." : `응답 ${r.status}`);
    S.D = await r.json();
  } catch (e) {
    $("#sub").textContent = "자료를 불러오지 못했습니다. " + e.message;
    return;
  }
  const m = S.D.meta;
  S.items = S.D.items;
  S.byCode = Object.fromEntries(S.items.map((i) => [i.code, i]));
  S.max = m.weights;
  S.catMax = catMax(m.weights);
  $("#sub").textContent = `코스피 시총 ${m.universe_cfg.top_n}위 중 ${m.scored}종목, ${m.asof} 종가 기준` + (m.errors.length ? ` · 수집 문제 ${m.errors.length}건` : "");
  renderLists();
  renderRules();
  if (location.hash.length === 7 && S.byCode[location.hash.slice(1)]) openDetail(location.hash.slice(1));
}

$(".tabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setTab(b.dataset.tab); });
$("#main").addEventListener("click", (e) => {
  const c = e.target.closest(".card"); if (c) return openDetail(c.dataset.code);
  const g = e.target.closest("[data-go]"); if (g) setTab(g.dataset.go);
});
$("#q").addEventListener("input", renderAll);
$("#sort").addEventListener("change", renderAll);
$("#close").addEventListener("click", () => closeDetail());
$("#sheet").addEventListener("click", (e) => { if (e.target.id === "sheet") closeDetail(); });
addEventListener("keydown", (e) => { if (e.key === "Escape") closeDetail(); });
addEventListener("popstate", () => closeDetail(true));

let saved = null;
try { saved = localStorage.getItem("badak.tab"); } catch (e) { /* 저장 불가 */ }
setTab(TABS.includes(saved) ? saved : "3");
load();
heatBadge();
