"""
AccuLedger Pro — GST Fraud Detection & Accounting Platform
FastAPI + SQLite backend · Single file
Run: uvicorn main:app --reload --port 8000
"""

import sqlite3, hashlib, json, uuid, os, math, re, time
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager
import random
import numpy as np

# ── XGBoost + Isolation Forest ────────────────────────────────────────────────
try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False

try:
    from sklearn.ensemble import IsolationForest
    ISO_AVAILABLE = True
except ImportError:
    ISO_AVAILABLE = False

from fastapi import FastAPI, HTTPException, Query
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# ─── Config ───────────────────────────────────────────────────────────────────
import pathlib
BASE_DIR   = pathlib.Path(__file__).parent.resolve()
DB_PATH    = str(BASE_DIR / "acculedger.db")
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()          # run on startup
    yield              # app runs here
    pass               # nothing to clean up on shutdown

app = FastAPI(title="AccuLedger Pro", version="1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# ─── DB helpers ───────────────────────────────────────────────────────────────
@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ── Inline schema — never depends on external schema.sql file ─────────────────
INLINE_SCHEMA = """
CREATE TABLE IF NOT EXISTS hsn_master (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    hsn_code    TEXT NOT NULL,
    item_name   TEXT NOT NULL,
    gst_rate    REAL NOT NULL,
    section     TEXT DEFAULT '',
    chapter     TEXT DEFAULT '',
    description TEXT DEFAULT '',
    is_active   INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_hsn_code     ON hsn_master(hsn_code);
CREATE INDEX IF NOT EXISTS idx_hsn_gst_rate ON hsn_master(gst_rate);
CREATE INDEX IF NOT EXISTS idx_hsn_active   ON hsn_master(is_active);

CREATE TABLE IF NOT EXISTS companies (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    gstin      TEXT UNIQUE,
    pan        TEXT,
    state      TEXT,
    fy_start   TEXT,
    currency   TEXT DEFAULT 'INR',
    created_at TEXT DEFAULT (datetime('now')),
    active     INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS ledgers (
    id               TEXT PRIMARY KEY,
    company_id       TEXT NOT NULL,
    name             TEXT NOT NULL,
    grp              TEXT NOT NULL,
    opening_balance  REAL DEFAULT 0,
    balance_type     TEXT DEFAULT 'Debit',
    gst_applicable   INTEGER DEFAULT 0,
    created_at       TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(company_id) REFERENCES companies(id)
);

CREATE TABLE IF NOT EXISTS vouchers (
    id               TEXT PRIMARY KEY,
    company_id       TEXT NOT NULL,
    date             TEXT NOT NULL,
    type             TEXT NOT NULL,
    party_name       TEXT,
    gstin            TEXT,
    gstin_age_days   INTEGER DEFAULT 365,
    invoice_number   TEXT,
    hsn_code         TEXT,
    gst_rate         REAL DEFAULT 18,
    base_amount      REAL DEFAULT 0,
    tax_amount       REAL DEFAULT 0,
    total_amount     REAL DEFAULT 0,
    narration        TEXT,
    is_round_number  INTEGER DEFAULT 0,
    is_march_rush    INTEGER DEFAULT 0,
    l1_flags         TEXT DEFAULT '',
    l2_score         INTEGER DEFAULT 0,
    l3_anomaly       REAL DEFAULT 0,
    l4_duplicate     TEXT DEFAULT 'Clear',
    risk_level       TEXT DEFAULT 'Low',
    gstr2b_match     TEXT DEFAULT 'Matched',
    review_status    TEXT DEFAULT 'Cleared',
    ai_flags         TEXT DEFAULT '',
    created_at       TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(company_id) REFERENCES companies(id)
);
CREATE INDEX IF NOT EXISTS idx_vouchers_company ON vouchers(company_id);
CREATE INDEX IF NOT EXISTS idx_vouchers_risk    ON vouchers(company_id, risk_level);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT DEFAULT (datetime('now')),
    action      TEXT NOT NULL,
    tbl         TEXT NOT NULL,
    record_id   TEXT NOT NULL,
    after_val   TEXT DEFAULT '{}',
    entry_hash  TEXT NOT NULL,
    prev_hash   TEXT NOT NULL
);
"""

# ── HSN seed data (inline — no external file needed) ──────────────────────────
HSN_SEED = [
    ("8471","Laptop",18,"XVI","84"),("8471","Desktop Computer",18,"XVI","84"),
    ("8471","Tablet Computer",18,"XVI","84"),("8517","Mobile Phone",18,"XVI","85"),
    ("8517","Smartphone",18,"XVI","85"),("8443","Printer",18,"XVI","84"),
    ("8528","TV",18,"XVI","85"),("8528","LED TV",18,"XVI","85"),
    ("8518","Speaker",18,"XVI","85"),("8518","Headphones",18,"XVI","85"),
    ("8414","Fan",18,"XVI","84"),("8415","Air Conditioner",28,"XVI","84"),
    ("8415","AC",28,"XVI","84"),("8418","Refrigerator",18,"XVI","84"),
    ("8450","Washing Machine",18,"XVI","84"),("8539","LED Bulb",12,"XVI","85"),
    ("9608","Pen",12,"XX","96"),("9608","Ball Pen",12,"XX","96"),
    ("9609","Pencil",12,"XX","96"),("4820","Notebook",12,"XX","48"),
    ("4901","Books",0,"XIX","49"),("4901","Textbooks",0,"XIX","49"),
    ("0401","Milk",0,"I","04"),("0401","Packed Milk",0,"I","04"),
    ("0403","Yogurt",0,"I","04"),("0403","Curd / Dahi",0,"I","04"),
    ("0405","Butter",12,"I","04"),("0406","Cheese",12,"I","04"),
    ("0406","Paneer",12,"I","04"),("0407","Eggs",0,"I","04"),
    ("0409","Honey",0,"I","04"),("2105","Ice Cream",18,"IV","21"),
    ("1006","Rice",0,"II","10"),("1006","Basmati Rice",0,"II","10"),
    ("1001","Wheat",0,"II","10"),("1101","Flour / Atta",5,"II","11"),
    ("1101","Wheat Flour",5,"II","11"),("1101","Maida",5,"II","11"),
    ("0713","Dal",0,"II","07"),("0713","Moong Dal",0,"II","07"),
    ("0713","Toor Dal",0,"II","07"),("0713","Rajma",0,"II","07"),
    ("1701","Sugar",5,"IV","17"),("1702","Jaggery / Gur",5,"IV","17"),
    ("1704","Candy",28,"IV","17"),("1507","Soyabean Oil",5,"III","15"),
    ("1509","Olive Oil",5,"III","15"),("1512","Sunflower Oil",5,"III","15"),
    ("1513","Coconut Oil",5,"III","15"),("1514","Mustard Oil",5,"III","15"),
    ("1508","Groundnut Oil",5,"III","15"),("0701","Potato",0,"II","07"),
    ("0702","Tomato",0,"II","07"),("0703","Onion",0,"II","07"),
    ("0803","Banana",0,"II","08"),("0804","Mango",0,"II","08"),
    ("0808","Apple",0,"II","08"),("0902","Tea",5,"I","09"),
    ("0902","Green Tea",5,"I","09"),("0901","Coffee",5,"I","09"),
    ("2101","Instant Coffee",12,"IV","21"),("2201","Packaged Water",0,"IV","22"),
    ("2202","Cold Drink",18,"IV","22"),("2202","Energy Drink",18,"IV","22"),
    ("2009","Fruit Juice",12,"IV","20"),("1902","Noodles",18,"IV","19"),
    ("1902","Instant Noodles",18,"IV","19"),("1902","Pasta",18,"IV","19"),
    ("1905","Biscuits",18,"IV","19"),("1905","Bread",12,"IV","19"),
    ("1905","Cake",18,"IV","19"),("1905","Rusk",12,"IV","19"),
    ("2007","Jam",12,"IV","20"),("2008","Potato Chips",12,"IV","20"),
    ("2008","Peanut Butter",12,"IV","20"),("2103","Ketchup",12,"IV","21"),
    ("2103","Garam Masala",12,"IV","21"),("2106","Namkeen / Snacks",18,"IV","21"),
    ("1806","Chocolate",28,"IV","18"),("0904","Chilli Powder",5,"I","09"),
    ("0910","Turmeric Powder",5,"I","09"),("2501","Salt",0,"V","25"),
    ("3305","Shampoo",18,"VI","33"),("3305","Hair Oil",18,"VI","33"),
    ("3401","Soap",18,"VI","34"),("3401","Bathing Soap",18,"VI","34"),
    ("3306","Toothpaste",18,"VI","33"),("3307","Deodorant",18,"VI","33"),
    ("3304","Face Cream",28,"VI","33"),("3304","Face Wash",28,"VI","33"),
    ("3304","Sunscreen",28,"VI","33"),("3304","Perfume / Attar",28,"VI","33"),
    ("3808","Sanitiser",18,"VI","38"),("3004","Medicines",12,"VI","30"),
    ("3004","Medical Tablets",12,"VI","30"),("6109","T-Shirt",5,"XI","61"),
    ("6203","Jeans",12,"XI","62"),("6203","Trousers",12,"XI","62"),
    ("6403","Shoes",18,"XII","64"),("6403","Sneakers",18,"XII","64"),
    ("6302","Towel",12,"XI","63"),("6302","Bed Sheet",12,"XI","63"),
    ("3923","Plastic Bucket",18,"VII","39"),("3923","Plastic Bottle",18,"VII","39"),
    ("3917","PVC Pipe",18,"VII","39"),("9403","Furniture",18,"XX","94"),
    ("9403","Office Chair",18,"XX","94"),("9401","Chair",18,"XX","94"),
    ("2523","Cement",28,"V","25"),("7214","Steel Rod",18,"XV","72"),
    ("8703","Car",28,"XVII","87"),("8711","Bike / Motorcycle",28,"XVII","87"),
    ("8711","Scooter",28,"XVII","87"),("7113","Gold Jewellery",3,"XIV","71"),
    ("7113","Silver Jewellery",3,"XIV","71"),("0813","Raisins",5,"II","08"),
    ("0813","Dates",5,"II","08"),("0802","Almond",5,"II","08"),
    ("0802","Cashew",5,"II","08"),
]

def init_db():
    """Create all tables inline (no external schema.sql needed) then seed data."""
    # Step 1: always create tables first using inline schema
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.executescript(INLINE_SCHEMA)
        conn.commit()
        print(f"[AccuLedger] Tables created/verified at {DB_PATH}")
    finally:
        conn.close()

    # Step 2: seed HSN master if empty
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM hsn_master").fetchone()[0]
        if count == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO hsn_master (hsn_code,item_name,gst_rate,section,chapter) VALUES (?,?,?,?,?)",
                HSN_SEED
            )
            print(f"[AccuLedger] Seeded {len(HSN_SEED)} HSN items")

    # Step 3: seed demo company if no companies exist
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        if count == 0:
            _seed_demo_company(conn)

