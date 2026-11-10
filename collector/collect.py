"""바닥 신호 수집기.

출처별로 따로 모으고, 한 곳이 실패해도 나머지로 점수를 냅니다(실패 항목은 '미수집'으로 표시).
  - 네이버 증권: 코스피 시가총액 순위(후보군), 종목별·코스피 일봉, 관리·경고·거래정지 종목
  - 한국거래소(pykrx, 로그인 필요): 외국인·기관 순매수, 외국인 지분율, 공매도 잔고, PER·PBR·배당수익률 이력
  - OpenDART: 재무 필터(흑자·잠식·이자보상·감사의견), 분기 영업이익, 공시(자사주·증자·소송 등), 임원·주요주주 지분
결과: data/latest.json(목록) + data/charts/종목코드.json(상세 차트)
"""

import datetime as dt
import io
import json
import os
import re
import sys
import time
import traceback
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import signals as SG  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
CHARTS = DATA / "charts"
for p in (DATA, CACHE, CHARTS, CACHE / "fund"):
    p.mkdir(parents=True, exist_ok=True)

CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
UCFG = CFG["universe"]
W, P, V = CFG["weights"], CFG["penalties"], int(CFG.get("valid_days", 20))

KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime.now(KST)
DART = "https://opendart.fss.or.kr/api"
DART_KEY = os.environ.get("DART_API_KEY", "").strip()
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "ko-KR,ko;q=0.9"}
S = requests.Session()
S.headers.update(UA)
ERRORS = []
CALLS = {"dart": 0, "krx": 0, "naver": 0}


def log(*a):
    print(*a, flush=True)


def err(where, e):
    msg = f"{where}: {str(e)[:200]}"
    log("  [오류] " + msg)
    ERRORS.append(msg)


