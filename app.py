"""
NSDL CAS Portfolio App
----------------------
1. Convert: upload password-protected CAS PDF(s) -> parse equity holdings ->
   preview + download CSV (paste into your Google Sheet `raqdata` tab).
2. Live Dashboard: mirrors the Google Finance sheet dashboard -
   total value, day's P&L, unrealized return, intraday market breadth,
   live feed auto-refresh, bull/dip simulation, top holdings & concentration.
"""
import io
import datetime as dt
import pandas as pd
import streamlit as st
import plotly.express as px
from streamlit_autorefresh import st_autorefresh

from cas_parser import parse_cas, FIELDS
from live_prices import fetch_quotes
from company_detail import get_company_detail, get_price_history

st.set_page_config(page_title="CAS Portfolio Tracker", page_icon="📈", layout="wide")


def rupees(x, lakhs=False):
    try:
        if lakhs:
            return f"₹{x/1e5:,.2f} L"
        return f"₹{x:,.2f}"
    except Exception:
        return str(x)


def rupees_short(x):
    """Compact Indian-format rupees for narrow screens / metric cards.
    >= 1 Cr -> '₹1.51 Cr', >= 1 L -> '₹26.17 L', else '₹5,645'."""
    try:
        v = float(x)
    except (ValueError, TypeError):
        return "—"
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1e7:
        return f"{sign}₹{a/1e7:,.2f} Cr"
    if a >= 1e5:
        return f"{sign}₹{a/1e5:,.2f} L"
    if a >= 1e3:
        return f"{sign}₹{a:,.0f}"
    return f"{sign}₹{a:,.2f}"