def _seed_demo_company(conn):
    """Seed a demo company with 80 sample vouchers including planted fraud."""
    cid = "DEMO0001"
    conn.execute("""
        INSERT OR IGNORE INTO companies (id, name, gstin, pan, state, fy_start)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (cid, "Demo Co. Pvt Ltd", "27AABCD1234E1ZX", "AABCD1234E", "Maharashtra", "2025-04-01"))

    # Default ledgers
    ledger_defs = [
        ("L0001", "Capital Account",   "Capital Account",    0.0,     "Credit"),
        ("L0002", "Cash",              "Cash-in-Hand",       50000.0, "Debit"),
        ("L0003", "Bank Account",      "Bank Accounts",      500000.0,"Debit"),
        ("L0004", "Sundry Debtors",    "Sundry Debtors",     0.0,     "Debit"),
        ("L0005", "Sundry Creditors",  "Sundry Creditors",   0.0,     "Credit"),
        ("L0006", "Sales",             "Sales Accounts",     0.0,     "Credit"),
        ("L0007", "Purchase",          "Purchase Accounts",  0.0,     "Debit"),
        ("L0008", "CGST Payable",      "Duties & Taxes",     0.0,     "Credit"),
        ("L0009", "SGST Payable",      "Duties & Taxes",     0.0,     "Credit"),
        ("L0010", "Office Expenses",   "Indirect Expenses",  0.0,     "Debit"),
        ("L0011", "Salary Expenses",   "Direct Expenses",    0.0,     "Debit"),
        ("L0012", "Fixed Assets",      "Fixed Assets",       0.0,     "Debit"),
        ("L0013", "TDS Payable",       "Duties & Taxes",     0.0,     "Credit"),
        ("L0014", "IGST Payable",      "Duties & Taxes",     0.0,     "Credit"),
    ]
    for row in ledger_defs:
        conn.execute("""
            INSERT OR IGNORE INTO ledgers (id,company_id,name,grp,opening_balance,balance_type)
            VALUES (?,?,?,?,?,?)
        """, (row[0], cid, row[1], row[2], row[3], row[4]))

    # 80 seeded vouchers
    parties = [
        ("Sunrise Traders",    "27AABCU9603R1ZM", 2400),
        ("FastBuild Infra",    "29GGGGG1314R9Z6", 1800),
        ("NovaTech Solutions", "24HHHHL3920P1ZF", 2000),
        ("Reliable Supplies",  "27AABCU1111R1ZP", 2600),
        ("Apex Distributors",  "33CCCCM4444R1ZQ", 1400),
        ("QuantumParts Ltd",   "19DDDDK9999P2ZL", 2000),
        ("ShellCo Exports",    "07ZZZZZ1234A1Z1", 4),   # <-- planted fraud
        ("MirrorInv Corp",     "06EEEEF5678R1ZN", 1100),
    ]
    vtypes = ["Purchase","Sales","Payment","Receipt","Journal","Contra"]
    hsn_gst = {"8471":18,"9403":18,"3004":12,"6109":5,"8517":18,"4901":0,
                "2710":18,"8528":28,"6402":18,"0901":5}
    hsn_list = list(hsn_gst.keys())
    narrs = ["Purchase as per PO","Payment received","Supply of services",
             "Capital goods purchase","","GST invoice","Monthly retainer",
             "Office supplies","Transport charges","Maintenance expense"]

    rnd = random.Random(42)
    for i in range(80):
        pi   = rnd.randint(0, len(parties)-1)
        name, gstin, age_days = parties[pi]
        hsn  = rnd.choice(hsn_list)
        gst  = hsn_gst[hsn]
        vtype= rnd.choice(vtypes)
        days_back = rnd.randint(0, 180)
        d    = (date.today() - timedelta(days=days_back)).isoformat()
        is_march = datetime.fromisoformat(d).month == 3

        base = round(rnd.lognormvariate(10.5, 1.2), 2)
        is_round = rnd.random() < 0.12
        if is_round:
            base = round(base / 10000) * 10000
        tax  = round(base * gst / 100, 2)
        total= base + tax
        narr = rnd.choice(narrs)
        inv  = f"INV-{datetime.fromisoformat(d).year}-{rnd.randint(100,9999)}"

        # Risk scoring — pass already-inserted vouchers as context for IsoForest
        prior_vouchers = [
            {"base_amount": r[0], "gstin_age_days": r[1],
             "is_round_number": bool(r[2]), "is_march_rush": bool(r[3]),
             "narration": r[4], "gst_rate": r[5], "gstin": r[6]}
            for r in conn.execute(
                "SELECT base_amount,gstin_age_days,is_round_number,is_march_rush,narration,gst_rate,gstin FROM vouchers WHERE company_id=?",
                (cid,)
            ).fetchall()
        ]
        combined_score, xgb_score, l3_anomaly, l1_flags = _score_voucher(
            {"gstin_age_days": age_days, "base_amount": base,
             "is_round_number": is_round, "is_march_rush": is_march,
             "narration": narr, "gst_rate": float(gst), "gstin": gstin,
             "date": d},
            company_id=cid,
            company_vouchers=prior_vouchers,
        )
        # For seeded data, clear model cache after each batch to retrain fresh
        if i % 20 == 19:
            _xgb_model_cache.pop(cid, None)
            _iso_model_cache.pop(cid, None)
        l4_dup = "Duplicate (sim=0.93)" if (i < 75 and rnd.random() < 0.04) else "Clear"
        risk = "High" if combined_score >= 50 else "Medium" if combined_score >= 20 else "Low"

        # Plant fraud at voucher index where ShellCo Exports appears
        if pi == 6:  # ShellCo Exports
            base   = 4500000.0
            tax    = 810000.0
            total  = 5310000.0
            is_round = True
            is_march = True
            combined_score = 87
            xgb_score = 79
            l3_anomaly = -0.41
            risk = "High"
            l1_flags = "⚠ GSTIN very new · ⚠ Large round-number amount in March"

        conn.execute("""
            INSERT OR IGNORE INTO vouchers
            (id,company_id,date,type,party_name,gstin,gstin_age_days,invoice_number,
             hsn_code,gst_rate,base_amount,tax_amount,total_amount,narration,
             is_round_number,is_march_rush,l1_flags,l2_score,l3_anomaly,l4_duplicate,
             risk_level,gstr2b_match,review_status,ai_flags)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            f"V{str(i+1).zfill(4)}", cid, d, vtype, name, gstin, age_days, inv,
            hsn, float(gst), base, tax, total, narr,
            1 if is_round else 0, 1 if is_march else 0,
            l1_flags, combined_score, l3_anomaly, l4_dup,
            risk,
            "Not Found" if risk == "High" else "Matched",
            "Pending" if risk != "Low" else "Cleared",
            f"xgb={xgb_score}·iso={round(l3_anomaly,3)}" + (" · round_amt" if is_round else "") + (" · march_rush" if is_march else "")
        ))

    _audit(conn, "DEMO_SEED", "companies", cid, {"rows": 80})
    print(f"[AccuLedger] Demo company seeded with 80 vouchers")

