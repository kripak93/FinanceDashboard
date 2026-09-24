"""Live price fetching via yfinance for NSE/BSE holdings.

Converts Google-Finance-style symbols (NSE:RELIANCE / BSE:INDBNK) into
yfinance tickers (RELIANCE.NS / INDBNK.BO) and fetches current prices.
"""
import yfinance as yf


def to_yf_ticker(gsymbol):
    """'NSE:RELIANCE' -> 'RELIANCE.NS' ; 'BSE:INDBNK' -> 'INDBNK.BO'.
    Returns None if the symbol is blank/unlistable."""
    if not gsymbol or ':' not in gsymbol:
        return None
    exch, sym = gsymbol.split(':', 1)
    if exch == 'NSE':
        return f"{sym}.NS"
    if exch == 'BSE':
        return f"{sym}.BO"
    return None


def fetch_quotes(gsymbols):
    """Fetch current price and previous close for Google-Finance-style symbols.
    Returns {gsymbol: {"price": float, "prev_close": float}}.
    Symbols that can't be resolved are omitted."""
    mapping = {}
    for g in gsymbols:
        t = to_yf_ticker(g)
        if t:
            mapping[t] = g

    quotes = {}
    if not mapping:
        return quotes

    tickers = list(mapping.keys())
    try:
        data = yf.download(
            tickers=" ".join(tickers),
            period="5d",
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
    except Exception:
        data = None

    for t in tickers:
        price = prev = None
        try:
            if data is not None and len(tickers) > 1 and t in data.columns.get_level_values(0):
                closes = data[t]["Close"].dropna()
            elif data is not None and len(tickers) == 1:
                closes = data["Close"].dropna()
            else:
                closes = None
            if closes is not None and len(closes):
                price = float(closes.iloc[-1])
                prev = float(closes.iloc[-2]) if len(closes) >= 2 else price
        except Exception:
            price = prev = None

        if price is None:
            try:
                fi = yf.Ticker(t).fast_info
                price = float(fi.get("last_price") or fi.get("lastPrice"))
                prev = float(fi.get("previous_close") or fi.get("previousClose") or price)
            except Exception:
                price = prev = None

        if price is not None:
            quotes[mapping[t]] = {"price": round(price, 2),
                                  "prev_close": round(prev if prev else price, 2)}

    return quotes


def fetch_prices(gsymbols):
    """Backward-compatible helper returning {gsymbol: price}."""
    return {g: q["price"] for g, q in fetch_quotes(gsymbols).items()}
