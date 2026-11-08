"""Indicators, scoring and backtest for my_stock_helper (pure pandas, no network)."""
import numpy as np
import pandas as pd

MAX_SCORE = 8


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    out = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    return out.where(dn != 0, 100.0)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def add_indicators(df: pd.DataFrame, bench: pd.Series | None = None) -> pd.DataFrame:
    d = df.copy()
    c = d["Close"]
    d["SMA50"] = c.rolling(50).mean()
    d["SMA200"] = c.rolling(200).mean()
    d["RSI"] = rsi(c)
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    d["MACD"] = ema12 - ema26
    d["MACD_SIG"] = d["MACD"].ewm(span=9, adjust=False).mean()
    d["ATR_PCT"] = atr(d) / c * 100
    d["HIGH_52W"] = c.rolling(252, min_periods=60).max()
    d["LOW_52W"] = c.rolling(252, min_periods=60).min()
    d["DD_FROM_HIGH"] = (c / d["HIGH_52W"] - 1) * 100
    if bench is not None and len(bench):
        b = bench.reindex(d.index).ffill()
        d["REL_6M"] = (c.pct_change(126) - b.pct_change(126)) * 100
    else:
        d["REL_6M"] = np.nan
    return d


def score_components(d: pd.DataFrame) -> pd.DataFrame:
    c = d["Close"]
    comp = pd.DataFrame(index=d.index)
    comp["Above 200-day avg (+2)"] = np.where(c > d["SMA200"], 2, 0)
    comp["50-day above 200-day (+1)"] = np.where(d["SMA50"] > d["SMA200"], 1, 0)
    comp["Above 50-day avg (+1)"] = np.where(c > d["SMA50"], 1, 0)
    comp["RSI healthy 45-70 (+1) / overheated >75 (-1)"] = np.where(
        d["RSI"].between(45, 70), 1, np.where(d["RSI"] > 75, -1, 0))
    comp["MACD above signal (+1)"] = np.where(d["MACD"] > d["MACD_SIG"], 1, 0)
    comp["Beating index over 6m (+1)"] = np.where(d["REL_6M"] > 0, 1, 0)
    comp["Within 15% of 52w high (+1)"] = np.where(d["DD_FROM_HIGH"] > -15, 1, 0)
    comp["Very volatile, ATR>4% (-1)"] = np.where(d["ATR_PCT"] > 4, -1, 0)
    return comp


def score_series(d: pd.DataFrame) -> pd.Series:
    s = score_components(d).sum(axis=1)
    return s.where(d["SMA200"].notna())  # need 200 days of history


def label(score: float) -> str:
    if pd.isna(score):
        return "Not enough history"
    if score >= 6:
        return "Strong"
    if score >= 4:
        return "Positive"
    if score >= 2:
        return "Neutral"
    return "Weak"


def backtest(d: pd.DataFrame, entry: int = 5, exit_: int = 2, cost: float = 0.001) -> dict:
    """Long-only: enter when score >= entry, exit when score <= exit_.
    Signal at close of day t is traded from day t+1 (no look-ahead)."""
    sc = score_series(d).dropna()
    px = d["Close"].reindex(sc.index)
    ret = px.pct_change().fillna(0)
    pos, held = [], 0
    for v in sc.values:
        if held == 0 and v >= entry:
            held = 1
        elif held == 1 and v <= exit_:
            held = 0
        pos.append(held)
    pos = pd.Series(pos, index=sc.index)
    strat = pos.shift(1).fillna(0) * ret - cost * pos.diff().abs().fillna(0)
    eq, bh = (1 + strat).cumprod(), (1 + ret).cumprod()

    def stats(curve):
        yrs = max((curve.index[-1] - curve.index[0]).days / 365.25, 1e-9)
        return {"total_%": (curve.iloc[-1] - 1) * 100,
                "cagr_%": (curve.iloc[-1] ** (1 / yrs) - 1) * 100,
                "max_dd_%": (curve / curve.cummax() - 1).min() * 100}

    return {"strategy": stats(eq), "buy_hold": stats(bh), "trades": int((pos.diff() == 1).sum()),
            "time_in_market_%": pos.mean() * 100, "equity": eq, "bh_equity": bh}