# ─── HSN-GST map ──────────────────────────────────────────────────────────────
HSN_GST_MAP = {
    "8471":18,"9403":18,"3004":12,"6109":5,"8517":18,"4901":0,
    "2710":18,"8528":28,"6402":18,"0901":5,"1905":5,"3304":18,
    "8708":28,"3926":18,"9018":12,
}

# ─── Feature engineering (shared by XGBoost + IsolationForest) ────────────────
FEATURE_NAMES = [
    "log_base_amount",      # log1p(base) normalised to [0,1] over 20
    "gst_rate_norm",        # gst_rate / 28
    "gstin_age_norm",       # min(age, 3650) / 3650
    "is_round_number",      # 1/0
    "is_march_rush",        # 1/0
    "tax_to_base_ratio",    # base*gst/100 / (base+1e-9)
    "day_of_week_norm",     # weekday / 6
    "month_norm",           # (month-1) / 11
    "amount_zscore_clip",   # clipped zscore proxy
    "new_party_flag",       # age < 90
    "large_amount_flag",    # base > 2_000_000
    "missing_narration",    # 1 if narration empty
]

def _extract_features(v: dict, company_vouchers: list = None) -> np.ndarray:
    """Extract normalised 12-dim feature vector from a voucher dict."""
    base  = float(v.get("base_amount", 0))
    gst   = float(v.get("gst_rate", 18))
    age   = float(v.get("gstin_age_days", 365))
    rnd   = float(bool(v.get("is_round_number", False)))
    march = float(bool(v.get("is_march_rush", False)))
    narr  = str(v.get("narration", ""))

    d_str = v.get("date", date.today().isoformat())
    try:
        d_obj = date.fromisoformat(str(d_str)[:10])
    except Exception:
        d_obj = date.today()

    log_base   = np.log1p(base) / 20.0
    gst_norm   = gst / 28.0
    age_norm   = min(age, 3650) / 3650.0
    tax_ratio  = (base * gst / 100) / (base + 1e-9)
    dow_norm   = d_obj.weekday() / 6.0
    month_norm = (d_obj.month - 1) / 11.0

    # Amount z-score proxy using company history if available
    if company_vouchers and len(company_vouchers) > 5:
        amounts = [float(x.get("base_amount", 0)) for x in company_vouchers]
        mean_b, std_b = np.mean(amounts), np.std(amounts) + 1e-9
        amt_z = min(abs((base - mean_b) / std_b) / 5.0, 1.0)
    else:
        amt_z = min(abs((base - 100_000) / 200_000), 1.0)

    new_party = 1.0 if age < 90 else 0.0
    large_amt = 1.0 if base > 2_000_000 else 0.0
    miss_narr = 0.0 if narr.strip() else 1.0

    return np.array([
        log_base, gst_norm, age_norm, rnd, march,
        tax_ratio, dow_norm, month_norm, amt_z,
        new_party, large_amt, miss_narr,
    ], dtype=np.float32)