def num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if v != v else float(v)
    s = str(v).replace(",", "").replace(" ", "").strip()
    if s in ("", "-", "N/A", "nan"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def load(name, default=None):
    f = CACHE / f"{name}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {} if default is None else default


def save(name, obj):
    f = CACHE / f"{name}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


# ───────────────────────── 1. 네이버 ─────────────────────────
def naver_get(url, params=None, tries=3):
    last = None
    for i in range(tries):
        try:
            r = S.get(url, params=params, timeout=25, headers={"Referer": "https://finance.naver.com/"})
            CALLS["naver"] += 1
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def fchart(symbol, count):
    """네이버 일봉(수정주가). 반환: {d,o,h,l,c,v} 리스트 묶음"""
    r = naver_get("https://fchart.stock.naver.com/sise.nhn",
                  {"symbol": symbol, "timeframe": "day", "count": count, "requestType": 0})
    rows = re.findall(r'data="([^"]+)"', r.content.decode("euc-kr", errors="replace"))
    out = {k: [] for k in "dohlcv"}
    for row in rows:
        p = row.split("|")
        if len(p) < 6:
            continue
        vals = [num(x) for x in p[1:6]]
        if any(v is None for v in vals) or vals[3] <= 0:
            continue
        o, h, l, c, v = vals
        out["d"].append(p[0])
        for k, val in zip("ohlcv", (o or c, h or c, l or c, c, v)):
            out[k].append(val)
    return out


def universe_naver():
    """코스피 보통주 시가총액 순위. 반환: [{code,name,mcap(억)}]"""
    rows = []
    for page in range(1, 9):
        r = naver_get("https://m.stock.naver.com/api/stocks/marketValue/KOSPI", {"page": page, "pageSize": 100})
        j = r.json()
        items = j.get("stocks") if isinstance(j, dict) else j
        if not items:
            break
        for it in items:
            code = str(it.get("itemCode") or "").strip()
            if len(code) != 6 or str(it.get("stockEndType") or "stock").lower() != "stock":
                continue
            mv = num(it.get("marketValue"))
            if mv is None:
                continue
            if mv > 1e9:  # 원 단위로 오면 억원으로
                mv /= 1e8
            rows.append({"code": code, "name": (it.get("stockName") or it.get("itemName") or "").strip(), "mcap": mv})
        time.sleep(0.2)
    if len(rows) < 400:
        raise RuntimeError(f"네이버 시가총액 순위가 {len(rows)}종목뿐입니다")
    rows.sort(key=lambda r: -r["mcap"])
    return rows


def flagged_naver():
    """관리종목·거래정지·투자경고·투자위험 종목코드 → 사유"""
    pages = [
        ("관리종목", "https://finance.naver.com/sise/management.naver", None),
        ("거래정지", "https://finance.naver.com/sise/trading_halt.naver", None),
        ("투자경고", "https://finance.naver.com/sise/investment_alert.naver", {"type": "warning"}),
        ("투자위험", "https://finance.naver.com/sise/investment_alert.naver", {"type": "risk"}),
    ]
    out = {}
    for why, url, params in pages:
        try:
            r = naver_get(url, params)
            for code in re.findall(r"/item/main\.naver\?code=(\d{6})", r.content.decode("euc-kr", errors="replace")):
                out.setdefault(code, why)
        except Exception as e:  # noqa: BLE001
            err(f"네이버 {why} 목록", e)
        time.sleep(0.3)
    return out


# ───────────────────────── 2. 한국거래소 ─────────────────────────
KRX_READY = None


def krx():
    """pykrx 모듈. 로그인 정보가 없으면 None"""
    global KRX_READY
    if KRX_READY is None:
        if not (os.getenv("KRX_ID") and os.getenv("KRX_PW")):
            err("한국거래소", "KRX_ID / KRX_PW 가 없습니다(저장소 Secrets에 추가). 수급·공매도·밸류 항목은 미수집 처리")
            KRX_READY = False
        else:
            try:
                from pykrx import stock  # noqa: F401
                KRX_READY = True
            except Exception as e:  # noqa: BLE001
                err("pykrx 불러오기", e)
                KRX_READY = False
    if not KRX_READY:
        return None
    from pykrx import stock
    return stock


def krx_call(fn, *a, **k):
    last = None
    for i in range(3):
        try:
            df = fn(*a, **k)
            CALLS["krx"] += 1
            time.sleep(0.5)
            return df
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise last


def col(df, *keys):
    for c in df.columns:
        if all(k in str(c) for k in keys):
            return c
    return None


def krx_daily(name, dates, fetch, keep):
    """날짜별 전종목 자료를 캐시에 쌓습니다. fetch(date)->{code: value} 또는 None(휴장·미공표)"""
    cache = load(name)
    todo = [d for d in dates if d not in cache]
    fails = 0
    for d in todo:
        try:
            m = fetch(d)
        except Exception as e:  # noqa: BLE001
            fails += 1
            if fails >= 3:
                err(f"한국거래소 {name}", e)
                break
            continue
        if m:
            cache[d] = m
        if len(cache) % 10 == 0:
            save(name, cache)
    for d in sorted(cache)[:-keep]:
        del cache[d]
    save(name, cache)
    log(f"  {name}: {len(cache)}일치 (새로 {len(todo)}일 시도)")
    return cache


def krx_flows(st, dates):
    def fetch(d):
        out = {}
        for inv in ("외국인", "기관합계"):
            df = krx_call(st.get_market_net_purchases_of_equities, d, d, "KOSPI", inv)
            if df is None or df.empty:
                return None
            c = col(df, "순매수", "대금")
            for code, v in df[c].items():
                out[code] = out.get(code, 0) + round(float(v) / 1e6)
        return out
    return krx_daily("flows", dates[-30:], fetch, 40)


def krx_foreign(st, dates):
    def fetch(d):
        df = krx_call(st.get_exhaustion_rates_of_foreign_investment, d, "KOSPI")
        if df is None or df.empty:
            return None
        c = col(df, "지분율")
        return {code: round(float(v), 2) for code, v in df[c].items() if v == v}
    return krx_daily("foreign", dates[-62:], fetch, 70)


def krx_short(st, dates):
    def fetch(d):
        df = krx_call(st.get_shorting_balance, d, "KOSPI")
        if df is None or df.empty:
            return None
        c = col(df, "공매도잔고") or col(df, "잔고")
        m = {code: int(v) for code, v in df[c].items() if v == v}
        return m if sum(m.values()) > 0 else None  # 아직 공표 전(T+2)이면 비어 있음
    return krx_daily("short", dates[-65:], fetch, 70)


def krx_fund(st, dates):
    """PER·PBR·배당수익률. 5년은 주 1회(주 마지막 거래일), 최근 5일은 매일. 연도별 파일로 나눠 저장."""
    weekly = {}
    for d in dates:
        y, w, _ = dt.date(int(d[:4]), int(d[4:6]), int(d[6:])).isocalendar()
        weekly[(y, w)] = d
    want = sorted(set(list(weekly.values())[-262:] + dates[-5:]))
    by_year = {}
    for d in want:
        by_year.setdefault(d[:4], []).append(d)
    fund, fails = {}, 0
    for y, ds in sorted(by_year.items()):
        name = f"fund/{y}"
        cache = load(name)
        new = 0
        for d in ds:
            if d in cache or fails >= 3:
                continue
            try:
                df = krx_call(st.get_market_fundamental, d, market="KOSPI")
            except Exception as e:  # noqa: BLE001
                fails += 1
                if fails >= 3:
                    err("한국거래소 PER·PBR", e)
                continue
            if df is None or df.empty:
                continue
            cp, cb, cd = col(df, "PER"), col(df, "PBR"), col(df, "DIV")
            rnd = lambda v, k: None if num(v) is None else round(num(v), k)
            cache[d] = {code: [rnd(r[cp], 1), rnd(r[cb], 2), rnd(r[cd], 2)] for code, r in df.iterrows()}
            new += 1
            if new % 20 == 0:
                save(name, cache)
                log(f"  PER·PBR {y}: {len(cache)}주")
        # 오래된 일별 값은 주간 표본만 남김
        keep = set(ds)
        for d in list(cache):
            if d not in keep and d < dates[-5]:
                del cache[d]
        save(name, cache)
        fund.update(cache)
    log(f"  PER·PBR 이력: {len(fund)}개 시점")
    return fund


# ───────────────────────── 3. OpenDART ─────────────────────────
def dart(path, params, raw=False):
    q = {"crtfc_key": DART_KEY, **params}
    last = None
    for i in range(4):
        try:
            r = S.get(f"{DART}/{path}", params=q, timeout=40)
            CALLS["dart"] += 1
            time.sleep(0.12)
            if raw:
                r.raise_for_status()
                return r.content
            j = r.json()
            st = j.get("status")
            if st == "000":
                return j
            if st in ("013", "014"):
                return None
            if st in ("010", "011", "012", "901"):
                raise SystemExit(f"[중단] OpenDART 인증키 문제({st}): {j.get('message')} — Secrets의 DART_API_KEY를 확인하세요.")
            if st == "020":
                raise SystemExit("[중단] OpenDART 일일 호출 한도 초과. 내일 다시 실행하면 캐시로 이어집니다.")
            last = f"{st} {j.get('message')}"
            return None
        except (requests.RequestException, ValueError) as e:
            last = e
            time.sleep(2 * (i + 1))
    log(f"  DART {path} 실패: {last}")
    return None


def corp_codes():
    f = CACHE / "corpcode.json"
    if f.exists() and time.time() - f.stat().st_mtime < 7 * 86400:
        return json.loads(f.read_text(encoding="utf-8"))
    raw = dart("corpCode.xml", {}, raw=True)
    z = zipfile.ZipFile(io.BytesIO(raw))
    root = ET.fromstring(z.read(z.namelist()[0]))
    m = {}
    for el in root.iter("list"):
        sc = (el.findtext("stock_code") or "").strip()
        if sc:
            m[sc] = el.findtext("corp_code").strip()
    f.write_text(json.dumps(m), encoding="utf-8")
    return m


def company(corps):
    cache = load("company")
    for c in corps:
        if c not in cache:
            j = dart("company.json", {"corp_code": c})
            cache[c] = (j or {}).get("induty_code", "")
    save("company", cache)
    return cache


ACC = {"op": ("영업이익",), "equity": ("자본총계",), "capital": ("자본금",), "rev": ("매출액", "영업수익")}


def multi(corps, year, reprt, refresh):
    """다중회사 주요계정. 반환 {corp: {acc: {cur, prev, cur_add, prev_add}}}"""
    name = f"fin_{year}_{reprt}"
    cache = load(name)
    asked = set(cache.pop("_asked", []))
    # 새로 후보에 든 회사는 항상 조회, 이미 물어봤는데 자료가 없던 회사는 refresh일 때만 다시 조회
    todo = [c for c in corps if c not in cache and (refresh or c not in asked)]
    for i in range(0, len(todo), 100):
        chunk = todo[i:i + 100]
        j = dart("fnlttMultiAcnt.json", {"corp_code": ",".join(chunk), "bsns_year": str(year), "reprt_code": reprt})
        per = {}
        for it in (j or {}).get("list", []):
            per.setdefault(it["corp_code"], []).append(it)
        for c, items in per.items():
            has_cfs = any(it.get("fs_div") == "CFS" for it in items)
            out = {}
            for it in items:
                if (it.get("fs_div") == "CFS") != has_cfs:
                    continue
                nm = (it.get("account_nm") or "").replace(" ", "")
                for k, keys in ACC.items():
                    if k not in out and any(nm == x or (k != "capital" and nm.startswith(x)) for x in keys):
                        out[k] = [num(it.get("thstrm_amount")), num(it.get("frmtrm_amount")),
                                  num(it.get("bfefrmtrm_amount")), num(it.get("thstrm_add_amount")),
                                  num(it.get("frmtrm_add_amount"))]
            cache[c] = out
    asked |= set(todo)
    if todo:
        save(name, {**cache, "_asked": sorted(asked)})
        log(f"  주요계정 {year}/{reprt}: {len(cache)}개사")
    return cache


def interest_expense(corp, year, cache):
    key = f"{corp}_{year}"
    if key in cache:
        return cache[key]
    found = None
    for fs in ("CFS", "OFS"):
        j = dart("fnlttSinglAcntAll.json", {"corp_code": corp, "bsns_year": str(year), "reprt_code": "11011", "fs_div": fs})
        if not j:
            continue
        cand = {}
        for it in j.get("list", []):
            nm = (it.get("account_nm") or "").replace(" ", "")
            aid = it.get("account_id", "")
            v = num(it.get("thstrm_amount"))
            if v is None:
                continue
            if it.get("sj_div") in ("IS", "CIS") and "이자비용" in nm:
                cand.setdefault("is", abs(v))
            elif it.get("sj_div") == "CF" and re.search(r"이자(의)?지급", nm):
                cand.setdefault("cf", abs(v))
            elif it.get("sj_div") in ("IS", "CIS") and (aid == "ifrs-full_FinanceCosts" or nm in ("금융원가", "금융비용")):
                cand.setdefault("fc", abs(v))
        if j.get("list"):
            found = {"v": cand.get("is") or cand.get("cf") or cand.get("fc") or 0,
                     "src": "이자비용" if "is" in cand else "이자지급" if "cf" in cand else "금융원가" if "fc" in cand else "없음"}
            break
    cache[key] = found
    return found


def audit_opinion(corp, year, cache):
    key = f"{corp}_{year}"
    if key in cache:
        return cache[key]
    j = dart("accnutAdtorNmNdAdtOpinion.json", {"corp_code": corp, "bsns_year": str(year), "reprt_code": "11011"})
    op = None
    for it in (j or {}).get("list", []):
        if "당기" in (it.get("bsns_year") or "") and (it.get("adt_opinion") or "").strip() not in ("", "-"):
            op = it["adt_opinion"].strip()
            break
    cache[key] = op
    return op


def quarter_keys(today):
    """최근 분기 보고서 후보(최신순 6개): (연도, 보고서코드, 라벨, 제출기한)"""
    out = []
    for yy in (today.year, today.year - 1, today.year - 2):
        for rc, lab, start, due in (
            ("11011", "4Q", dt.date(yy + 1, 2, 1), dt.date(yy + 1, 4, 1)),
            ("11014", "3Q", dt.date(yy, 10, 20), dt.date(yy, 11, 15)),
            ("11012", "2Q", dt.date(yy, 7, 20), dt.date(yy, 8, 15)),
            ("11013", "1Q", dt.date(yy, 4, 20), dt.date(yy, 5, 16)),
        ):
            if start <= today:
                out.append((yy, rc, f"{str(yy)[2:]}.{lab}", due))
    return out[:6]


def quarters_for(corp, fins, keys):
    """분기 단독 영업이익 [(라벨, 당기, 전년동기)] 오래된→최신"""
    out = []
    for yy, rc, lab, _ in reversed(keys):
        f = fins.get((yy, rc), {}).get(corp, {}).get("op")
        if not f:
            continue
        if rc == "11011":
            q3 = fins.get((yy, "11014"), {}).get(corp, {}).get("op")
            if not q3 or q3[3] is None or q3[4] is None or f[0] is None or f[1] is None:
                continue
            out.append((lab, f[0] - q3[3], f[1] - q3[4]))
        else:
            if f[0] is None or f[1] is None:
                continue
            out.append((lab, f[0], f[1]))
    return out[-2:]


KINDS = [
    ("dilution", ("유상증자결정", "전환사채권발행결정", "신주인수권부사채권발행결정", "교환사채권발행결정")),
    ("buyback", ("자기주식취득결정", "자기주식취득신탁계약체결결정")),
    ("retire", ("주식소각결정",)),
    ("legal", ("횡령·배임혐의발생", "횡령ㆍ배임혐의발생", "소송등의제기", "소송등의 제기")),
    ("unfaithful", ("불성실공시법인지정",)),
]


SKIP = ("철회", "무상증자", "자회사", "종속회사", "예고", "취소", "자율공시", "일정금액미만", "경영권분쟁")


def kind_of(nm):
    """보고서명 → 종류. 정정·첨부 보고서, 자회사 공시, 예고·자율공시·경영권분쟁 소송은 제외"""
    n = nm.replace(" ", "")
    if n.startswith("[") or any(x in n for x in SKIP):
        return None
    for k, keys in KINDS:
        if any(x.replace(" ", "") in n for x in keys):
            return k
    return None


def disclosures(today):
    """코스피 주요사항(B)·거래소공시(I) 1년치 중 필요한 종류만. 증분 수집."""
    cache = load("disclosures", {"rows": {}, "last": {}})
    end = today
    for ty in ("B", "I"):
        last = cache["last"].get(ty)
        start = (dt.date.fromisoformat(last) - dt.timedelta(days=3)) if last else today - dt.timedelta(days=370)
        s = start
        while s <= end:
            e = min(end, s + dt.timedelta(days=88))
            page, total = 1, 1
            while page <= total:
                j = dart("list.json", {"bgn_de": s.strftime("%Y%m%d"), "end_de": e.strftime("%Y%m%d"),
                                       "corp_cls": "Y", "pblntf_ty": ty, "page_no": page, "page_count": 100})
                if not j:
                    break
                total = int(j.get("total_page") or 1)
                for it in j.get("list", []):
                    k = kind_of(it.get("report_nm", ""))
                    if k:
                        cache["rows"][it["rcept_no"]] = {"s": it.get("stock_code", ""), "d": it["rcept_dt"], "k": k,
                                                         "nm": re.sub(r"\s+", " ", it["report_nm"]).strip()}
                page += 1
            log(f"  공시({ty}) {s}~{e}: 누적 {len(cache['rows'])}건")
            s = e + dt.timedelta(days=1)
        cache["last"][ty] = end.isoformat()
    cut = (today - dt.timedelta(days=400)).strftime("%Y%m%d")
    cache["rows"] = {k: v for k, v in cache["rows"].items() if v["d"] >= cut}
    save("disclosures", cache)
    return cache["rows"]


INSTITUTION = re.compile(r"연금|공제회|자산운용|투자|증권|은행|보험|캐피탈|신탁|펀드|Fund|FUND|Capital|CAPITAL|Management|BlackRock|Vanguard|Norges|Government|GIC", re.I)


def insider(corp, today):
    """임원·주요주주 특정증권 소유상황 보고(최근 120일): 증가=매수 신호, 주요주주 감소=감점"""
    j = dart("elestock.json", {"corp_code": corp})
    out = []
    cut = (today - dt.timedelta(days=120)).strftime("%Y%m%d")
    for it in (j or {}).get("list", []):
        d = (it.get("rcept_dt") or "").replace("-", "")
        if d < cut:
            continue
        ch = num(it.get("sp_stock_lmp_irds_cnt"))
        if not ch:
            continue
        who = (it.get("repror") or "").strip()
        if INSTITUTION.search(who):
            continue  # 국민연금·운용사 등 기관 매매는 내부자 신호가 아님
        main = (it.get("isu_main_shrholdr") or "").strip()
        if ch > 0:
            out.append({"k": "insider_buy", "d": d, "who": who, "nm": "임원·주요주주 보유 증가"})
        elif main not in ("", "-"):
            out.append({"k": "holder_sell", "d": d, "who": who, "nm": "주요주주 보유 감소"})
    return out


# ───────────────────────── 4. 조립 ─────────────────────────
def series_for(code, cache, dates_set):
    return [(d, cache[d][code]) for d in sorted(cache) if code in cache[d] and d in dates_set]


def main():
    today = NOW.date()
    log(f"바닥 신호 수집 {NOW:%Y-%m-%d %H:%M} KST")

    # 1) 코스피 일봉 → 거래일 달력
    kospi_ts = fchart("KOSPI", 1400)
    dates = kospi_ts["d"]
    if len(dates) < 300:
        raise SystemExit("[중단] 코스피 지수 일봉을 받지 못했습니다.")
    asof = dates[-1]
    kospi = dict(zip(kospi_ts["d"], kospi_ts["c"]))
    dset = set(dates)
    log(f"기준 거래일 {asof}")

    # 2) 후보군
    ranked = universe_naver()
    base = []
    excluded = []
    for r in ranked:
        if r["code"][-1] != "0" or re.search(r"스팩|리츠|인프라|제\d+호", r["name"]):
            continue
        base.append(r)
        if len(base) >= UCFG["top_n"]:
            break
    flags = flagged_naver()

    # 3) 일봉
    ts = {}
    for i, r in enumerate(base):
        try:
            t = fchart(r["code"], 300)
            if len(t["c"]) >= 130:
                ts[r["code"]] = t
        except Exception as e:  # noqa: BLE001
            err(f"일봉 {r['name']}", e)
        time.sleep(0.08)
        if (i + 1) % 50 == 0:
            log(f"  일봉 {i + 1}/{len(base)}")

    # 4) DART 재무 필터
    corp_map, induty, fins, qkeys, events, aud, intr = {}, {}, {}, [], {}, {}, {}
    ay = today.year - 1 if today >= dt.date(today.year, 4, 15) else today.year - 2
    disc = {}
    if DART_KEY:
        try:
            cc = corp_codes()
            corp_map = {r["code"]: cc.get(r["code"]) for r in base if cc.get(r["code"])}
            corps = sorted(set(corp_map.values()))
            induty = company(corps)
            fins[(ay, "11011")] = multi(corps, ay, "11011", refresh=True)
            qkeys = quarter_keys(today)
            for yy, rc, lab, due in qkeys:
                fresh = today <= due + dt.timedelta(days=45)
                fins[(yy, rc)] = multi(corps, yy, rc, refresh=fresh)
            aud = load("audit")
            intr = load("interest")
            for i, c in enumerate(corps):
                audit_opinion(c, ay, aud)
                if not induty.get(c, "").startswith(("64", "65", "66")):
                    interest_expense(c, ay, intr)
                if (i + 1) % 50 == 0:
                    save("audit", aud)
                    save("interest", intr)
                    log(f"  감사의견·이자비용 {i + 1}/{len(corps)}")
            save("audit", aud)
            save("interest", intr)
            disc = disclosures(today)
            for c in corps:
                events[c] = insider(c, today)
            log(f"  임원·주요주주 보고 확인 {len(corps)}개사")
        except SystemExit as e:
            err("OpenDART", e)
        except Exception as e:  # noqa: BLE001
            err("OpenDART", e)
            traceback.print_exc()
    else:
        err("OpenDART", "DART_API_KEY 가 없습니다. 재무 필터·공시·실적 항목은 미수집 처리")

    for no, row in disc.items():
        c = corp_map.get(row["s"])
        k = kind_of(row["nm"])  # 저장된 공시도 최신 분류 규칙으로 다시 거름
        if c and k:
            events.setdefault(c, []).append({"k": k, "d": row["d"], "nm": row["nm"]})

    # 5) 한국거래소
    st = krx()
    flows = foreign = short = fund = {}
    if st:
        for name, fn in (("수급", lambda: krx_flows(st, dates)), ("외국인 지분율", lambda: krx_foreign(st, dates)),
                         ("공매도", lambda: krx_short(st, dates)), ("PER·PBR", lambda: krx_fund(st, dates))):
            try:
                res = fn()
                if name == "수급":
                    flows = res
                elif name == "외국인 지분율":
                    foreign = res
                elif name == "공매도":
                    short = res
                else:
                    fund = res
            except Exception as e:  # noqa: BLE001
                err(f"한국거래소 {name}", e)

    # 6) 필터 + 점수
    items, stage_hist = [], load("stage_hist")
    today_s = asof
    for r in base:
        code, name = r["code"], r["name"]
        why = None
        t = ts.get(code)
        corp = corp_map.get(code)
        if code in flags:
            why = flags[code]
        elif not t:
            why = "일봉 부족(신규상장 등)"
        else:
            tv = sum(c * v for c, v in zip(t["c"][-20:], t["v"][-20:])) / 20 / 1e8
            if tv < UCFG["min_trading_value_eok"]:
                why = f"거래대금 부족({tv:,.0f}억)"
        if not why and corp:
            if any(e["k"] == "unfaithful" and SG.days_between(e["d"], today_s) <= 365 for e in events.get(corp, [])):
                why = "불성실공시법인 지정(1년 내)"
            op = aud.get(f"{corp}_{ay}")
            if not why and op and ("적정" not in op or any(x in op for x in ("부적정", "한정", "거절"))):
                why = f"감사의견 {op}"
            a = fins.get((ay, "11011"), {}).get(corp)
            if not why and a:
                eq, cap = (a.get("equity") or [None])[0], (a.get("capital") or [None])[0]
                fin_co = induty.get(corp, "").startswith(("64", "65", "66"))
                if eq is not None and cap and eq < cap:
                    why = "자본잠식"
                ops = [x for x in (a.get("op") or [])[:3] if x is not None]
                if not why and not fin_co and len(ops) == 3 and sum(1 for x in ops if x > 0) < UCFG["min_profit_years_of_3"]:
                    why = f"최근 3년 영업흑자 {sum(1 for x in ops if x > 0)}년"
                ie = intr.get(f"{corp}_{ay}")
                if not why and not fin_co and ie and ie["v"] > 0 and ops:
                    cov = ops[0] / ie["v"]
                    if cov <= UCFG["min_interest_coverage"]:
                        why = f"이자보상배율 {cov:.1f}배({ie['src']} 기준)"
        if why:
            excluded.append({"code": code, "name": name, "why": why})
            continue

        fl = series_for(code, flows, dset)
        fr = series_for(code, foreign, dset)
        sh = series_for(code, short, dset)
        fu = [(d, *v) for d, v in sorted((d, fund[d][code]) for d in fund if code in fund[d])]
        evs = sorted(events.get(corp, []), key=lambda e: e["d"]) if corp else []
        q = quarters_for(corp, fins, qkeys) if corp else []
        try:
            res = SG.score_stock(t, W, P, V, kospi, fl, fr, sh, fu, evs, q, today_s)
        except Exception as e:  # noqa: BLE001
            err(f"점수 {name}", e)
            traceback.print_exc()
            continue

        x = res["x"]
        h = [s for s in stage_hist.get(code, []) if s[0] != today_s] + [[today_s, res["stage"]]]
        h = h[-60:]
        stage_hist[code] = h
        since = today_s
        for d, s in reversed(h):
            if s != res["stage"]:
                break
            since = d
        low60 = min(x.l[-60:])
        cats = {}
        for k, (pts, _, _) in res["subs"].items():
            cat = SG.ITEMS[k][0]
            cats[cat] = round(cats.get(cat, 0) + (pts or 0), 1)
        items.append({
            "code": code, "name": name, "mcap": round(r["mcap"]), "rank": ranked.index(r) + 1,
            "close": x.c[-1], "chg": round((x.c[-1] / x.c[-2] - 1) * 100, 2),
            "low60": round((x.c[-1] / low60 - 1) * 100, 1),
            "hi120": round((x.c[-1] / max(x.h[-120:]) - 1) * 100, 1),
            "score": res["score"], "raw": res["raw"], "stage": res["stage"], "since": since,
            "cats": cats,
            "subs": {k: [v[0], v[1]] for k, v in res["subs"].items()},
            "pen": [list(p) for p in res["pen"]],
        })
        write_chart(code, name, x, res)

    save("stage_hist", {k: v for k, v in stage_hist.items() if any(i["code"] == k for i in items)})
    items.sort(key=lambda i: -i["score"])
    na = {k: True for k in ("D1", "D3", "D4", "E1", "F1", "G1") if items and all(i["subs"][k][0] is None for i in items)}
    out = {
        "meta": {
            "updated": NOW.strftime("%Y-%m-%d %H:%M"), "asof": f"{asof[:4]}-{asof[4:6]}-{asof[6:]}",
            "universe": len(base), "scored": len(items), "excluded": excluded, "errors": ERRORS,
            "calls": CALLS, "weights": W, "penalties": P, "valid_days": V, "universe_cfg": UCFG, "na": na,
            "items": {k: list(v) for k, v in SG.ITEMS.items()},
        },
        "items": items,
    }
    write(DATA / "latest.json", out)
    log(f"완료: 후보 {len(base)} → 채점 {len(items)} (제외 {len(excluded)}), 호출 {CALLS}, 오류 {len(ERRORS)}건")


def write_chart(code, name, x, res):
    n = min(120, x.n)
    s = slice(x.n - n, x.n)
    rd = lambda a, k=0: [None if v is None else round(v, k) for v in a[s]]
    marks = []
    for k, (pts, note, pos) in res["subs"].items():
        if pts and pos is not None and pos >= x.n - n and k[0] in "ABC" and k != "C3":
            marks.append([pos - (x.n - n), k])
    write(CHARTS / f"{code}.json", {
        "code": code, "name": name, "d": x.d[s], "o": rd(x.o), "h": rd(x.h), "l": rd(x.l), "c": rd(x.c),
        "v": rd(x.v), "ma20": rd(x.ma20), "ma60": rd(x.ma60), "bb": rd(x.bb), "rsi": rd(x.rsi, 1), "marks": marks,
    })


if __name__ == "__main__":
    main()
