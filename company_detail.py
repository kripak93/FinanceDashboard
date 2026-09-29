"""
On-demand company deep-dive data via yfinance.

Fetched only when a user selects a company, so it never slows the main
price tick. Results are cached by the caller (Streamlit) so re-selecting a
company is instant.
"""
import yfinance as yf
from live_prices import to_yf_ticker


INFO_FIELDS = {
    "longName": "Name",
    "sector": "Sector",
    "industry": "Industry",
    "marketCap": "Market Cap",
    "trailingPE": "P/E (TTM)",
    "priceToBook": "P/B",
    "beta": "Beta",
    "fiftyTwoWeekHigh": "52W High",
    "fiftyTwoWeekLow": "52W Low",
    "dividendYield": "Dividend Yield %",
    "dividendRate": "Dividend Rate (annual)",
}


def get_company_detail(gsymbol, face_value=None):
    """Return a dict of company data for one Google-Finance-style symbol.
    `face_value` (from the CAS) lets us compute the Indian-style
    'declared % of face value' figure. Returns {'available': False, ...} if the
    symbol is unlistable or yfinance has no data."""
    ticker = to_yf_ticker(gsymbol)
    if not ticker:
        return {"available": False, "reason": "No tradable symbol (unlisted / suspended)."}

    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception as e:
        return {"available": False, "reason": f"Lookup failed: {e}"}

    if not info or info.get("regularMarketPrice") is None and not info.get("longName"):
        return {"available": False, "reason": "No market data available for this symbol."}

    detail = {"available": True, "ticker": ticker, "fields": {}}
    for key, label in INFO_FIELDS.items():
        detail["fields"][label] = info.get(key)

    # Indian-style declared % of face value = annual dividend / face value * 100
    div_rate = info.get("dividendRate")
    if div_rate and face_value:
        try:
            detail["declared_pct_face"] = round(float(div_rate) / float(face_value) * 100, 1)
        except (ValueError, ZeroDivisionError, TypeError):
            detail["declared_pct_face"] = None
    else:
        detail["declared_pct_face"] = None

    detail["dividend_rate"] = div_rate

    # Recent dividend history (date -> amount)
    try:
        divs = t.dividends
        if divs is not None and len(divs):
            recent = divs.tail(6)
            detail["dividends"] = [
                {"date": d.strftime("%d-%b-%Y"), "amount": round(float(a), 2)}
                for d, a in recent.items()
            ]
        else:
            detail["dividends"] = []
    except Exception:
        detail["dividends"] = []

    return detail


def get_price_history(gsymbol, period="6mo"):
    """Return a DataFrame of price history (Date, Close) for charting, or None."""
    ticker = to_yf_ticker(gsymbol)
    if not ticker:
        return None
    try:
        hist = yf.Ticker(ticker).history(period=period)
        if hist is None or hist.empty:
            return None
        return hist[["Close"]].reset_index()
    except Exception:
        return None