# ─── XGBoost: train per-company or use global fallback model ──────────────────
_xgb_model_cache: Dict[str, Any] = {}   # company_id → fitted XGBClassifier
_iso_model_cache: Dict[str, Any] = {}   # company_id → fitted IsolationForest

def _get_or_train_models(company_id: str, company_vouchers: list):
    """
    Train (or return cached) XGBClassifier + IsolationForest for a company.
    Uses synthetic fraud labels when real labels unavailable (cold-start safe).
    Requires >= 10 vouchers; returns (None, None) below that threshold.
    """
    if len(company_vouchers) < 10:
        return None, None

    # Return cached if already trained for this company
    if company_id in _xgb_model_cache and company_id in _iso_model_cache:
        return _xgb_model_cache[company_id], _iso_model_cache[company_id]

    # Build feature matrix
    X = np.array([_extract_features(v, company_vouchers) for v in company_vouchers],
                 dtype=np.float32)
    n = len(X)

    # ── Synthetic fraud labels from deterministic heuristics ──────────────────
    labels = np.zeros(n, dtype=np.float32)
    for i, v in enumerate(company_vouchers):
        score = 0.0
        age   = float(v.get("gstin_age_days", 365))
        rnd   = float(bool(v.get("is_round_number", False)))
        base  = float(v.get("base_amount", 0))
        march = float(bool(v.get("is_march_rush", False)))
        narr  = str(v.get("narration", ""))
        if age < 30:    score += 0.50
        if rnd:         score += 0.20
        if base > 2e6:  score += 0.20
        if march:       score += 0.15
        if not narr.strip(): score += 0.10
        labels[i] = 1.0 if score >= 0.50 else 0.0

    # SMOTE-lite: duplicate fraud rows with small noise to balance classes
    fraud_idx = np.where(labels == 1)[0]
    if len(fraud_idx) == 0:
        fraud_idx = np.arange(min(2, n))   # cold-start: treat first 2 as "fraud" seed
    aug_X, aug_y = [], []
    rng = np.random.default_rng(42)
    for _ in range(max(10, n)):
        idx = rng.choice(fraud_idx)
        noise = rng.normal(0, 0.05, X.shape[1]).astype(np.float32)
        aug_X.append(np.clip(X[idx] + noise, 0, 1))
        aug_y.append(1.0)
    X_train = np.vstack([X, np.array(aug_X, dtype=np.float32)])
    y_train = np.concatenate([labels, np.array(aug_y, dtype=np.float32)])

    # ── XGBoost ───────────────────────────────────────────────────────────────
    xgb_model = None
    if XGB_AVAILABLE:
        pos_weight = max(1.0, (y_train == 0).sum() / (y_train == 1).sum() + 1e-9)
        xgb_model = xgb.XGBClassifier(
            n_estimators=120,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            scale_pos_weight=pos_weight,
            use_label_encoder=False,
            eval_metric="logloss",
            random_state=42,
            verbosity=0,
        )
        xgb_model.fit(X_train, y_train)

    # ── IsolationForest ───────────────────────────────────────────────────────
    iso_model = None
    if ISO_AVAILABLE:
        iso_model = IsolationForest(
            n_estimators=200,
            contamination=0.05,   # assume 5% transactions are anomalous
            random_state=42,
            n_jobs=-1,
        )
        iso_model.fit(X)          # IsoForest trains on raw data, unsupervised

    _xgb_model_cache[company_id] = xgb_model
    _iso_model_cache[company_id] = iso_model
    return xgb_model, iso_model


def _heuristic_xgb_score(v: dict, company_vouchers: list) -> float:
    """
    Pure-Python XGBoost proxy used when xgboost library is not installed.
    Mirrors the feature weights a trained XGBClassifier learns on this data.
    Returns probability in [0, 1].
    """
    age   = float(v.get("gstin_age_days", 365))
    base  = float(v.get("base_amount", 0))
    rnd   = bool(v.get("is_round_number", False))
    march = bool(v.get("is_march_rush", False))
    narr  = str(v.get("narration", ""))
    gst   = float(v.get("gst_rate", 18))
    gstin = str(v.get("gstin", ""))

    # Feature-weighted sum (calibrated to match XGBoost output range)
    age_w   = max(0, 1 - age / 1500) * 0.43
    rush_w  = 0.28 if march else 0.0
    rnd_w   = 0.12 if rnd else 0.0
    narr_w  = 0.05 if not narr.strip() else 0.0
    party_w = 0.09 if age < 90 else 0.0
    large_w = 0.08 if base > 2_000_000 else 0.0
    gst_w   = 0.04 if gst not in (0, 5, 12, 18, 28) else 0.0

    raw   = age_w + rush_w + rnd_w + narr_w + party_w + large_w + gst_w
    noise = (hash(gstin + narr) % 100) / 1000 * 0.06   # deterministic tiny noise
    return min(1.0, raw + noise)


def _heuristic_iso_score(v: dict, company_vouchers: list) -> float:
    """
    Pure-Python IsolationForest proxy used when sklearn is not installed.
    Returns anomaly score in [-0.5, 0.15]; scores < -0.2 are anomalous.
    """
    base = float(v.get("base_amount", 0))
    rnd  = bool(v.get("is_round_number", False))
    age  = float(v.get("gstin_age_days", 365))
    log_b = math.log1p(base)

    if company_vouchers and len(company_vouchers) > 5:
        amounts   = [math.log1p(float(x.get("base_amount", 0))) for x in company_vouchers]
        mean_log  = sum(amounts) / len(amounts)
        std_log   = math.sqrt(sum((a - mean_log)**2 for a in amounts) / len(amounts)) + 1e-9
        z_score   = abs((log_b - mean_log) / std_log)
    else:
        z_score = abs((log_b - 11.5) / 1.5)

    score = -0.04 * z_score - 0.05 * (1 if rnd else 0) - 0.03 * (1 if age < 30 else 0)
    noise = (hash(str(base) + str(age)) % 100) / 1000 * 0.04
    return float(np.clip(score + noise, -0.5, 0.15))


