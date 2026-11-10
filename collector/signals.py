"""바닥 신호 계산 — 네트워크 없이 숫자만으로 지표와 점수를 냅니다.

모든 함수는 날짜 오름차순 리스트를 받습니다. 결과의 각 세부 항목은
(점수, 설명, 발생 위치) 형태이고, 점수는 config.json 배점을 상한으로 합니다.
"""

import datetime as dt
import math

# 세부 항목 정의: 키 → (대분류, 이름)
ITEMS = {
    "A1": ("A", "투매성 대량거래"),
    "A2": ("A", "대량거래 후 거래량 급감"),
    "A3": ("A", "아랫꼬리·지지 캔들"),
    "B1": ("B", "RSI 과매도"),
    "B2": ("B", "RSI 강세 다이버전스"),
    "B3": ("B", "MACD 다이버전스"),
    "B4": ("B", "볼린저 하단 재진입"),
    "B5": ("B", "60일 이격도"),
    "B6": ("B", "OBV 다이버전스"),
    "C1": ("C", "이중바닥·N자 돌파"),
    "C2": ("C", "20일선 회복"),
    "C3": ("C", "코스피 대비 상대강도"),
    "D1": ("D", "외국인+기관 순매수"),
    "D2": ("D", "신용잔고 감소"),
    "D3": ("D", "공매도 잔고 감소"),
    "D4": ("D", "외국인 지분율 반등"),
    "E1": ("E", "PBR 5년 밴드 하단"),
    "E2": ("E", "시가배당률 5년 상단"),
    "E3": ("E", "PER 5년 밴드 하단"),
    "F1": ("F", "임원·주요주주 지분 증가"),
    "F2": ("F", "자사주 취득 결정"),
    "F3": ("F", "자사주 소각"),
    "G1": ("G", "영업이익 증가 전환"),
    "G2": ("G", "영업이익 악화 둔화"),
}


# ───────────── 기본 계산 ─────────────
def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def sma(a, n):
    out, s = [None] * len(a), 0.0
    for i, x in enumerate(a):
        s += x
        if i >= n:
            s -= a[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(a, n):
    out, k, e = [None] * len(a), 2 / (n + 1), None
    for i, x in enumerate(a):
        e = x if e is None else x * k + e * (1 - k)
        out[i] = e if i >= n - 1 else None
    return out


def rsi(c, n=14):
    out = [None] * len(c)
    if len(c) <= n:
        return out
    g = l = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]
        g += max(d, 0)
        l += max(-d, 0)
    g, l = g / n, l / n
    out[n] = 100 if l == 0 else 100 - 100 / (1 + g / l)
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        l = (l * (n - 1) + max(-d, 0)) / n
        out[i] = 100 if l == 0 else 100 - 100 / (1 + g / l)
    return out


def macd_hist(c):
    e12, e26 = ema(c, 12), ema(c, 26)
    m = [a - b if a is not None and b is not None else None for a, b in zip(e12, e26)]
    first = next((i for i, x in enumerate(m) if x is not None), None)
    out = [None] * len(c)
    if first is None:
        return out
    sig = ema(m[first:], 9)
    for j, s in enumerate(sig):
        if s is not None:
            out[first + j] = m[first + j] - s
    return out


def obv(c, v):
    out, s = [0.0] * len(c), 0.0
    for i in range(1, len(c)):
        s += v[i] if c[i] > c[i - 1] else (-v[i] if c[i] < c[i - 1] else 0)
        out[i] = s
    return out


def bollinger_low(c, n=20, k=2.0):
    out = [None] * len(c)
    for i in range(n - 1, len(c)):
        w = c[i - n + 1:i + 1]
        m = sum(w) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / n)
        out[i] = m - k * sd
    return out


def pivots_low(low, start, w=3):
    """start 이후의 저점(좌우 w봉보다 낮은 봉). 끝부분은 오른쪽 2봉 이상이면 인정."""
    n, out = len(low), []
    for i in range(max(start, w), n - 2):
        left = low[i - w:i]
        right = low[i + 1:min(n, i + w + 1)]
        if low[i] < min(left) and low[i] <= min(right):
            out.append(i)
    return out


