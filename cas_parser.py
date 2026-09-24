"""
NSDL CAS equity-holdings parser (reusable module).

parse_cas(file_or_path, password) -> list[dict]
Each dict has keys:
    ISIN, Symbol, Company, Face Value, Shares, Price, Value,
    Account, Statement Date, Status

- Symbol is normalised to Google Finance format, e.g. NSE:RELIANCE / BSE:INDBNK.
- Unlistable holdings (NOT LISTED / TRADING SUSPENDED) get a blank Symbol and a
  populated Status so GOOGLEFINANCE() won't throw #N/A.
"""
import re
import pdfplumber

ISIN_RE = re.compile(r'^(IN[A-Z0-9]{9}\d)\s+(.*)$')

NUM_TAIL_RE = re.compile(
    r'^(.*?)\s+'
    r'(\d+\.\d{2})\s+'          # face value
    r'([\d,]+)\s+'              # no. of shares
    r'([\d,]+\.\d{2})\s+'       # market price
    r'([\d,]+\.\d{2})$'         # value
)

NOTE_TAIL_RE = re.compile(
    r'^(.*?)\s+'
    r'(\d+\.\d{2})\s+'
    r'([\d,]+)\s+'
    r'(See Note|N\.?A\.?|-)\s+'
    r'([\d,]+\.\d{2})$'
)

STMT_RE = re.compile(r'to\s+(\d{2}-[A-Za-z]{3}-\d{4})')
DPID_RE = re.compile(r'DP ID:?\s*([A-Z0-9]+).*?Client ID:?\s*(\d+)', re.IGNORECASE)
SUMMARY_ACCT_RE = re.compile(r'^NSDL Demat Account\s+\d+\s+[\d,]+\.\d{2}$')

STATUS_LABELS = ('NOT LISTED', 'TRADING SUSPENDED')

FIELDS = ['ISIN', 'Symbol', 'Company', 'Face Value', 'Shares', 'Price', 'Value',
          'Account', 'Statement Date', 'Status']


def _clean_num(s):
    return s.replace(',', '')


def normalize_symbol(raw):
    """'RELIANCE.NSE' -> 'NSE:RELIANCE'. Returns (google_symbol, status)."""
    raw = (raw or '').strip()
    if raw in STATUS_LABELS or raw == '':
        return '', (raw or 'UNKNOWN')
    m = re.match(r'^([A-Z0-9&\-]+)\.(NSE|BSE)$', raw)
    if m:
        return f"{m.group(2)}:{m.group(1)}", ''
    return raw, ''


def _build_account_map(pdf):
    amap = {}
    for page in pdf.pages:
        text = page.extract_text() or ""
        lines = [l.strip() for l in text.split('\n')]
        for j in range(len(lines) - 2):
            if SUMMARY_ACCT_RE.match(lines[j + 1]):
                dm = DPID_RE.search(lines[j + 2])
                bank = lines[j].strip()
                if dm and bank and 'ISINs' not in bank and 'Account Type' not in bank:
                    amap[dm.group(2)] = bank
    return amap


def parse_cas(file_or_path, password):
    """Parse a password-protected NSDL CAS PDF. Accepts a path or a file-like
    object (e.g. Streamlit's UploadedFile). Returns a list of row dicts."""
    rows = []
    with pdfplumber.open(file_or_path, password=password) as pdf:
        account_map = _build_account_map(pdf)
        stmt_date = ''
        current_account = ''
        in_equity = False
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines = [l.rstrip() for l in text.split('\n')]

            if not stmt_date:
                for l in lines:
                    m = STMT_RE.search(l)
                    if m and 'Statement for the period' in l:
                        stmt_date = m.group(1)
                        break

            i = 0
            while i < len(lines):
                line = lines[i].strip()

                dm = DPID_RE.search(line)
                if dm:
                    current_account = account_map.get(dm.group(2), current_account)
                    in_equity = False

                if 'Equities (E)' in line or line == 'Equity Shares':
                    in_equity = True
                if 'Preference Shares' in line or 'PORTFOLIO COMPOSITION' in line:
                    in_equity = False

                m = ISIN_RE.match(line)
                if m and in_equity:
                    isin = m.group(1)
                    rest = m.group(2)
                    nm = NUM_TAIL_RE.match(rest)
                    note_price = None
                    if not nm:
                        nnm = NOTE_TAIL_RE.match(rest)
                        if nnm:
                            nm = nnm
                            note_price = nnm.group(4).strip()
                    if nm:
                        name_part = nm.group(1).strip()
                        face = _clean_num(nm.group(2))
                        shares = _clean_num(nm.group(3))
                        price = '' if note_price is not None else _clean_num(nm.group(4))
                        value = _clean_num(nm.group(5))

                        symbol_raw = ""
                        name_cont = ""
                        if i + 1 < len(lines):
                            nxt = lines[i + 1].strip()
                            if not ISIN_RE.match(nxt) and nxt and not nxt.startswith('ISIN') \
                               and 'Sub Total' not in nxt and 'Total' not in nxt \
                               and 'PPaaggee' not in nxt and 'Consolidated' not in nxt:
                                if nxt.startswith('NOT LISTED'):
                                    symbol_raw = 'NOT LISTED'
                                    name_cont = nxt[len('NOT LISTED'):].strip()
                                elif nxt.startswith('TRADING SUSPENDED'):
                                    symbol_raw = 'TRADING SUSPENDED'
                                    name_cont = nxt[len('TRADING SUSPENDED'):].strip()
                                else:
                                    parts = nxt.split(None, 1)
                                    symbol_raw = parts[0]
                                    if len(parts) > 1:
                                        name_cont = parts[1].strip()
                                i += 1

                        if symbol_raw == 'NOT' and name_cont.startswith('LISTED'):
                            symbol_raw = 'NOT LISTED'
                            name_cont = name_cont[len('LISTED'):].strip()
                        elif symbol_raw == 'TRADING' and name_cont.startswith('SUSPENDED'):
                            symbol_raw = 'TRADING SUSPENDED'
                            name_cont = name_cont[len('SUSPENDED'):].strip()

                        full_name = (name_part + ' ' + name_cont).strip()
                        for lbl in ('SUSPENDED', 'LISTED'):
                            if full_name.endswith(' ' + lbl):
                                full_name = full_name[: -(len(lbl) + 1)].strip()
                        if symbol_raw == 'NOT':
                            symbol_raw = 'NOT LISTED'
                        elif symbol_raw == 'TRADING':
                            symbol_raw = 'TRADING SUSPENDED'

                        gsymbol, status = normalize_symbol(symbol_raw)

                        rows.append({
                            'ISIN': isin,
                            'Symbol': gsymbol,
                            'Company': full_name,
                            'Face Value': face,
                            'Shares': shares,
                            'Price': price,
                            'Value': value,
                            'Account': current_account,
                            'Statement Date': stmt_date,
                            'Status': status,
                        })
                i += 1
    return rows