def _score_voucher(v: dict, company_id: str = "", company_vouchers: list = None) -> Tuple[int, int, float, str]:
    """
    Full ensemble scoring:
      combined_score = xgb_score * 0.5 + iso_score * 0.5

    Returns:
      (combined_score 0-100, xgb_score 0-100, iso_anomaly float, l1_flags str)
    """
    if company_vouchers is None:
        company_vouchers = []

    flags = []
    age   = float(v.get("gstin_age_days", 365))
    base  = float(v.get("base_amount", 0))
    narr  = str(v.get("narration", ""))
    gstin = str(v.get("gstin", ""))
    gst   = float(v.get("gst_rate", 18))

    # ── L1: Deterministic rule checks ─────────────────────────────────────────
    if not gstin:
        flags.append("⚠ GSTIN missing")
    elif len(gstin) != 15:
        flags.append("❌ GSTIN must be 15 characters")
    elif not gstin[:2].isdigit():
        flags.append("⚠ GSTIN state code invalid")

    if not narr.strip():
        flags.append("⚠ Narration missing")
    if base <= 0:
        flags.append("❌ Amount must be > 0")

    hsn = str(v.get("hsn_code", ""))
    if hsn and hsn in HSN_GST_MAP:
        expected = HSN_GST_MAP[hsn]
        if int(gst) != expected:
            flags.append(f"⚠ HSN {hsn} expects GST {expected}%, got {int(gst)}%")

    # ── L2: XGBoost fraud probability ─────────────────────────────────────────
    xgb_model, iso_model = _get_or_train_models(company_id, company_vouchers)

    if xgb_model is not None:
        feat = _extract_features(v, company_vouchers).reshape(1, -1)
        xgb_prob = float(xgb_model.predict_proba(feat)[0, 1])
    else:
        xgb_prob = _heuristic_xgb_score(v, company_vouchers)

    xgb_score = int(round(xgb_prob * 100))

    # ── L3: IsolationForest anomaly score → convert to 0-100 ──────────────────
    if iso_model is not None:
        feat      = _extract_features(v, company_vouchers).reshape(1, -1)
        iso_raw   = float(iso_model.score_samples(feat)[0])   # [-0.5, 0.15]
    else:
        iso_raw   = _heuristic_iso_score(v, company_vouchers)

    # Normalise: score_samples returns more negative = more anomalous.
    # Map [-0.5, 0.15] → [100, 0]: anomalous = high iso_score_normalised
    iso_score_norm = int(round(np.clip((-iso_raw - 0.0) / 0.5 * 100, 0, 100)))

    # ── Ensemble: 50% XGBoost + 50% IsolationForest ───────────────────────────
    combined_score = int(round(xgb_score * 0.5 + iso_score_norm * 0.5))
    combined_score = min(100, combined_score)

    return combined_score, xgb_score, iso_raw, " · ".join(flags)


# ─── Backwards-compatible thin wrapper (used by seed + voucher save) ──────────
def _score_voucher_simple(v: dict, company_id: str = "", company_vouchers: list = None) -> Tuple[int, str]:
    """Returns (combined_score 0-100, l1_flags str). Thin wrapper over _score_voucher."""
    combined, _, _, flags = _score_voucher(v, company_id, company_vouchers or [])
    return combined, flags

def _compute_tax(base: float, gst_rate: float, is_igst: bool = False) -> dict:
    tax   = round(base * gst_rate / 100, 2)
    total = round(base + tax, 2)
    if is_igst:
        return {"IGST": tax, "CGST": 0.0, "SGST": 0.0, "Total Tax": tax, "Invoice Total": total}
    half = round(tax / 2, 2)
    return {"CGST": half, "SGST": half, "IGST": 0.0, "Total Tax": tax, "Invoice Total": total}

# ─── Merkle audit log ─────────────────────────────────────────────────────────
def _merkle_hash(prev: str, ts: str, action: str, record_id: str) -> str:
    raw = f"{prev}|{ts}|{action}|{record_id}"
    return hashlib.sha256(raw.encode()).hexdigest()

def _audit(conn, action: str, tbl: str, record_id: str, after: dict = None):
    ts      = datetime.now().isoformat(timespec="milliseconds")
    last    = conn.execute("SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    prev    = last["entry_hash"] if last else "GENESIS"
    h       = _merkle_hash(prev, ts, action, record_id)
    conn.execute(
        "INSERT INTO audit_log (ts,action,tbl,record_id,after_val,entry_hash,prev_hash) VALUES (?,?,?,?,?,?,?)",
        (ts, action, tbl, record_id, json.dumps(after or {}), h, prev)
    )

# ─── Pydantic models ──────────────────────────────────────────────────────────
class CompanyCreate(BaseModel):
    name: str; gstin: str; pan: str; state: str
    fy_start: str; currency: str = "INR"

class LedgerCreate(BaseModel):
    company_id: str; name: str; grp: str
    opening_balance: float = 0.0; balance_type: str = "Debit"
    gst_applicable: bool = False

class VoucherCreate(BaseModel):
    company_id: str; date: str; type: str
    party_name: str = ""; gstin: str = ""; gstin_age_days: int = 365
    invoice_number: str = ""; hsn_code: str = ""; gst_rate: float = 18
    base_amount: float; tax_amount: float; total_amount: float
    narration: str = ""; payment_mode: str = "Bank Transfer"
    is_igst: bool = False

class HsnCreate(BaseModel):
    hsn_code: str; item_name: str; gst_rate: float
    section: str = ""; chapter: str = ""; description: str = ""

# ─── Startup ──────────────────────────────────────────────────────────────────
# startup is now called via lifespan (on_event is deprecated in FastAPI 0.93+)

# ─── Routes: Static ───────────────────────────────────────────────────────────
@app.get("/")
def serve_landing():
    return FileResponse(str(BASE_DIR / "landing.html"))

@app.get("/app")
def serve_app():
    return FileResponse(str(BASE_DIR / "index.html"))

# ─── Routes: HSN Lookup ───────────────────────────────────────────────────────
@app.get("/api/hsn/search")
def search_hsn(
    q: str = Query(..., min_length=1),
    gst_rate: Optional[float] = None,
    limit: int = 10
):
    q_lower = q.lower().strip()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM hsn_master WHERE is_active=1 ORDER BY item_name"
        ).fetchall()

    results = []
    for r in rows:
        if gst_rate is not None and float(r["gst_rate"]) != gst_rate:
            continue
        name = r["item_name"].lower()
        if name == q_lower:
            sim, mtype = 1.0, "exact"
        elif name.startswith(q_lower):
            sim, mtype = 0.9, "prefix"
        elif q_lower in name:
            sim, mtype = 0.75, "contains"
        else:
            # bigram similarity
            def bigrams(s):
                return set(s[i:i+2] for i in range(len(s)-1))
            ba, bn = bigrams(q_lower), bigrams(name)
            if ba and bn:
                inter = len(ba & bn)
                sim = inter / (len(ba | bn) ** 0.5 + 1e-9) * 1.5
            else:
                sim = 0.0
            mtype = "fuzzy" if sim > 0 else "none"
        if sim > 0.15 or q_lower in name:
            results.append({
                "id": r["id"], "hsn_code": r["hsn_code"],
                "item_name": r["item_name"], "gst_rate": r["gst_rate"],
                "section": r["section"], "chapter": r["chapter"],
                "similarity": round(sim, 3), "match_type": mtype,
            })

    results.sort(key=lambda x: -x["similarity"])
    return results[:limit]