@st.cache_data(show_spinner=False)
def parse_files(file_bytes_list, password):
    all_rows, errors = [], []
    for name, raw in file_bytes_list:
        try:
            all_rows.extend(parse_cas(io.BytesIO(raw), password))
        except Exception as e:
            errors.append((name, str(e)))
    df = pd.DataFrame(all_rows, columns=FIELDS)
    for c in ["Face Value", "Shares", "Value"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["Price"] = pd.to_numeric(df["Price"], errors="coerce")
    return df, errors


@st.cache_data(show_spinner=True, ttl=60)
def get_quotes(symbols, _bucket):
    """_bucket busts the cache on the auto-refresh tick."""
    return fetch_quotes(symbols)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_company_detail(gsymbol, face_value):
    return get_company_detail(gsymbol, face_value)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_price_history(gsymbol, period):
    return get_price_history(gsymbol, period)


st.title("📈 NSDL CAS Portfolio Tracker")
st.caption("Password-protected CAS PDFs in, live NSE/BSE valuation out.")

with st.sidebar:
    st.header("Upload")
    uploaded = st.file_uploader("CAS PDF file(s)", type=["pdf", "PDF"],
                                accept_multiple_files=True)
    password = st.text_input("PDF password", type="password")
    go = st.button("Parse", type="primary", use_container_width=True)

if "df" not in st.session_state:
    st.session_state.df = None

if go:
    if not uploaded:
        st.warning("Add at least one PDF.")
    elif not password:
        st.warning("Enter the PDF password.")
    else:
        payload = [(f.name, f.getvalue()) for f in uploaded]
        df, errors = parse_files(payload, password)
        for name, err in errors:
            st.error(f"{name}: {err}")
        if df is not None and not df.empty:
            st.session_state.df = df
            st.success(f"Parsed {len(df)} holdings across "
                       f"{df['Statement Date'].nunique()} statement(s).")
        else:
            st.error("No equity holdings found. Check the password and file.")

df = st.session_state.df
if df is None or df.empty:
    st.info("⬅️ Upload one or more CAS PDFs and enter the password to begin.")
    st.stop()

statements = sorted(df["Statement Date"].dropna().unique(),
                    key=lambda d: pd.to_datetime(d, format="%d-%b-%Y", errors="coerce"))

tab_dash, tab_company, tab_convert = st.tabs(
    ["📊 Live Dashboard", "🔍 Company Deep Dive", "🔄 Convert / Export"])

# ---------------------------------------------------------------- Dashboard tab
with tab_dash:
    top_ctrl = st.columns([2, 1, 1, 1, 1])
    with top_ctrl[0]:
        sel = st.selectbox("Statement (baseline)", statements,
                           index=len(statements) - 1)
    with top_ctrl[1]:
        live_feed = st.toggle("Live feed", value=True)
    with top_ctrl[2]:
        cadence = st.selectbox("Refresh", ["3s", "10s", "30s", "60s"], index=2)
    with top_ctrl[3]:
        sim = st.radio("Simulate", ["Off", "Bull +", "Dip -"], horizontal=True)
    with top_ctrl[4]:
        sim_pct = st.slider("Sim %", 0, 10, 3)

    if live_feed:
        secs = int(cadence.rstrip("s"))
        tick = st_autorefresh(interval=secs * 1000, key="feedtick")
    else:
        tick = 0

    view = df[df["Statement Date"] == sel].copy()
    symbols = view.loc[view["Symbol"] != "", "Symbol"].unique().tolist()

    with st.spinner("Fetching live NSE/BSE prices..."):
        quotes = get_quotes(tuple(symbols), tick if live_feed else "static")

    view["Live Price"] = view["Symbol"].map(lambda s: quotes.get(s, {}).get("price"))
    view["Prev Close"] = view["Symbol"].map(lambda s: quotes.get(s, {}).get("prev_close"))

    # Simulation: nudge live prices for what-if viewing
    factor = 1.0
    if sim == "Bull +":
        factor = 1 + sim_pct / 100
    elif sim == "Dip -":
        factor = 1 - sim_pct / 100
    if factor != 1.0:
        view["Live Price"] = view["Live Price"] * factor

    view["Live Value"] = view["Live Price"] * view["Shares"]
    view["Live Value"] = view["Live Value"].fillna(view["Value"])
    view["Statement Value"] = view["Value"]
    view["Prev Value"] = (view["Prev Close"] * view["Shares"]).fillna(view["Value"])
    view["Day P&L"] = view["Live Value"] - view["Prev Value"]
    view["Total P&L"] = view["Live Value"] - view["Statement Value"]

    total_live = view["Live Value"].sum()
    total_stmt = view["Statement Value"].sum()
    total_prev = view["Prev Value"].sum()
    day_pnl = total_live - total_prev
    total_pnl = total_live - total_stmt
    day_pct = (day_pnl / total_prev * 100) if total_prev else 0
    roi_pct = (total_pnl / total_stmt * 100) if total_stmt else 0

    # Market breadth (intraday day move per stock)
    priced = view[view["Live Price"].notna() & view["Prev Close"].notna()]
    advancing = int((priced["Live Price"] > priced["Prev Close"]).sum())
    declining = int((priced["Live Price"] < priced["Prev Close"]).sum())

    # ---- Header stat cards
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Portfolio Value", rupees_short(total_live),
              help=f"Invested (statement): {rupees(total_stmt)} · {len(view)} assets")
    m2.metric("Day's Profit / Loss", rupees_short(day_pnl), f"{day_pct:+.2f}% today")
    m3.metric("Total Unrealized Return", rupees_short(total_pnl), f"{roi_pct:+.2f}% ROI")
    with m4:
        st.markdown("**Intraday Market Breadth**")
        st.markdown(f"🟢 **{advancing} Advancing**  |  🔴 **{declining} Declining**")
        st.caption(f"Last tick: {dt.datetime.now().strftime('%H:%M:%S')}")

    if sim != "Off":
        st.info(f"Simulation active: prices scaled {factor:+.0%} — for what-if viewing only.")

    st.divider()

    # ---- Analytics section with three views (mirrors screenshot)
    st.subheader("Portfolio Analytics & Live Engine")
    v1, v2, v3 = st.tabs(["Top Holdings Weight", "Daily Movement", "Symbol Guide"])

    view["Weight %"] = view["Live Value"] / total_live * 100

    with v1:
        left, right = st.columns([3, 2])
        with left:
            top7 = view.sort_values("Live Value", ascending=False).head(7)
            fig = px.bar(top7, x="Live Value", y="Company", orientation="h",
                         text=top7["Weight %"].map(lambda w: f"{w:.1f}%"))
            fig.update_layout(yaxis={"categoryorder": "total ascending"},
                              height=380, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        with right:
            st.markdown("**Concentration Snapshot**")
            snap = view.sort_values("Live Value", ascending=False).head(10).copy()
            snap["Value"] = snap["Live Value"].map(lambda v: rupees(v, lakhs=True))
            snap["Weight"] = snap["Weight %"].map(lambda w: f"{w:.1f}%")
            snap.insert(0, "#", range(1, len(snap) + 1))
            st.dataframe(snap[["#", "Company", "Value", "Weight"]],
                         use_container_width=True, hide_index=True)

    with v2:
        mv = priced.copy()
        mv["Day Move %"] = (mv["Live Price"] - mv["Prev Close"]) / mv["Prev Close"] * 100
        mv = mv.sort_values("Day Move %")
        fig2 = px.bar(mv, x="Day Move %", y="Company", orientation="h",
                      color="Day Move %", color_continuous_scale=["#d62728", "#bbb", "#2ca02c"])
        fig2.update_layout(height=max(400, len(mv) * 14),
                           margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig2, use_container_width=True)

    with v3:
        st.markdown(
            "This app values holdings with **yfinance** (NSE `.NS`, BSE `.BO`).\n\n"
            "The exported **Symbol** column uses Google Finance syntax so it works "
            "directly in your sheet:\n"
            "- `=GOOGLEFINANCE(\"NSE:RELIANCE\", \"price\")`\n"
            "- `=GOOGLEFINANCE(\"BSE:INDBNK\", \"price\")`\n\n"
            "Holdings marked **NOT LISTED / TRADING SUSPENDED** have no symbol and "
            "are valued at their statement value."
        )

    st.divider()
    st.subheader("Holdings detail (live)")
    show = view[["Company", "Symbol", "Shares", "Live Price", "Prev Close",
                 "Day P&L", "Statement Value", "Live Value", "Total P&L",
                 "Weight %", "Account"]].sort_values("Live Value", ascending=False)
    st.dataframe(
        show.style.format({
            "Shares": "{:,.0f}", "Live Price": "₹{:,.2f}", "Prev Close": "₹{:,.2f}",
            "Day P&L": "₹{:,.2f}", "Statement Value": "₹{:,.2f}",
            "Live Value": "₹{:,.2f}", "Total P&L": "₹{:,.2f}", "Weight %": "{:.2f}%",
        }),
        use_container_width=True, hide_index=True,
    )

# -------------------------------------------------------------- Company deep dive
with tab_company:
    # Use the latest statement's holdings as the universe of selectable companies
    latest_stmt = statements[-1]
    universe = df[df["Statement Date"] == latest_stmt].copy()
    universe = universe.sort_values("Company")

    names = universe["Company"].tolist()
    picked = st.selectbox("Select a company", names, key="company_pick")
    row = universe[universe["Company"] == picked].iloc[0]

    gsymbol = row["Symbol"]
    face_value = row["Face Value"]
    shares = float(row["Shares"]) if pd.notna(row["Shares"]) else 0

    st.markdown(f"### {picked}")
    st.caption(f"{gsymbol or 'Unlisted / suspended'} · {row['Account']}")

    detail = cached_company_detail(gsymbol, float(face_value) if pd.notna(face_value) else None)

    if not detail.get("available"):
        st.info(f"Market data not available: {detail.get('reason', 'unknown')}")
        st.write(f"**Your position:** {shares:,.0f} shares · "
                 f"statement value {rupees(row['Value'])}")
    else:
        # Live quote for this one company
        q = fetch_quotes([gsymbol]).get(gsymbol, {})
        live_price = q.get("price")
        live_value = live_price * shares if live_price else row["Value"]

        # ---- Your position
        st.markdown("#### Your position")
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Shares", f"{shares:,.0f}")
        p2.metric("Live Price", rupees(live_price) if live_price else "—")
        p3.metric("Live Value", rupees_short(live_value))
        p4.metric("vs Statement", rupees_short(live_value - row["Value"]))

        # ---- Dividends
        st.markdown("#### Dividends")
        d1, d2, d3, d4 = st.columns(4)
        dy = detail["fields"].get("Dividend Yield %")
        dr = detail.get("dividend_rate")
        declared = detail.get("declared_pct_face")
        annual_income = (dr * shares) if dr else None
        d1.metric("Dividend Yield", f"{dy:.2f}%" if dy else "—")
        d2.metric("Annual ₹/share", rupees(dr) if dr else "—")
        d3.metric("Declared % of Face", f"{declared:,.0f}%" if declared else "—",
                  help="Indian-style: annual dividend ÷ face value × 100")
        d4.metric("Est. annual income", rupees_short(annual_income) if annual_income else "—",
                  help="Annual ₹/share × your shares")

        divs = detail.get("dividends") or []
        if divs:
            st.caption("Recent dividends (ex-date · amount per share)")
            dd = pd.DataFrame(divs)
            dd["amount"] = dd["amount"].map(lambda a: f"₹{a:,.2f}")
            st.dataframe(dd.rename(columns={"date": "Ex-Date", "amount": "Amount/Share"}),
                         use_container_width=True, hide_index=True)

        # ---- Company snapshot
        st.markdown("#### Company snapshot")
        f = detail["fields"]
        s1, s2, s3 = st.columns(3)
        mcap = f.get("Market Cap")
        s1.metric("Market Cap", f"₹{mcap/1e7:,.0f} Cr" if mcap else "—")
        s1.metric("Sector", f.get("Sector") or "—")
        s2.metric("P/E (TTM)", f"{f['P/E (TTM)']:.1f}" if f.get("P/E (TTM)") else "—")
        s2.metric("Beta", f"{f['Beta']:.2f}" if f.get("Beta") is not None else "—")
        s3.metric("52W High", rupees(f["52W High"]) if f.get("52W High") else "—")
        s3.metric("52W Low", rupees(f["52W Low"]) if f.get("52W Low") else "—")

        # ---- Price history
        st.markdown("#### Price history")
        rng = st.radio("Range", ["1mo", "6mo", "1y"], horizontal=True, index=1,
                       key="hist_range")
        hist = cached_price_history(gsymbol, rng)
        if hist is not None and not hist.empty:
            xcol = hist.columns[0]
            fig = px.line(hist, x=xcol, y="Close")
            fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10),
                              yaxis_title="Close (₹)", xaxis_title="")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No price history available.")


# ------------------------------------------------------------------ Convert tab
with tab_convert:
    st.subheader("Extracted holdings")
    st.caption("Columns match your `raqdata` table. Download and paste into the "
               "Google Sheet — GOOGLEFINANCE() will price the Symbol column.")
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.download_button("⬇️ Download CSV",
                       data=df.to_csv(index=False).encode("utf-8-sig"),
                       file_name="cas_holdings.csv", mime="text/csv")
    unlisted = df[df["Symbol"] == ""]
    if not unlisted.empty:
        st.warning(f"{len(unlisted)} holding(s) have no tradable symbol and "
                   f"are valued at statement value.")
        st.dataframe(unlisted[["Company", "Status", "Value", "Statement Date"]],
                     use_container_width=True, hide_index=True)