def pct_rank(xs, v):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return sum(1 for x in xs if x <= v) / len(xs) * 100


class Ctx:
    """종목 하나의 계산 재료"""

    def __init__(self, ts, valid_days=20):
        self.d, self.o, self.h, self.l, self.c, self.v = (ts[k] for k in ("d", "o", "h", "l", "c", "v"))
        self.n = len(self.c)
        self.V = valid_days
        self.ma20, self.ma60, self.ma120 = sma(self.c, 20), sma(self.c, 60), sma(self.c, 120)
        self.rsi = rsi(self.c)
        self.hist = macd_hist(self.c)
        self.obv = obv(self.c, self.v)
        self.bb = bollinger_low(self.c)

    def age(self, i):
        return self.n - 1 - i

    def decay(self, i):
        """발생 후 3일까지는 그대로, 이후 유효기간 끝에서 40%까지 줄고, 넘으면 0"""
        a = self.age(i)
        if a > self.V:
            return 0.0
        if a <= 3:
            return 1.0
        return max(0.4, 1 - (a - 3) * 0.6 / max(1, self.V - 3))

    def date(self, i):
        s = self.d[i]
        return f"{s[4:6]}/{s[6:8]}" if len(s) == 8 else s

    def avg_vol(self, i, n=20):
        w = self.v[max(0, i - n):i]
        return sum(w) / len(w) if w else None


def r1(x):
    return round(x, 1)


# ───────────── A. 매도 소진 ─────────────
def sig_A(x, W):
    out = {}
    c, l, o, v, n = x.c, x.l, x.o, x.v, x.n
    best = None
    for i in range(max(21, n - x.V - 1), n):
        base = x.avg_vol(i)
        if not base:
            continue
        r = v[i] / base
        falling = (x.ma60[i] is not None and c[i] < x.ma60[i]) or c[i] / c[i - 20] - 1 <= -0.08
        selloff = c[i] <= c[i - 1] or (min(o[i], c[i]) - l[i]) / c[i] >= 0.02
        if r >= 2 and falling and selloff:
            pts = (W["A1"] if r >= 3 else W["A1"] * 0.5) * x.decay(i)
            if best is None or pts >= best[0]:
                best = (pts, i, r, base)
    if best:
        pts, i, r, base = best
        out["A1"] = (r1(pts), f"{x.date(i)} 거래량 20일 평균의 {r:.1f}배", i)
        after = v[i + 1:i + 6]
        if len(after) >= 3:
            ratio = sum(after) / len(after) / base
            held = min(l[i + 1:]) >= l[i] * 0.97
            k = i + len(after)
            if held and ratio <= 1.2:
                p = (W["A2"] if ratio <= 1.0 else W["A2"] * 0.5) * x.decay(k)
                out["A2"] = (r1(p), f"이후 {len(after)}일 평균 거래량이 평소의 {ratio:.0%}, 저점 지지", k)
            elif not held:
                out["A2"] = (0, "대량거래일 저점을 3% 넘게 다시 이탈", None)
            else:
                out["A2"] = (0, f"이후 거래량이 평소의 {ratio:.0%}로 아직 많음", None)
        else:
            out["A2"] = (0, "대량거래 후 3일 이상 지나야 판정", None)
    else:
        out["A1"] = (0, f"최근 {x.V}일 하락 중 대량거래 없음", None)
        out["A2"] = (0, "기준이 되는 대량거래 없음", None)

    best = None
    for i in range(max(11, n - 10), n):
        down = c[i - 1] < c[i - 11] * 0.97 or (x.ma20[i] is not None and c[i] < x.ma20[i])
        if not down:
            continue
        body = abs(c[i] - o[i])
        lower = min(o[i], c[i]) - l[i]
        hammer = lower >= 2 * max(body, c[i] * 0.002) and lower / c[i] >= 0.015
        bull = o[i] > 0 and (c[i] - o[i]) / o[i] >= 0.04 and c[i - 1] < c[i - 6]
        if hammer or bull:
            pts = W["A3"] * x.decay(i)
            if best is None or pts >= best[0]:
                best = (pts, i, "아랫꼬리" if hammer else "하락 후 장대양봉")
    out["A3"] = (r1(best[0]), f"{x.date(best[1])} {best[2]}", best[1]) if best else (0, "최근 10일 지지 캔들 없음", None)
    return out