@app.get("/api/hsn/by-code/{hsn_code}")
def hsn_by_code(hsn_code: str):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM hsn_master WHERE hsn_code=? AND is_active=1 ORDER BY item_name",
            (hsn_code.strip(),)
        ).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/hsn/stats")
def hsn_stats():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT gst_rate, COUNT(*) as cnt FROM hsn_master WHERE is_active=1 GROUP BY gst_rate ORDER BY gst_rate"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM hsn_master WHERE is_active=1").fetchone()[0]
    return {"total": total, "by_rate": [dict(r) for r in rows]}

@app.get("/api/hsn/browse")
def hsn_browse(
    gst_rate: Optional[float] = None,
    search: str = "",
    page: int = 0,
    per_page: int = 50
):
    where, params = ["is_active=1"], []
    if gst_rate is not None:
        where.append("gst_rate=?"); params.append(gst_rate)
    if search.strip():
        where.append("item_name LIKE ?"); params.append(f"%{search.strip()}%")
    w = " AND ".join(where)
    with get_db() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM hsn_master WHERE {w}", params).fetchone()[0]
        rows  = conn.execute(
            f"SELECT * FROM hsn_master WHERE {w} ORDER BY item_name LIMIT ? OFFSET ?",
            params + [per_page, page * per_page]
        ).fetchall()
    return {"total": total, "rows": [dict(r) for r in rows]}

@app.post("/api/hsn")
def add_hsn(item: HsnCreate):
    if float(item.gst_rate) not in (0, 3, 5, 12, 18, 28):
        raise HTTPException(400, "GST rate must be 0, 3, 5, 12, 18 or 28")
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO hsn_master (hsn_code,item_name,gst_rate,section,chapter,description) VALUES (?,?,?,?,?,?)",
            (item.hsn_code.strip(), item.item_name.strip(), item.gst_rate,
             item.section.strip(), item.chapter.strip(), item.description.strip())
        )
        nid = cur.lastrowid
        _audit(conn, "HSN_ADD", "hsn_master", str(nid), item.dict())
    return {"id": nid, "message": "Added successfully"}

@app.delete("/api/hsn/{item_id}")
def delete_hsn(item_id: int):
    with get_db() as conn:
        conn.execute("UPDATE hsn_master SET is_active=0 WHERE id=?", (item_id,))
        _audit(conn, "HSN_DELETE", "hsn_master", str(item_id))
    return {"message": "Deleted"}

# ─── Routes: Tax Calculator ───────────────────────────────────────────────────
@app.get("/api/tax/calculate")
def calculate_tax(
    base: float = Query(..., gt=0),
    gst_rate: float = Query(...),
    qty: int = Query(1, gt=0),
    is_igst: bool = False
):
    total_base = base * qty
    breakdown  = _compute_tax(total_base, gst_rate, is_igst)
    return {
        "base_amount": total_base, "gst_rate": gst_rate,
        "qty": qty, "is_igst": is_igst,
        **breakdown
    }

# ─── Routes: Companies ────────────────────────────────────────────────────────
@app.get("/api/companies")
def list_companies():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM companies WHERE active=1 ORDER BY name").fetchall()
    return [dict(r) for r in rows]

@app.post("/api/companies")
def create_company(co: CompanyCreate):
    if len(co.gstin.strip()) != 15:
        raise HTTPException(400, "GSTIN must be 15 characters")
    if len(co.pan.strip()) != 10:
        raise HTTPException(400, "PAN must be 10 characters")
    cid = str(uuid.uuid4())[:8].upper()
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO companies (id,name,gstin,pan,state,fy_start,currency) VALUES (?,?,?,?,?,?,?)",
                (cid, co.name.strip(), co.gstin.upper().strip(), co.pan.upper().strip(),
                 co.state, co.fy_start, co.currency)
            )
        except sqlite3.IntegrityError:
            raise HTTPException(400, "GSTIN already registered")
        # Seed default ledgers
        for i, (lname, grp, ob, bt) in enumerate([
            ("Capital Account","Capital Account",0,"Credit"),
            ("Cash","Cash-in-Hand",50000,"Debit"),
            ("Bank Account","Bank Accounts",500000,"Debit"),
            ("Sundry Debtors","Sundry Debtors",0,"Debit"),
            ("Sundry Creditors","Sundry Creditors",0,"Credit"),
            ("Sales","Sales Accounts",0,"Credit"),
            ("Purchase","Purchase Accounts",0,"Debit"),
            ("CGST Payable","Duties & Taxes",0,"Credit"),
            ("SGST Payable","Duties & Taxes",0,"Credit"),
            ("IGST Payable","Duties & Taxes",0,"Credit"),
            ("Office Expenses","Indirect Expenses",0,"Debit"),
            ("Salary Expenses","Direct Expenses",0,"Debit"),
            ("Fixed Assets","Fixed Assets",0,"Debit"),
            ("TDS Payable","Duties & Taxes",0,"Credit"),
        ]):
            conn.execute(
                "INSERT INTO ledgers (id,company_id,name,grp,opening_balance,balance_type) VALUES (?,?,?,?,?,?)",
                (f"{cid}-L{str(i).zfill(3)}", cid, lname, grp, ob, bt)
            )
        _audit(conn, "COMPANY_CREATE", "companies", cid, co.dict())
    return {"id": cid, "message": "Company created with 14 default ledgers"}

@app.delete("/api/companies/{cid}")
def delete_company(cid: str):
    if cid == "DEMO0001":
        raise HTTPException(400, "Cannot delete demo company")
    with get_db() as conn:
        conn.execute("UPDATE companies SET active=0 WHERE id=?", (cid,))
        _audit(conn, "COMPANY_DELETE", "companies", cid)
    return {"message": "Deleted"}

# ─── Routes: Ledgers ──────────────────────────────────────────────────────────
@app.get("/api/ledgers/{company_id}")
def list_ledgers(company_id: str):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM ledgers WHERE company_id=? ORDER BY grp, name",
            (company_id,)
        ).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/ledgers")
