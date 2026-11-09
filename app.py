"""my_stock_helper - track NSE/BSE stocks and rank them from price history.
Run:  pip install -r requirements.txt  &&  streamlit run app.py
Educational screening tool, not investment advice."""
import hmac
import json
import math
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from plotly.subplots import make_subplots

import briefing as br
import categories as cat
import signals as sg
import ui
import storage as store

DEFAULT = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ITC"]
BENCH = {".NS": "^NSEI", ".BO": "^BSESN"}

st.set_page_config(page_title="my_stock_helper", layout="wide", initial_sidebar_state="collapsed")

# Optional password gate for the hosted version (set APP_PASSWORD in secrets).
_pw = store.secret("APP_PASSWORD")
if _pw and not st.session_state.get("authed"):
    st.title("my_stock_helper")
    _entered = st.text_input("Password", type="password")
    if _entered and hmac.compare_digest(str(_entered), str(_pw)):
        st.session_state["authed"] = True
        st.rerun()
    elif _entered:
        st.error("Wrong password")
    st.stop()
if _key := store.secret("ANTHROPIC_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = str(_key)


def norm(sym: str, ex: str) -> str:
    s = sym.strip().upper()
    return s if s and (s.endswith(".NS") or s.endswith(".BO") or s.startswith("^")) else (s + ex if s else "")


@st.cache_data(ttl=900, show_spinner=False)
def load(symbol: str, period: str = "5y") -> pd.DataFrame:
    df = yf.download(symbol, period=period, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    return df.dropna(subset=["Close"])


@st.cache_data(ttl=3600, show_spinner=False)
def fundamentals(symbol: str) -> dict:
    try:
        i = yf.Ticker(symbol).info
    except Exception:
        return {}
    keys = {"trailingPE": "P/E", "priceToBook": "P/B", "returnOnEquity": "ROE", "revenueGrowth": "Revenue growth",
            "debtToEquity": "Debt/Equity", "dividendYield": "Dividend yield", "marketCap": "Market cap"}
    return {v: i.get(k) for k, v in keys.items() if i.get(k) is not None}



NIFTY50 = ("ADANIENT ADANIPORTS APOLLOHOSP ASIANPAINT AXISBANK BAJAJ-AUTO BAJFINANCE BAJAJFINSV BEL BHARTIARTL CIPLA "
           "COALINDIA DRREDDY EICHERMOT ETERNAL GRASIM HCLTECH HDFCBANK HDFCLIFE HINDALCO HINDUNILVR ICICIBANK "
           "INDUSINDBK INFY ITC JIOFIN JSWSTEEL KOTAKBANK LT M&M MARUTI NESTLEIND NTPC ONGC POWERGRID RELIANCE "
           "SBILIFE SBIN SHRIRAMFIN SUNPHARMA TATACONSUM TATASTEEL TCS TECHM TITAN TRENT ULTRACEMCO WIPRO").split()


NIFTY_NEXT50 = ("ABB ADANIENSOL ADANIGREEN ADANIPOWER AMBUJACEM BAJAJHLDNG BANKBARODA BOSCHLTD BRITANNIA CANBK CGPOWER "
                "CHOLAFIN DABUR DIVISLAB DLF DMART GAIL GODREJCP HAVELLS HAL HINDZINC HYUNDAI ICICIGI ICICIPRULI "
                "INDHOTEL INDIGO IOC IRFC JINDALSTEL JSWENERGY LICI LODHA LTIM MAZDOCK MOTHERSON NAUKRI PFC PIDILITIND "
                "PNB RECLTD SHREECEM SIEMENS SWIGGY TATAPOWER TORNTPHARM TVSMOTOR UNITDSPR VBL VEDL ZYDUSLIFE").split()
NIFTY100 = NIFTY50 + NIFTY_NEXT50
INDEX_SOURCES = {"Nifty 50": ("nifty50", NIFTY50), "Nifty 100": ("nifty100", NIFTY100), "Nifty 500": ("nifty500", None)}


@st.cache_data(ttl=86400, show_spinner=False)
def index_symbols(slug: str) -> list:
    """Live constituents from niftyindices.com. Raises on failure (so failures are not cached)."""
    url = f"https://www.niftyindices.com/IndexConstituent/ind_{slug}list.csv"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        df = pd.read_csv(r)
    df.columns = [c.strip() for c in df.columns]
    syms = [str(x).strip() for x in df["Symbol"].dropna() if not str(x).upper().startswith("DUMMY")]
    if len(syms) < 20:
        raise ValueError("unexpected file")
    return [x + ".NS" for x in syms]


def pin_to_watchlist(new: list):
    """Button callback: merge screener picks into the watchlist box and save to disk."""
    exch = st.session_state.get("ex_choice", ".NS")
    cur = [norm(x, exch) for x in st.session_state.get("wl_text", "").splitlines() if x.strip()]
    added = [x for x in new if x not in cur]
    merged = cur + added
    short = [x.rsplit(".", 1)[0] if x.endswith(exch) else x for x in merged]
    st.session_state["wl_text"] = "\n".join(short)
    ok = store.save("watchlist.json", short)
    st.session_state["pin_gen"] = st.session_state.get("pin_gen", 0) + 1  # resets the checkboxes
    st.session_state["pin_msg"] = f"Added {len(added)} stock(s) to your watchlist" + (" (the rest were already there)." if len(added) < len(new) else ".") + ("" if ok else " Could not save to storage; it will be lost on restart.")


def extract(raw: pd.DataFrame, sym: str):
    """Pull one symbol's OHLCV out of a multi-symbol yfinance download."""
    if raw is None or raw.empty:
        return None
    df = raw
    if isinstance(raw.columns, pd.MultiIndex):
        if sym not in raw.columns.get_level_values(0):
            return None
        df = raw[sym]
    df = df.dropna(subset=["Close"])
    return df if len(df) else None


@st.cache_data(ttl=900, show_spinner=False)
def load_many(symbols: tuple, period: str = "2y") -> dict:
    out = {}
    for i in range(0, len(symbols), 40):  # chunks keep requests small
        chunk = list(symbols[i:i + 40])
        try:
            raw = yf.download(chunk, period=period, auto_adjust=True, progress=False, group_by="ticker", threads=True)
        except Exception:
            continue
        for sym in chunk:
            df = extract(raw, sym)
            if df is not None:
                out[sym] = df
    return out


@st.cache_data(ttl=900, show_spinner=False)
def cached_snapshot():
    return br.snapshot(yf)


@st.cache_data(ttl=900, show_spinner=False)
def cached_news():
    return br.headlines()


@st.cache_data(ttl=1800, show_spinner=False)
def cached_claude_brief(payload_json: str):
    return br.claude_brief(json.loads(payload_json))


@st.cache_data(ttl=86400, show_spinner=False)
def load_meta(symbols: tuple) -> dict:
    def one(sym):
        try:
            i = yf.Ticker(sym).info
            mc = i.get("marketCap")
            return sym, {"Sector": i.get("sector"), "Industry": i.get("industry"), "MCap (Rs cr)": mc / 1e7 if mc else None}
        except Exception:
            return sym, {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        return dict(pool.map(one, symbols))


def analyse(symbol: str):
    df = load(symbol)
    if df.empty:
        return None
    bench = load(BENCH[symbol[-3:]])["Close"] if symbol[-3:] in BENCH else None
    return sg.add_indicators(df, bench)


# ---------- sidebar: watchlist ----------
st.sidebar.title("my_stock_helper")
if "cfg" not in st.session_state:
    st.session_state["cfg"] = store.load("settings.json", {})
_cfg = st.session_state["cfg"]
user_name = st.sidebar.text_input("Your name (for the daily brief)", value=_cfg.get("name", "Amit"))
if user_name != _cfg.get("name"):
    _cfg["name"] = user_name
    store.save("settings.json", _cfg)
ex = st.sidebar.radio("Default exchange", [".NS", ".BO"], key="ex_choice", format_func=lambda x: "NSE" if x == ".NS" else "BSE")
if "wl_text" not in st.session_state:
    st.session_state["wl_text"] = "\n".join(store.load("watchlist.json", DEFAULT))
txt = st.sidebar.text_area("Watchlist (one symbol per line)", key="wl_text", height=220,
                           help="Plain names get the exchange suffix added. You can also type RELIANCE.BO to override.")
symbols = list(dict.fromkeys(filter(None, (norm(s, ex) for s in txt.splitlines()))))
if st.sidebar.button("Save watchlist"):
    ok = store.save("watchlist.json", [s.rsplit(".", 1)[0] if s.endswith(ex) else s for s in symbols])
    st.sidebar.success("Saved") if ok else st.sidebar.error("Could not save (check GIST_ID / GITHUB_TOKEN secrets)")
st.sidebar.markdown("**Market-cap buckets (screener)**")
large_cr = st.sidebar.number_input("Large cap if market cap >= (Rs crore)", value=80000, step=5000)
mid_cr = st.sidebar.number_input("Mid cap if >= (Rs crore); below = Small", value=25000, step=2500)
st.sidebar.caption("Approximate. SEBI/AMFI publish the official large/mid/small list twice a year; adjust these to match.")
st.sidebar.caption("Data: Yahoo Finance via yfinance (delayed, unofficial). Not investment advice.")

tab0, tab1, tab2, tab3, tab4 = st.tabs(["Summary", "Watchlist & ranking", "Stock detail", "Backtest", "Screener"])

# ---------- tab 1 ----------
with tab1:
    rows = []
    with st.spinner("Fetching prices..."):
        for s in symbols:
            d = analyse(s)
            if d is None or len(d) < 2:
                rows.append({"Symbol": s, "Signal": "No data"})
                continue
            last, prev = d.iloc[-1], d.iloc[-2]
            sc = sg.score_series(d).iloc[-1]
            rows.append({"Symbol": s, "Price": round(last.Close, 2), "Day %": round((last.Close / prev.Close - 1) * 100, 2),
                         "From 52w high %": round(last.DD_FROM_HIGH, 1), "RSI": round(last.RSI, 1),
                         "Score": sc, f"Score (max {sg.MAX_SCORE})": sc, "Signal": sg.label(sc)})
    tbl = pd.DataFrame(rows)
    if "Score" in tbl:
        tbl = tbl.sort_values("Score", ascending=False, na_position="last").drop(columns="Score")
    st.subheader("Ranked by technical score")
    st.dataframe(ui.style_table(tbl, ("Day %",), "Signal"), width="stretch", hide_index=True)
    st.caption("Higher score = stronger trend, momentum and relative strength in the stock's own history. "
               "It is a shortlist aid: check the Backtest tab and fundamentals before acting.")

# ---------- tab 0: summary (filled after the watchlist is scored) ----------
with tab0:
    now = br.now_ist()
    snap, news = cached_snapshot(), cached_news()
    watch = [r for r in rows if r.get("Signal") not in (None, "No data")]
    payload = {"name": user_name, "date": f"{now:%A, %d %B %Y}", "market_status": br.market_status(now),
               "snapshot": snap, "headlines": [n["title"] for n in news[:12]],
               "watchlist": [{k: r.get(k) for k in ("Symbol", "Day %", "Signal")} for r in watch]}
    ai_text = cached_claude_brief(json.dumps(payload, default=str))
    st.markdown(f"### Good day, {user_name}")
    left, right = st.columns([3, 2])
    with left:
        st.write(ai_text or br.rule_based_brief(user_name, now, snap, news, watch))
        st.caption("AI-written from the data and headlines; not a forecast or advice." if ai_text else
                   "Fact-based summary. Set ANTHROPIC_API_KEY (and pip install anthropic) for a written outlook.")
        if news:
            st.markdown("**Headlines**")
            for n in news[:6]:
                st.markdown(f"- [{n['title']}]({n['link']})")
            if len(news) > 6:
                with st.expander(f"More headlines ({len(news) - 6})"):
                    for n in news[6:]:
                        st.markdown(f"- [{n['title']}]({n['link']}) - *{n['source']}*")
        else:
            st.caption("No headlines loaded (feeds unreachable or feedparser not installed).")
    with right:
        if snap:
            st.markdown("**Markets**")
            sdf = pd.DataFrame([{"Market": m["name"], "Level": m["price"], "Change %": m["chg_pct"]} for m in snap])
            st.dataframe(ui.style_table(sdf, ("Change %",)), hide_index=True, width="stretch")
            st.caption("Colour shows direction only. A rising India VIX or crude price is usually a caution sign.")
        mv = pd.DataFrame([{"Symbol": r["Symbol"], "Price": r.get("Price"), "Day %": r.get("Day %"), "Signal": r.get("Signal")}
                           for r in watch if r.get("Price") is not None])
        if not mv.empty:
            st.markdown("**Your watchlist today**")
            st.dataframe(ui.style_table(mv.sort_values("Day %", ascending=False), ("Day %",), "Signal"),
                         hide_index=True, width="stretch")

# ---------- tab 2 ----------
with tab2:
    ca, cb = st.columns(2)
    pick = ca.selectbox("From your watchlist", symbols) if symbols else None
    typed = cb.text_input("Or type any symbol", key="detail_sym", placeholder="e.g. TATAMOTORS, ZOMATO, 500325.BO",
                          help="Plain names use the exchange chosen in the sidebar. Add .NS or .BO to force one.")
    sym = norm(typed, ex) if typed.strip() else pick
    if not sym:
        st.info("Add a stock to your watchlist, or type any NSE/BSE symbol above.")
    else:
        d = analyse(sym)
        if d is None:
            st.warning(f"No data found for {sym}. Check the spelling. NSE names look like RELIANCE; "
                       "BSE can use RELIANCE.BO or the numeric code such as 500325.BO.")
        else:
            if sym not in symbols:
                st.button(f"Add {sym} to watchlist", on_click=pin_to_watchlist, args=([sym],))
            if len(d) < 260:
                st.caption("Under about a year of history, so the 200-day average and score are not reliable for this stock.")
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
            fig.add_trace(go.Candlestick(x=d.index, open=d.Open, high=d.High, low=d.Low, close=d.Close, name="Price", increasing_line_color=ui.GREEN, decreasing_line_color=ui.RED), 1, 1)
            for col, color in [("SMA50", "orange"), ("SMA200", "purple")]:
                fig.add_trace(go.Scatter(x=d.index, y=d[col], name=col, line=dict(color=color, width=1.3)), 1, 1)
            fig.add_trace(go.Scatter(x=d.index, y=d.RSI, name="RSI", line=dict(width=1.2)), 2, 1)
            fig.add_hline(y=70, line_dash="dot", row=2, col=1)
            fig.add_hline(y=30, line_dash="dot", row=2, col=1)
            fig.update_layout(height=620, xaxis_rangeslider_visible=False, margin=dict(t=20, b=10))
            st.plotly_chart(fig, width="stretch")

            comp = sg.score_components(d).iloc[-1]
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**Why the score is {int(comp.sum())} / {sg.MAX_SCORE}**")
                st.dataframe(ui.style_table(comp.rename("Points").to_frame(), ("Points",)), width="stretch")
            with c2:
                st.markdown("**Fundamentals (context only)**")
                f = fundamentals(sym)
                st.dataframe(pd.Series(f, name="Value").astype(str).to_frame(), width="stretch") if f else st.info("Not available.")

# ---------- tab 3 ----------
with tab3:
    if symbols:
        sym = st.selectbox("Symbol to backtest", symbols, key="bt")
        a, b = st.columns(2)
        entry = a.slider("Buy when score >=", 3, 8, 5)
        exit_ = b.slider("Sell when score <=", -2, 5, 2)
        d = analyse(sym)
        if d is None or len(d) < 260:
            st.warning("Need roughly 1.5+ years of history.")
        else:
            r = sg.backtest(d, entry, exit_)
            m = pd.DataFrame({"Strategy": r["strategy"], "Buy & hold": r["buy_hold"]}).round(1)
            st.dataframe(ui.style_table(m, tuple(m.columns), num_fmt="{:+.1f}"), width="stretch")
            st.line_chart(pd.DataFrame({"Strategy": r["equity"], "Buy & hold": r["bh_equity"]}))
            st.caption(f"{r['trades']} trades, in market {r['time_in_market_%']:.0f}% of the time, 0.1% cost per trade. "
                       "Past results on one stock say little about the future; test several stocks and periods.")

# ---------- tab 4: screener ----------
with tab4:
    st.subheader("Screen a whole index or your own list")
    src = st.radio("Universe", ["Nifty 50", "Nifty 100", "Nifty 500", "Upload NSE index CSV", "Paste symbols"], horizontal=True)
    universe = []
    if src in INDEX_SOURCES:
        slug, fallback = INDEX_SOURCES[src]
        try:
            universe = index_symbols(slug)
            st.caption(f"Loaded {len(universe)} current constituents from niftyindices.com.")
        except Exception:
            if fallback:
                universe = [x + ".NS" for x in fallback]
                st.caption("Could not reach niftyindices.com, so this is a built-in approximate list "
                           "(membership changes; failed symbols are listed below the table).")
            else:
                st.error("Could not download this list. Get the CSV from niftyindices.com and use 'Upload NSE index CSV'.")
        if src == "Nifty 500":
            st.caption("500 stocks can take several minutes on the first run; results are cached for 15 minutes.")
    elif src.startswith("Upload"):
        st.caption("Download any index constituents CSV from niftyindices.com (e.g. Midcap 150, Smallcap 250) "
                   "and upload it. The 'Symbol' column is used.")
        up = st.file_uploader("Index CSV", type="csv")
        if up is not None:
            col = pd.read_csv(up)
            col.columns = [c.strip() for c in col.columns]
            if "Symbol" in col:
                universe = [norm(x, ".NS") for x in col["Symbol"].dropna().astype(str) if not x.upper().startswith("DUMMY")]
            else:
                st.error("No 'Symbol' column found.")
    else:
        pasted = st.text_area("Symbols (comma or newline separated)")
        universe = [norm(x, ex) for x in pasted.replace(",", "\n").splitlines() if x.strip()]
    universe = list(dict.fromkeys(universe))

    cat_on = st.checkbox("Add market-cap and sector categories (one extra lookup per stock, slower)", value=True)
    cat_min = st.number_input("Look up categories only for stocks scoring at least", -2, 8, 4)
    if universe and st.button(f"Run screener on {len(universe)} stocks"):
        with st.spinner("Downloading prices and scoring... large lists can take a few minutes"):
            data = load_many(tuple(universe))
            bench = load("^NSEI")["Close"]
            res = []
            for sym, df in data.items():
                if len(df) < 260:
                    continue
                d = sg.add_indicators(df, bench if sym.endswith(".NS") else None)
                sc = sg.score_series(d).iloc[-1]
                last = d.iloc[-1]
                res.append({"Symbol": sym, "Price": round(last.Close, 2), "Score": sc, "Signal": sg.label(sc),
                            "RSI": round(last.RSI, 1), "From 52w high %": round(last.DD_FROM_HIGH, 1),
                            "6m vs index %": round(last.REL_6M, 1) if pd.notna(last.REL_6M) else None})
        df_res = pd.DataFrame(res)
        if cat_on and not df_res.empty:
            picks = tuple(df_res.loc[df_res.Score >= cat_min, "Symbol"])
            with st.spinner(f"Looking up sector and market cap for {len(picks)} stocks..."):
                meta = load_meta(picks)
            for col in ["Sector", "Industry", "MCap (Rs cr)"]:
                df_res[col] = df_res.Symbol.map(lambda x: meta.get(x, {}).get(col))
        st.session_state["screen"] = (df_res, [u for u in universe if u not in data])

    if "screen" in st.session_state:
        res, missing = st.session_state["screen"]
        if res.empty:
            st.warning("No stocks could be scored.")
        else:
            lo = st.slider("Minimum score", -2, sg.MAX_SCORE, 5)
            res = res.copy()
            if "Sector" in res:
                res["Cap"] = res["MCap (Rs cr)"].map(lambda v: cat.cap_bucket(v, large_cr, mid_cr))
                res["Style"] = res["Sector"].map(cat.style)
            view = res[res.Score >= lo]
            if "Cap" in view:
                f1, f2 = st.columns(2)
                caps = f1.multiselect("Cap size", ["Large", "Mid", "Small", "n/a"], default=["Large", "Mid", "Small", "n/a"])
                styles = f2.multiselect("Style", ["Cyclical", "Defensive", "Other", "n/a"], default=["Cyclical", "Defensive", "Other", "n/a"])
                view = view[view.Cap.isin(caps) & view.Style.isin(styles)]
            pmax = float(res.Price.max())
            pts = [0] + [v for v in (50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000) if v < pmax] + [int(math.ceil(pmax))]
            plo, phi = st.select_slider("Price range (Rs, last close)", options=pts, value=(pts[0], pts[-1]),
                                        format_func=lambda v: f"{v:,}")
            view = view[(view.Price >= plo) & (view.Price <= phi)]
            view = view.sort_values(["Score", "6m vs index %"], ascending=False).reset_index(drop=True)
            st.write(f"{len(view)} of {len(res)} stocks match (score >= {lo}, price Rs {plo:,} to {phi:,})")
            show = view.copy()
            show.insert(0, "In watchlist", show.Symbol.isin(symbols))
            show.insert(0, "Pin", False)
            editor_key = f"pins_{st.session_state.get('pin_gen', 0)}_{lo}_{plo}_{phi}_{len(view)}"
            edited = st.data_editor(ui.style_table(show, ("6m vs index %",), "Signal"), key=editor_key, width="stretch", hide_index=True,
                                    disabled=[c for c in show.columns if c != "Pin"],
                                    column_config={"Pin": st.column_config.CheckboxColumn("Pin", help="Tick, then click the button below")})
            picked = edited.loc[edited["Pin"], "Symbol"].tolist()
            st.button(f"Pin {len(picked)} selected stock(s) to watchlist", disabled=not picked,
                      on_click=pin_to_watchlist, args=(picked,))
            if msg := st.session_state.pop("pin_msg", None):
                st.success(msg)
            st.download_button("Download CSV", view.to_csv(index=False), "screener.csv")
        if missing:
            st.caption(f"Skipped (no data or under ~1 year of history): {', '.join(missing)}")