# ───────────── B. 과매도·다이버전스 ─────────────
def divergence_pair(x):
    """최근 60일 안에서 (이전 저점, 최근 저점) — 최근 저점이 더 낮은 경우만"""
    pv = pivots_low(x.l, x.n - 60)
    if len(pv) < 2:
        return None
    l2 = pv[-1]
    if x.age(l2) > x.V:
        return None
    earlier = [p for p in pv[:-1] if p <= l2 - 5]
    if not earlier:
        return None
    l1 = min(earlier, key=lambda p: x.l[p])
    if x.l[l2] >= x.l[l1]:
        return None
    return l1, l2


def sig_B(x, W):
    out = {}
    lo = max(0, x.n - x.V - 1)
    rs = [(x.rsi[i], i) for i in range(lo, x.n) if x.rsi[i] is not None]
    if rs:
        m, i = min(rs)
        if m <= 30:
            base = W["B1"] if m <= 25 else W["B1"] * (0.6 + (30 - m) / 5 * 0.4)
            out["B1"] = (r1(base * x.decay(i)), f"{x.date(i)} RSI {m:.0f}", i)
        else:
            out["B1"] = (0, f"최근 {x.V}일 RSI 최저 {m:.0f}", None)
    else:
        out["B1"] = (0, "RSI 계산 불가", None)

    pair = divergence_pair(x)
    if pair:
        a, b = pair
        ra, rb = x.rsi[a], x.rsi[b]
        if ra is not None and rb is not None and rb > ra + 2 and ra <= 40:
            out["B2"] = (r1(W["B2"] * x.decay(b)), f"저점 {x.date(a)}→{x.date(b)} 주가↓ RSI {ra:.0f}→{rb:.0f}", b)
        else:
            out["B2"] = (0, "저점은 낮아졌지만 RSI도 함께 낮아짐", None)
        ha, hb = x.hist[a], x.hist[b]
        if ha is not None and hb is not None and ha < 0 and hb > ha:
            out["B3"] = (r1(W["B3"] * x.decay(b)), f"저점 {x.date(a)}→{x.date(b)} MACD 히스토그램 상승", b)
        else:
            out["B3"] = (0, "MACD 저점 상승 없음", None)
        if x.obv[b] > x.obv[a]:
            out["B6"] = (r1(W["B6"] * x.decay(b)), f"저점 {x.date(a)}→{x.date(b)} OBV 상승", b)
        else:
            out["B6"] = (0, "OBV도 함께 하락", None)
    else:
        for k in ("B2", "B3", "B6"):
            out[k] = (0, "최근 60일 안에 더 낮은 저점 쌍 없음", None)

    hit = None
    last_below = None
    for i in range(lo, x.n):
        if x.bb[i] is None:
            continue
        if x.c[i] < x.bb[i]:
            last_below, hit = i, None
        elif last_below is not None and hit is None:
            hit = i
    if hit is not None and x.c[-1] > x.bb[-1]:
        out["B4"] = (r1(W["B4"] * x.decay(hit)), f"{x.date(last_below)} 하단 이탈 → {x.date(hit)} 재진입", hit)
    elif last_below is not None and hit is None:
        out["B4"] = (0, "볼린저 하단 아래에 머무는 중", None)
    else:
        out["B4"] = (0, f"최근 {x.V}일 하단 이탈 없음", None)

    ds = [(x.c[i] / x.ma60[i] * 100, i) for i in range(max(0, x.n - 10), x.n) if x.ma60[i]]
    if ds:
        m, i = min(ds)
        if m <= 90:
            base = W["B5"] if m <= 85 else W["B5"] * (0.5 + (90 - m) / 10)
            out["B5"] = (r1(base * x.decay(i)), f"{x.date(i)} 이격도 {m:.0f}", i)
        else:
            out["B5"] = (0, f"최근 10일 최저 이격도 {m:.0f}", None)
    else:
        out["B5"] = (0, "60일 이동평균 계산 불가", None)
    return out