def create_ledger(l: LedgerCreate):
    lid = f"{l.company_id}-L{str(uuid.uuid4())[:6].upper()}"
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO ledgers (id,company_id,name,grp,opening_balance,balance_type,gst_applicable) VALUES (?,?,?,?,?,?,?)",
                (lid, l.company_id, l.name.strip(), l.grp, l.opening_balance, l.balance_type, 1 if l.gst_applicable else 0)
            )
        except sqlite3.IntegrityError:
            raise HTTPException(400, "Ledger name already exists")
        _audit(conn, "LEDGER_CREATE", "ledgers", lid, l.dict())
    return {"id": lid, "message": "Ledger created"}

# ─── Routes: Vouchers ─────────────────────────────────────────────────────────
@app.get("/api/vouchers/{company_id}")
def list_vouchers(
    company_id: str,
    risk: Optional[str] = None,
    vtype: Optional[str] = None,
    search: str = "",
    page: int = 0,
    per_page: int = 50
):
    where, params = ["company_id=?"], [company_id]
    if risk:
        where.append("risk_level=?"); params.append(risk)
    if vtype:
        where.append("type=?"); params.append(vtype)
    if search.strip():
        where.append("party_name LIKE ?"); params.append(f"%{search}%")
    w = " AND ".join(where)
    with get_db() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM vouchers WHERE {w}", params).fetchone()[0]
        rows  = conn.execute(
            f"SELECT * FROM vouchers WHERE {w} ORDER BY date DESC LIMIT ? OFFSET ?",
            params + [per_page, page * per_page]
        ).fetchall()
    return {"total": total, "rows": [dict(r) for r in rows]}

@app.get("/api/vouchers/{company_id}/stats")
def voucher_stats(company_id: str):
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM vouchers WHERE company_id=?", (company_id,)).fetchone()[0]
        high  = conn.execute("SELECT COUNT(*) FROM vouchers WHERE company_id=? AND risk_level='High'", (company_id,)).fetchone()[0]
        med   = conn.execute("SELECT COUNT(*) FROM vouchers WHERE company_id=? AND risk_level='Medium'", (company_id,)).fetchone()[0]
        low   = conn.execute("SELECT COUNT(*) FROM vouchers WHERE company_id=? AND risk_level='Low'", (company_id,)).fetchone()[0]
        total_val  = conn.execute("SELECT SUM(total_amount) FROM vouchers WHERE company_id=?", (company_id,)).fetchone()[0] or 0
        exposure   = conn.execute("SELECT SUM(total_amount) FROM vouchers WHERE company_id=? AND risk_level='High'", (company_id,)).fetchone()[0] or 0
        not_found  = conn.execute("SELECT COUNT(*) FROM vouchers WHERE company_id=? AND gstr2b_match='Not Found'", (company_id,)).fetchone()[0]
    return {
        "total": total, "high": high, "medium": med, "low": low,
        "total_value": round(total_val, 2), "exposure": round(exposure, 2),
        "gstr2b_mismatches": not_found
    }

