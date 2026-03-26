-- ============================================================
-- AccuLedger HSN-GST Master Database
-- SQLite Schema + Full Seed Data
-- Run: python main.py  (auto-initialised on first run)
-- ============================================================

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

-- ── Companies ──────────────────────────────────────────────
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

-- ── Ledgers ────────────────────────────────────────────────
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

-- ── Vouchers ───────────────────────────────────────────────
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

-- ── Audit Log ──────────────────────────────────────────────
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

-- ── SEED: HSN Master ───────────────────────────────────────
INSERT OR IGNORE INTO hsn_master (hsn_code, item_name, gst_rate, section, chapter) VALUES
-- Electronics
('8471','Laptop',18,'XVI','84'),
('8471','Desktop Computer',18,'XVI','84'),
('8471','Tablet Computer',18,'XVI','84'),
('8517','Mobile Phone',18,'XVI','85'),
('8517','Smartphone',18,'XVI','85'),
('8443','Printer',18,'XVI','84'),
('8528','TV',18,'XVI','85'),
('8528','LED TV',18,'XVI','85'),
('8518','Speaker',18,'XVI','85'),
('8518','Headphones',18,'XVI','85'),
('8518','Earphones',18,'XVI','85'),
('8414','Fan',18,'XVI','84'),
('8414','Ceiling Fan',18,'XVI','84'),
('8415','Air Conditioner',28,'XVI','84'),
('8415','AC',28,'XVI','84'),
('8415','Split AC',28,'XVI','84'),
('8418','Refrigerator',18,'XVI','84'),
('8418','Fridge',18,'XVI','84'),
('8450','Washing Machine',18,'XVI','84'),
('8539','LED Bulb',12,'XVI','85'),
('8539','Tube Light',12,'XVI','85'),
-- Stationery
('9608','Pen',12,'XX','96'),
('9608','Ball Pen',12,'XX','96'),
('9608','Gel Pen',12,'XX','96'),
('9609','Pencil',12,'XX','96'),
('4820','Notebook',12,'XX','48'),
('4820','Register',12,'XX','48'),
('4901','Books',0,'XIX','49'),
('4901','Textbooks',0,'XIX','49'),
-- Dairy
('0401','Milk',0,'I','04'),
('0401','Packed Milk',0,'I','04'),
('0403','Yogurt',0,'I','04'),
('0403','Curd / Dahi',0,'I','04'),
('0405','Butter',12,'I','04'),
('0406','Cheese',12,'I','04'),
('0406','Paneer',12,'I','04'),
('0407','Eggs',0,'I','04'),
('0409','Honey',0,'I','04'),
('2105','Ice Cream',18,'IV','21'),
-- Grains & Pulses
('1006','Rice',0,'II','10'),
('1006','Basmati Rice',0,'II','10'),
('1001','Wheat',0,'II','10'),
('1101','Flour / Atta',5,'II','11'),
('1101','Wheat Flour',5,'II','11'),
('1101','Maida',5,'II','11'),
('0713','Dal',0,'II','07'),
('0713','Moong Dal',0,'II','07'),
('0713','Toor Dal',0,'II','07'),
('0713','Rajma',0,'II','07'),
-- Sugar & Sweeteners
('1701','Sugar',5,'IV','17'),
('1702','Jaggery / Gur',5,'IV','17'),
('1704','Candy',28,'IV','17'),
('1704','Chewing Gum',18,'IV','17'),
-- Oils
('1507','Soyabean Oil',5,'III','15'),
('1509','Olive Oil',5,'III','15'),
('1512','Sunflower Oil',5,'III','15'),
('1513','Coconut Oil',5,'III','15'),
('1514','Mustard Oil',5,'III','15'),
('1508','Groundnut Oil',5,'III','15'),
-- Vegetables & Fruits
('0701','Potato',0,'II','07'),
('0702','Tomato',0,'II','07'),
('0703','Onion',0,'II','07'),
('0803','Banana',0,'II','08'),
('0804','Mango',0,'II','08'),
('0808','Apple',0,'II','08'),
-- Tea & Coffee
('0902','Tea',5,'I','09'),
('0902','Green Tea',5,'I','09'),
('0901','Coffee',5,'I','09'),
('2101','Instant Coffee',12,'IV','21'),
-- Beverages
('2201','Packaged Water',0,'IV','22'),
('2202','Cold Drink',18,'IV','22'),
('2202','Energy Drink',18,'IV','22'),
('2009','Fruit Juice',12,'IV','20'),
-- Packaged Foods
('1902','Noodles',18,'IV','19'),
('1902','Instant Noodles',18,'IV','19'),
('1902','Pasta',18,'IV','19'),
('1905','Biscuits',18,'IV','19'),
('1905','Bread',12,'IV','19'),
('1905','Cake',18,'IV','19'),
('1905','Rusk',12,'IV','19'),
('1905','Popcorn',18,'IV','19'),
('2007','Jam',12,'IV','20'),
('2008','Potato Chips',12,'IV','20'),
('2008','Peanut Butter',12,'IV','20'),
('2103','Ketchup',12,'IV','21'),
('2103','Garam Masala',12,'IV','21'),
('2106','Namkeen / Snacks',18,'IV','21'),
('1806','Chocolate',28,'IV','18'),
-- Spices
('0904','Chilli Powder',5,'I','09'),
('0910','Turmeric Powder',5,'I','09'),
('0909','Coriander Powder',5,'I','09'),
('2501','Salt',0,'V','25'),
-- Personal Care
('3305','Shampoo',18,'VI','33'),
('3305','Hair Oil',18,'VI','33'),
('3305','Hair Colour',28,'VI','33'),
('3401','Soap',18,'VI','34'),
('3401','Bathing Soap',18,'VI','34'),
('3306','Toothpaste',18,'VI','33'),
('3307','Deodorant',18,'VI','33'),
('3304','Face Cream',28,'VI','33'),
('3304','Face Wash',28,'VI','33'),
('3304','Body Lotion',28,'VI','33'),
('3304','Sunscreen',28,'VI','33'),
('3304','Perfume / Attar',28,'VI','33'),
('3808','Sanitiser',18,'VI','38'),
-- Medical
('3004','Medicines',12,'VI','30'),
('3004','Medical Tablets',12,'VI','30'),
-- Clothing
('6109','T-Shirt',5,'XI','61'),
('6203','Jeans',12,'XI','62'),
('6203','Trousers',12,'XI','62'),
('6403','Shoes',18,'XII','64'),
('6403','Sneakers',18,'XII','64'),
-- Home
('6302','Towel',12,'XI','63'),
('6302','Bed Sheet',12,'XI','63'),
('5701','Carpet',12,'XI','57'),
-- Plastics
('3923','Plastic Bucket',18,'VII','39'),
('3923','Plastic Bottle',18,'VII','39'),
('3917','PVC Pipe',18,'VII','39'),
-- Furniture
('9403','Furniture',18,'XX','94'),
('9403','Office Chair',18,'XX','94'),
('9401','Chair',18,'XX','94'),
-- Construction
('2523','Cement',28,'V','25'),
('7214','Steel Rod',18,'XV','72'),
-- Vehicles
('8703','Car',28,'XVII','87'),
('8711','Bike / Motorcycle',28,'XVII','87'),
('8711','Scooter',28,'XVII','87'),
-- Jewellery
('7113','Gold Jewellery',3,'XIV','71'),
('7113','Silver Jewellery',3,'XIV','71'),
-- Dry Fruits
('0813','Raisins',5,'II','08'),
('0813','Dates',5,'II','08'),
('0802','Almond',5,'II','08'),
('0802','Cashew',5,'II','08');