# ───────────── C. 바닥 패턴·전환 ─────────────
def sig_C(x, W, kospi):
    out = {}
    c, h, l, v, n = x.c, x.h, x.l, x.v, x.n
    floor = min(l[max(0, n - 120):])
    pv = pivots_low(l, n - 60)
    best = None
    for j, p2 in enumerate(pv):
        for p1 in pv[:j]:
            if p2 - p1 < 5 or l[p1] > floor * 1.05:
                continue
            if not (l[p1] * 0.97 <= l[p2] <= l[p1] * 1.15):
                continue
            neck = max(h[p1 + 1:p2])
            if neck < l[p1] * 1.05:
                continue
            kind = "이중바닥" if abs(l[p2] / l[p1] - 1) <= 0.03 else "N자"
            brk = None
            for k in range(p2 + 1, n):
                av = x.avg_vol(k)
                if c[k] > neck and av and v[k] >= 1.5 * av:
                    brk = k
                    break
            if brk is not None:
                pts = W["C1"] * x.decay(brk)
                note = f"{kind} {x.date(p1)}·{x.date(p2)}, {x.date(brk)} 넥라인 {neck:,.0f} 거래량 돌파"
                pos = brk
            elif x.age(p2) <= x.V and c[-1] > l[p2]:
                pts = W["C1"] * 2 / 7
                note = f"{kind} {x.date(p1)}·{x.date(p2)} 형성, 넥라인 {neck:,.0f} 돌파 대기"
                pos = None
            else:
                continue
            if best is None or pts > best[0]:
                best = (pts, note, pos)
    out["C1"] = (r1(best[0]), best[1], best[2]) if best else (0, "최근 60일 바닥 패턴 없음", None)

    run = 0
    for i in range(n - 1, -1, -1):
        if x.ma20[i] is not None and c[i] > x.ma20[i]:
            run += 1
        else:
            break
    if run >= 2:
        r = n - run
        below = sum(1 for i in range(max(0, r - 15), r) if x.ma20[i] is not None and c[i] < x.ma20[i])
        if below >= 5:
            out["C2"] = (r1(W["C2"] * x.decay(r + 1)), f"{x.date(r)}부터 20일선 위 {run}일째", r + 1)
        else:
            out["C2"] = (0, "20일선 위지만 직전 하락 구간이 짧음", None)
    else:
        out["C2"] = (0, "20일선 아래" if run == 0 else "20일선 위 1일째(2일 안착 필요)", None)

    k = [kospi.get(d) for d in x.d]
    if n > 41 and all(k[i] for i in (n - 1, n - 21, n - 41)):
        now = (c[-1] / c[-21] - 1) - (k[-1] / k[-21] - 1)
        prev = (c[-21] / c[-41] - 1) - (k[-21] / k[-41] - 1)
        if now > 0 and prev < 0:
            out["C3"] = (W["C3"], f"20일 초과수익 {prev:+.1%} → {now:+.1%} 전환", n - 1)
        elif now > 0:
            out["C3"] = (r1(W["C3"] * 0.5), f"20일 초과수익 {now:+.1%} 유지", n - 1)
        else:
            out["C3"] = (0, f"20일 초과수익 {now:+.1%}", None)
    else:
        out["C3"] = (0, "코스피 비교 자료 부족", None)
    return out