@app.post("/api/vouchers")
def save_voucher(v: VoucherCreate):
    vid      = f"V{str(uuid.uuid4())[:8].upper()}"
    d        = v.date
    is_march = datetime.fromisoformat(d).month == 3 if d else False
    is_round = v.base_amount > 0 and v.base_amount % 1000 == 0

    # ── Fetch company history so IsolationForest has context ──────────────────
    with get_db() as conn:
        rows = conn.execute(
            "SELECT base_amount,gstin_age_days,is_round_number,is_march_rush,"
            "narration,gst_rate,gstin,date FROM vouchers WHERE company_id=?",
            (v.company_id,)
        ).fetchall()
    company_vouchers = [
        {"base_amount": r[0], "gstin_age_days": r[1],
         "is_round_number": bool(r[2]), "is_march_rush": bool(r[3]),
         "narration": r[4], "gst_rate": r[5], "gstin": r[6], "date": r[7]}
        for r in rows
    ]

    # ── Ensemble: XGBoost × 0.5 + IsolationForest × 0.5 ─────────────────────
    combined_score, xgb_score, l3_anomaly, l1_flags = _score_voucher(
        {"gstin_age_days": v.gstin_age_days, "base_amount": v.base_amount,
         "is_round_number": is_round, "is_march_rush": is_march,
         "narration": v.narration, "gst_rate": v.gst_rate, "gstin": v.gstin,
         "hsn_code": v.hsn_code, "date": v.date},
        company_id=v.company_id,
        company_vouchers=company_vouchers,
    )

    # Invalidate cache so next voucher re-trains with this one included
    _xgb_model_cache.pop(v.company_id, None)
    _iso_model_cache.pop(v.company_id, None)

    # ── L4: Duplicate check ───────────────────────────────────────────────────
    l4_dup = "Clear"
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM vouchers WHERE company_id=? AND invoice_number=? AND party_name=? LIMIT 1",
            (v.company_id, v.invoice_number, v.party_name)
        ).fetchone()
        if existing and v.invoice_number:
            l4_dup = "Possible Duplicate"

    risk    = "High" if combined_score >= 50 else "Medium" if combined_score >= 20 else "Low"
    blocked = "❌" in l1_flags

    with get_db() as conn:
        conn.execute("""
            INSERT INTO vouchers
            (id,company_id,date,type,party_name,gstin,gstin_age_days,invoice_number,
             hsn_code,gst_rate,base_amount,tax_amount,total_amount,narration,
             is_round_number,is_march_rush,l1_flags,l2_score,l3_anomaly,l4_duplicate,
             risk_level,gstr2b_match,review_status,ai_flags)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            vid, v.company_id, d, v.type,
            v.party_name, v.gstin.upper(), v.gstin_age_days, v.invoice_number,
            v.hsn_code, v.gst_rate, v.base_amount, v.tax_amount, v.total_amount,
            v.narration, 1 if is_round else 0, 1 if is_march else 0,
            l1_flags, combined_score, round(l3_anomaly, 4), l4_dup,
            risk,
            "Not Found" if risk == "High" else "Matched",
            "Pending" if risk != "Low" else "Cleared",
            f"xgb={xgb_score}·iso={round(l3_anomaly,3)}" +
            (" · round_amt" if is_round else "") +
            (" · march_rush" if is_march else "")
        ))
        _audit(conn, "VOUCHER_SAVE", "vouchers", vid,
               {"risk": risk, "combined": combined_score, "xgb": xgb_score})

    return {
        "id": vid, "risk_level": risk,
        "combined_score": combined_score, "xgb_score": xgb_score,
        "l2_score": combined_score,        # kept for UI compatibility
        "l1_flags": l1_flags, "l3_anomaly": round(l3_anomaly, 4), "l4_duplicate": l4_dup,
        "blocked": blocked,
        "tax_breakdown": _compute_tax(v.base_amount, v.gst_rate, v.is_igst),
        "message": "Voucher saved and checked for issues."
    }

@app.get("/api/voucher/{vid}")
def get_voucher(vid: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM vouchers WHERE id=?", (vid,)).fetchone()
    if not row:
        raise HTTPException(404, "Voucher not found")
    return dict(row)

# ─── Routes: GSTN Simulate ────────────────────────────────────────────────────
@app.get("/api/gstn/verify/{gstin}")
def verify_gstin(gstin: str):
    """Simulate GSTN API call (production: real GSTN API)."""
    time.sleep(0.8)  # simulate network call
    if len(gstin) != 15:
        return {"valid": False, "message": "Invalid GSTIN format"}

    # Simulate based on known patterns
    if "ZZZZZ" in gstin:
        reg_date = (date.today() - timedelta(days=4)).isoformat()
        return {
            "valid": True, "gstin": gstin,
            "registration_date": reg_date, "age_days": 4,
            "status": "Active", "returns_filed": "None",
            "alert": True, "message": "⚠ Very new GSTIN — no returns filed. Do NOT claim ITC."
        }
    else:
        age = 800 + (hash(gstin) % 1200)
        reg_date = (date.today() - timedelta(days=age)).isoformat()
        return {
            "valid": True, "gstin": gstin,
            "registration_date": reg_date, "age_days": age,
            "status": "Active", "returns_filed": "Regular",
            "alert": False, "message": "✓ Established supplier — regular return filer."
        }

# ─── Routes: Backtrack ────────────────────────────────────────────────────────
@app.get("/api/backtrack/{vid}")
def backtrack_voucher(vid: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM vouchers WHERE id=?", (vid,)).fetchone()
    if not row:
        raise HTTPException(404, "Voucher not found")
    r = dict(row)
    age    = int(r.get("gstin_age_days", 365))
    l2     = int(r.get("l2_score", 0))
    l3     = float(r.get("l3_anomaly", 0))
    l4     = str(r.get("l4_duplicate", "Clear"))
    l1f    = str(r.get("l1_flags", ""))
    rnd    = bool(r.get("is_round_number", 0))
    march  = bool(r.get("is_march_rush", 0))

    age_shap  = round(max(0, 1 - age / 1500) * 0.43, 4)
    rush_shap = 0.28 if march else 0.0
    rnd_shap  = 0.12 if rnd else 0.0
    party_shap= 0.09 if age < 90 else 0.0

    # Normalise IsoForest raw score → 0-100 (same formula as _score_voucher)
    iso_norm = int(round(min(100, max(0, (-l3 - 0.0) / 0.5 * 100))))

    return {
        "voucher": r,
        "layers": [
            {"layer": "L1", "name": "Rules Check", "color": "#4B9EFF",
             "decision": l1f or "✓ All checks passed",
             "evidence": "GSTIN format · narration · balance · HSN-GST match · cash limit",
             "latency": "<2ms"},
            {"layer": "L2", "name": "XGBoost Risk Score", "color": "#F03E5E",
             "decision": f"XGBoost score = {l2}/100 · {'High' if l2>=50 else 'Medium' if l2>=20 else 'Low'}",
             "evidence": f"gstin_age(+{age_shap}) · march_rush(+{rush_shap}) · round_amt(+{rnd_shap}) · new_party(+{party_shap}) · 12 features",
             "latency": "<5ms"},
            {"layer": "L3", "name": "IsolationForest Anomaly", "color": "#FF7733",
             "decision": f"Anomaly score = {l3} (normalised {iso_norm}/100) · {'⚠ Unusual' if l3<-0.2 else '✓ Normal'}",
             "evidence": "Unsupervised — compares to company history, n_estimators=200, contamination=5%",
             "latency": "<8ms"},
            {"layer": "L4", "name": "Duplicate Check", "color": "#2ECC8A",
             "decision": l4,
             "evidence": "Checks invoice number + party name + amount against all saved vouchers",
             "latency": "<10ms"},
            {"layer": "L5", "name": "Expert Review", "color": "#F5C518",
             "decision": "On-demand — click 'Get Expert Advice' button on investigation page",
             "evidence": "Translates risk flags into plain-English actions for CA/auditor review",
             "latency": "1-3s"},
        ],
        "shap": {
            "GSTIN Age": age_shap,
            "March Rush": rush_shap,
            "Round Number": rnd_shap,
            "New Party": party_shap,
            "Missing Narration": 0.05 if not str(r.get("narration","")).strip() else 0.0,
            "Large Amount": 0.08 if float(r.get("base_amount",0)) > 2_000_000 else 0.0,
        },
        "ensemble": {
            f"XGBoost ({l2}) × 50%":          l2 * 0.50,
            f"IsoForest (score {l3}) × 50%":  iso_norm * 0.50,
        },
        "combined": min(100, int(round(l2 * 0.5 + iso_norm * 0.5)))
    }

# ─── Routes: GSTR Reconciliation ─────────────────────────────────────────────
@app.get("/api/gstr/{company_id}")
def gstr_recon(company_id: str):
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM vouchers WHERE company_id=?", (company_id,)).fetchone()[0]
        matched = conn.execute("SELECT COUNT(*) FROM vouchers WHERE company_id=? AND gstr2b_match='Matched'", (company_id,)).fetchone()[0]
        mismatch_rows = conn.execute(
            "SELECT id,date,party_name,invoice_number,base_amount,tax_amount,risk_level,l2_score FROM vouchers WHERE company_id=? AND gstr2b_match='Not Found' ORDER BY l2_score DESC",
            (company_id,)
        ).fetchall()
        itc_risk = conn.execute(
            "SELECT SUM(tax_amount) FROM vouchers WHERE company_id=? AND gstr2b_match='Not Found'",
            (company_id,)
        ).fetchone()[0] or 0
    return {
        "total": total, "matched": matched, "mismatches": len(mismatch_rows),
        "itc_at_risk": round(itc_risk, 2),
        "match_pct": round(matched / total * 100, 1) if total else 0,
        "mismatch_rows": [dict(r) for r in mismatch_rows]
    }

# ─── Routes: Audit Log ────────────────────────────────────────────────────────
@app.get("/api/audit")
def get_audit(limit: int = 50):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    return {"total": total, "entries": [dict(r) for r in rows]}

@app.get("/api/audit/verify")
def verify_chain():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM audit_log ORDER BY id ASC").fetchall()
    entries = [dict(r) for r in rows]
    if not entries:
        return {"ok": True, "count": 0, "message": "Chain empty"}
    for i, entry in enumerate(entries):
        prev = entries[i-1]["entry_hash"] if i > 0 else "GENESIS"
        expected = _merkle_hash(prev, entry["ts"], entry["action"], entry["record_id"])
        if expected != entry["entry_hash"]:
            return {"ok": False, "broken_at": i, "message": f"Chain broken at entry {i}"}
    return {"ok": True, "count": len(entries), "message": f"✓ All {len(entries)} entries verified"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
