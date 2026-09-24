# CAS Portfolio Tracker

A Streamlit app that turns password-protected **NSDL Consolidated Account
Statement (CAS)** PDFs into a live equity portfolio dashboard.

## What it does

1. **Convert / Export** — Upload one or more password-protected CAS PDFs, extract
   all equity holdings, and download a CSV whose columns match a Google Sheets
   `raqdata` table (`ISIN | Symbol | Company | Face Value | Shares | Price |
   Value | Account`, plus `Statement Date` and `Status`). The `Symbol` column is
   emitted in Google Finance syntax (`NSE:RELIANCE`, `BSE:INDBNK`) so it works
   directly with `=GOOGLEFINANCE(...)`.
2. **Live Dashboard** — Values holdings using live NSE/BSE prices via `yfinance`
   and shows total value, day's P&L, unrealized return, intraday market breadth,
   top holdings, concentration and per-account allocation. Includes a live-feed
   auto-refresh and a bull/dip simulation control.

## Notes

- The CAS statement price is a month-end snapshot; live valuation comes from
  `yfinance`. "Unrealized return" is measured against the statement value
  (the CAS does not contain purchase cost basis).
- Holdings marked `NOT LISTED` / `TRADING SUSPENDED` have no tradable symbol and
  are valued at their statement value.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then upload your CAS PDF(s) and enter the PDF password in the sidebar.

## Privacy

This repo contains **only application code**. Statement PDFs, extracted CSVs,
spreadsheets and any credentials are excluded via `.gitignore` and must never be
committed.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI (Convert + Live Dashboard) |
| `cas_parser.py` | CAS PDF equity-holdings parser |
| `live_prices.py` | yfinance quote fetching (NSE/BSE) |