# ───────────── D. 수급 ─────────────
def sig_D(x, W, flows, foreign, short):
    """flows: [(날짜, 외국인+기관 순매수 백만원)], foreign: [(날짜, 지분율%)], short: [(날짜, 잔고주식수)]"""
    out = {}
    if len(flows) >= 10:
        vals = [f for _, f in flows[-25:]]
        s5, prev = sum(vals[-5:]), sum(vals[:-5])
        k = 0
        for f in reversed(vals):
            if f > 0:
                k += 1
            else:
                break
        if s5 > 0:
            base = W["D1"] * (0.75 if prev < 0 else 0.375)
            bonus = W["D1"] * (0.25 if k >= 3 else 0.125 if k >= 2 else 0)
            what = "전환" if prev < 0 else "지속"
            out["D1"] = (r1(min(W["D1"], base + bonus)),
                         f"5일 순매수 {s5 / 100:+,.0f}억 ({what}), {k}일 연속", x.n - 1)
        else:
            out["D1"] = (0, f"5일 순매도 {s5 / 100:,.0f}억", None)
    else:
        out["D1"] = (None, "수급 자료 미수집", None)

    out["D2"] = (None, "종목별 신용잔고 공개 출처 없음(미수집)", None)

    if len(short) >= 10:
        w = short[-60:]
        mx = max(b for _, b in w)
        cur = w[-1][1]
        if mx <= 0:
            out["D3"] = (0, "공매도 잔고 없음", None)
        else:
            drop = 1 - cur / mx
            asof = w[-1][0]
            if drop >= 0.2:
                out["D3"] = (W["D3"], f"잔고 고점 대비 {drop:.0%} 감소 ({asof[4:6]}/{asof[6:]} 기준)", x.n - 1)
            elif drop >= 0.1:
                out["D3"] = (r1(W["D3"] * 0.5), f"잔고 고점 대비 {drop:.0%} 감소", x.n - 1)
            else:
                out["D3"] = (0, f"잔고 고점 대비 {drop:.0%} 감소", None)
    else:
        out["D3"] = (None, "공매도 잔고 미수집", None)

    if len(foreign) >= 10:
        w = foreign[-60:]
        mn_i = min(range(len(w)), key=lambda i: w[i][1])
        mn, cur = w[mn_i][1], w[-1][1]
        age = len(w) - 1 - mn_i
        up = cur - mn
        if age >= 5 and up >= 0.3:
            out["D4"] = (W["D4"], f"지분율 {mn:.2f}% → {cur:.2f}% (+{up:.2f}%p)", x.n - 1)
        elif age >= 5 and up >= 0.1:
            out["D4"] = (r1(W["D4"] * 0.5), f"지분율 {mn:.2f}% → {cur:.2f}% (+{up:.2f}%p)", x.n - 1)
        else:
            out["D4"] = (0, f"지분율 {cur:.2f}%, 60일 저점 대비 +{up:.2f}%p", None)
    else:
        out["D4"] = (None, "외국인 지분율 미수집", None)
    return out


# ───────────── E. 가치 바닥 ─────────────
def sig_E(W, fund):
    """fund: [(날짜, PER, PBR, 배당수익률)] 5년 주간 + 최신"""
    out = {}
    if len(fund) < 100:
        for k in ("E1", "E2", "E3"):
            out[k] = (None, "5년 밸류 이력 부족(2년 미만)", None)
        return out
    per, pbr, div = fund[-1][1], fund[-1][2], fund[-1][3]
    yrs = f"{len(fund) / 52:.0f}년"

    if pbr and pbr > 0:
        p = pct_rank([f[2] for f in fund if f[2] and f[2] > 0], pbr)
        pts = W["E1"] if p <= 10 else W["E1"] * (1 - (p - 10) * 0.0375) if p <= 20 else 0
        out["E1"] = (r1(pts), f"PBR {pbr:.2f}배, {yrs} 중 하위 {p:.0f}%", None)
    else:
        out["E1"] = (0, "PBR 없음", None)

    if div and div > 0:
        p = pct_rank([f[3] for f in fund if f[3] is not None], div)
        pts = W["E2"] if p >= 90 else W["E2"] * (0.625 + (p - 80) * 0.0375) if p >= 80 else 0
        out["E2"] = (r1(pts), f"시가배당률 {div:.2f}%, {yrs} 중 상위 {100 - p:.0f}%", None)
    else:
        out["E2"] = (0, "배당 없음", None)

    if per and per > 0:
        p = pct_rank([f[1] for f in fund if f[1] and f[1] > 0], per)
        pts = W["E3"] if p <= 10 else W["E3"] * (1 - (p - 10) / 30) if p <= 20 else 0
        out["E3"] = (r1(pts), f"PER {per:.1f}배, {yrs} 중 하위 {p:.0f}%", None)
    else:
        out["E3"] = (0, "적자 또는 PER 없음", None)
    return out


