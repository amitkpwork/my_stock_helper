"""Daily personalised brief: market snapshot + headlines + (optional) Claude-written summary."""
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo

FEEDS = {  # edit freely; any RSS/Atom URL works. Dead feeds are skipped.
    "Economic Times - Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Economic Times - Stocks": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "Mint - Business": "https://www.livemint.com/rss/business",
}
TICKERS = {"Nifty 50": "^NSEI", "Sensex": "^BSESN", "Bank Nifty": "^NSEBANK", "India VIX": "^INDIAVIX",
           "USD/INR": "INR=X", "Brent crude": "BZ=F", "S&P 500": "^GSPC"}


def now_ist() -> dt.datetime:
    return dt.datetime.now(ZoneInfo("Asia/Kolkata"))


def market_status(now: dt.datetime) -> str:
    if now.weekday() >= 5:
        return "Indian markets are closed today (weekend)."
    t = now.time()
    if t < dt.time(9, 15):
        s = "Markets open at 9:15 AM IST."
    elif t <= dt.time(15, 30):
        s = "Markets are open until 3:30 PM IST."
    else:
        s = "Markets have closed for the day."
    return s + " (Exchange holidays are not checked.)"


def snapshot(yf) -> list[dict]:
    out = []
    try:
        raw = yf.download(list(TICKERS.values()), period="10d", auto_adjust=True, progress=False, group_by="ticker")
    except Exception:
        return out
    for name, t in TICKERS.items():
        try:
            c = raw[t]["Close"].dropna()
            if len(c) >= 2:
                out.append({"name": name, "price": float(c.iloc[-1]), "chg_pct": float((c.iloc[-1] / c.iloc[-2] - 1) * 100),
                            "asof": str(c.index[-1].date())})
        except Exception:
            continue
    return out


def headlines(per_feed: int = 6) -> list[dict]:
    try:
        import feedparser
    except ImportError:
        return []
    seen, out = set(), []
    for src, url in FEEDS.items():
        try:
            for e in feedparser.parse(url).entries[:per_feed]:
                title = (e.get("title") or "").strip()
                if title and title.lower() not in seen:
                    seen.add(title.lower())
                    out.append({"source": src, "title": title, "link": e.get("link", "")})
        except Exception:
            continue
    return out


def _fmt(s: dict) -> str:
    arrow = "up" if s["chg_pct"] > 0 else "down" if s["chg_pct"] < 0 else "flat"
    return f"{s['name']} {arrow} {abs(s['chg_pct']):.2f}% at {s['price']:,.2f}"


def rule_based_brief(name: str, now: dt.datetime, snap: list[dict], news: list[dict], watch: list[dict]) -> str:
    """Plain facts only: no forecasts are invented."""
    by = {s["name"]: s for s in snap}
    lines = [f"Hello {name}, today is {now:%A, %d %B %Y}. {market_status(now)}"]
    idx = [by[k] for k in ("Nifty 50", "Sensex", "Bank Nifty") if k in by]
    if idx:
        lines.append("Last session: " + "; ".join(_fmt(s) for s in idx) + f" (as of {idx[0]['asof']}).")
    cues = [by[k] for k in ("S&P 500", "Brent crude", "USD/INR", "India VIX") if k in by]
    if cues:
        lines.append("Cues to watch: " + "; ".join(_fmt(s) for s in cues) + ".")
        if "India VIX" in by and by["India VIX"]["chg_pct"] > 5:
            lines.append("India VIX jumped, which usually means traders are pricing in bigger swings.")
    strong = [w for w in watch if w.get("Signal") == "Strong"]
    movers = sorted([w for w in watch if w.get("Day %") is not None], key=lambda w: w["Day %"])
    if movers:
        lines.append(f"On your watchlist: biggest gainer {movers[-1]['Symbol']} ({movers[-1]['Day %']:+.2f}%), "
                     f"biggest faller {movers[0]['Symbol']} ({movers[0]['Day %']:+.2f}%)"
                     + (f"; {len(strong)} stock(s) currently score Strong." if strong else "."))
    return "\n\n".join(lines)


SYSTEM = ("You write a short morning market brief for an Indian retail investor. Use ONLY the JSON facts given "
          "(market snapshot, headlines, watchlist). Start with 'Hello <name>, today is <date>.' Then 4-6 sentences: "
          "what happened last session, the main themes in the headlines, and what to watch today. Phrase anything "
          "forward-looking as a possibility tied to a specific fact ('could', 'may'), never as a prediction. "
          "Do not give buy/sell advice, price targets or numbers that are not in the data. Plain language, no markdown.")


def claude_brief(payload: dict) -> str | None:
    """Optional. Needs `pip install anthropic` and the ANTHROPIC_API_KEY environment variable."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        msg = anthropic.Anthropic(api_key=key).messages.create(
            model="claude-sonnet-5-5", max_tokens=500, system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, default=str)}])
        return "".join(b.text for b in msg.content if b.type == "text").strip() or None
    except Exception:
        return None
