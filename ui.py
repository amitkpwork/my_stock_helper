"""Table colouring helpers: green for positive, red for negative, coloured signal badges."""
import numpy as np
import pandas as pd

GREEN, RED = "#16a34a", "#dc2626"
FORMATS = {"Price": "{:,.2f}", "Level": "{:,.2f}", "Day %": "{:+.2f}%", "Change %": "{:+.2f}%",
           "6m vs index %": "{:+.1f}%", "From 52w high %": "{:.1f}%", "RSI": "{:.1f}", "Points": "{:+.0f}"}
SIGNAL_STYLE = {
    "Strong": "background-color:#bbf7d0;color:#14532d;font-weight:600",
    "Positive": "background-color:#dcfce7;color:#166534",
    "Neutral": "background-color:#f3f4f6;color:#374151",
    "Weak": "background-color:#fecaca;color:#7f1d1d;font-weight:600",
}


def _safe(fmt: str):
    def f(v):
        if isinstance(v, (int, float, np.number)) and not isinstance(v, (bool, np.bool_)) and not pd.isna(v):
            return fmt.format(v)
        return "-" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
    return f


def _sign_color(v):
    if isinstance(v, (int, float, np.number)) and not isinstance(v, (bool, np.bool_)) and not pd.isna(v):
        if v > 0:
            return f"color:{GREEN};font-weight:600"
        if v < 0:
            return f"color:{RED};font-weight:600"
    return ""


def _map(sty, fn, cols):
    return (sty.map if hasattr(sty, "map") else sty.applymap)(fn, subset=cols)


def style_table(df: pd.DataFrame, pn_cols=(), signal_col: str | None = None, num_fmt: str | None = None):
    sty = df.style
    fm = {c: _safe(f) for c, f in FORMATS.items() if c in df.columns}
    if num_fmt:
        for c in df.select_dtypes("number").columns:
            fm.setdefault(c, _safe(num_fmt))
    if fm:
        sty = sty.format(fm, na_rep="-")
    cols = [c for c in pn_cols if c in df.columns]
    if cols:
        sty = _map(sty, _sign_color, cols)
    if signal_col and signal_col in df.columns:
        sty = _map(sty, lambda v: SIGNAL_STYLE.get(v, ""), [signal_col])
    return sty