# ───────────── F·G·감점: 공시 ─────────────
def days_between(a, b):
    return (dt.date(int(b[:4]), int(b[4:6]), int(b[6:])) - dt.date(int(a[:4]), int(a[4:6]), int(a[6:]))).days


def sig_F(W, events, today):
    """events: [{'k': 종류, 'd': YYYYMMDD, 'nm': 보고서명, 'who': ...}]"""
    out = {}
    within = lambda e, n: 0 <= days_between(e["d"], today) <= n
    buys = [e for e in events if e["k"] == "insider_buy" and within(e, 60)]
    if buys:
        e = max(buys, key=lambda e: e["d"])
        who = ", ".join(sorted({b.get("who", "") for b in buys if b.get("who")}))[:40]
        out["F1"] = (W["F1"], f"{e['d'][4:6]}/{e['d'][6:]} 등 {len(buys)}건 보유 증가 보고" + (f" ({who})" if who else ""), None)
    else:
        out["F1"] = (0, "최근 60일 임원·주요주주 보유 증가 없음", None)
    bb = [e for e in events if e["k"] == "buyback" and within(e, 60)]
    out["F2"] = ((W["F2"], f"{bb[-1]['d'][4:6]}/{bb[-1]['d'][6:]} {bb[-1]['nm']}", None) if bb
                 else (0, "최근 60일 자사주 취득 결정 없음", None))
    rt = [e for e in events if e["k"] == "retire" and within(e, 365)]
    out["F3"] = ((W["F3"], f"{rt[-1]['d'][:4]}.{rt[-1]['d'][4:6]}.{rt[-1]['d'][6:]} 주식소각결정", None) if rt
                 else (0, "최근 1년 소각 공시 없음", None))
    return out


def sig_G(W, q):
    """q: [(분기라벨, 당기 영업이익, 전년동기 영업이익)] 오래된→최신, 최소 2개"""
    out = {}
    if not q or len(q) < 1 or q[-1][1] is None or q[-1][2] is None:
        out["G1"] = (None, "분기 실적 미수집", None)
        out["G2"] = (None, "분기 실적 미수집", None)
        return out

    def g(cur, prev):
        return (cur - prev) / abs(prev) if prev else (1.0 if cur > 0 else -1.0 if cur < 0 else 0.0)

    lab, cur, prev = q[-1]
    g_now = g(cur, prev)
    g_prev = g(q[-2][1], q[-2][2]) if len(q) >= 2 and q[-2][1] is not None and q[-2][2] is not None else None
    eok = lambda v: f"{v / 1e8:,.0f}억"
    desc = f"{lab} 영업이익 {eok(cur)} (전년 {eok(prev)}, {g_now:+.0%})"
    if cur > prev:
        out["G1"] = (W["G1"], desc, None)
        if g_prev is not None and g_prev < 0:
            out["G2"] = (W["G2"], f"직전 분기 {g_prev:+.0%}에서 증가로 전환", None)
        else:
            out["G2"] = (0, "직전 분기도 증가(전환 아님)" if g_prev is not None else "직전 분기 비교 불가", None)
    else:
        out["G1"] = (0, desc, None)
        if g_prev is not None and g_now > g_prev:
            out["G2"] = (W["G2"], f"감소폭 축소 {g_prev:+.0%} → {g_now:+.0%}", None)
        else:
            out["G2"] = (0, "감소폭 축소 아님" if g_prev is not None else "직전 분기 비교 불가", None)
    return out


def penalties(P, events, today):
    within = lambda e, n: 0 <= days_between(e["d"], today) <= n
    out = []
    dil = [e for e in events if e["k"] == "dilution" and within(e, 90)]
    if dil:
        out.append(("증자·메자닌 발행", P["dilution"], f"{dil[-1]['d'][4:6]}/{dil[-1]['d'][6:]} {dil[-1]['nm']}"))
    sell = [e for e in events if e["k"] == "holder_sell" and within(e, 90)]
    if sell:
        e = sell[-1]
        out.append(("주요주주 지분 매도", P["holder_sell"], f"{e['d'][4:6]}/{e['d'][6:]} {e.get('who', '')} 보유 감소"))
    leg = [e for e in events if e["k"] == "legal" and within(e, 180)]
    if leg:
        out.append(("횡령·배임·소송", P["legal"], f"{leg[-1]['d'][4:6]}/{leg[-1]['d'][6:]} {leg[-1]['nm']}"))
    return out


# ───────────── 종합 ─────────────
def stage_of(x, subs, ts):
    """단계는 상태 판정이라 근거를 60일까지 봅니다(점수는 유효기간 안의 신호만).
    ① 최근 20일 RSI 30 이하 또는 최근 10일 이격도 90 이하
    ② 60일 안에 과매도 + (거래량 급감 또는 다이버전스) + 최근 10일 신저가 없음 + 60일 저점 대비 20% 이내
    ③ ② + (패턴 돌파 또는 20일선 회복) + 외국인·기관 순매수"""
    met = lambda d, k: (d.get(k, (0,))[0] or 0) > 0

    def oversold(cx, rsi_days):
        rs = [cx.rsi[i] for i in range(max(0, cx.n - rsi_days - 1), cx.n) if cx.rsi[i] is not None]
        ds = [cx.c[i] / cx.ma60[i] * 100 for i in range(max(0, cx.n - 10), cx.n) if cx.ma60[i]]
        return bool((rs and min(rs) <= 30) or (ds and min(ds) <= 90))

    s1_now = oversold(x, x.V)
    x60 = Ctx(ts, 60)
    ev = {**sig_A(x60, {k: 1 for k in ("A1", "A2", "A3")}), **sig_B(x60, {k: 1 for k in ("B1", "B2", "B3", "B4", "B5", "B6")})}
    rs60 = [x.rsi[i] for i in range(max(0, x.n - 61), x.n) if x.rsi[i] is not None]
    s1_any = s1_now or bool(rs60 and min(rs60) <= 30) or met(ev, "B5")
    w = x.l[max(0, x.n - 60):]
    low_i = min(range(len(w)), key=lambda i: w[i])
    low_age = len(w) - 1 - low_i
    near = x.c[-1] <= w[low_i] * 1.2
    s2 = s1_any and (met(ev, "A2") or met(ev, "B2") or met(ev, "B3")) and low_age >= 10 and near
    if s2:
        c1_break = met(subs, "C1") and "돌파 대기" not in subs["C1"][1]
        if (c1_break or met(subs, "C2")) and met(subs, "D1"):
            return 3
        return 2
    return 1 if s1_now else 0


def score_stock(ts, W, P, valid_days, kospi, flows, foreign, short, fund, events, quarters, today):
    x = Ctx(ts, valid_days)
    subs = {}
    subs.update(sig_A(x, W))
    subs.update(sig_B(x, W))
    subs.update(sig_C(x, W, kospi))
    subs.update(sig_D(x, W, flows, foreign, short))
    subs.update(sig_E(W, fund))
    subs.update(sig_F(W, events, today))
    subs.update(sig_G(W, quarters))
    pen = penalties(P, events, today)
    raw = sum((v[0] or 0) for v in subs.values())
    p = max(P["cap"], sum(x[1] for x in pen))
    total = max(0.0, raw + p)
    return {
        "x": x,
        "subs": subs,
        "pen": pen,
        "pen_total": p,
        "raw": round(raw, 1),
        "score": round(total, 1),
        "stage": stage_of(x, subs, ts),
    }
