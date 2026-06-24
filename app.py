import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import random
import re
import base64
from weasyprint import HTML

# --- PAGE SETUP & THEME INITIALIZATION ---
st.set_page_config(
    page_title="ARK Premium Solutions - Quotation Portal", 
    page_icon="🌐", 
    layout="wide"
)

# Custom UI CSS Inject for Sky Blue/Slate theme pairing & proper word-wrap constraints
st.markdown("""
<style>
    :root { --main-color: #00a8e8; }
    .stButton>button { background-color: #00a8e8 !important; color: white !important; font-weight: bold; }
    .reportview-container { background: #f4f7f6; }
    /* Force word wrap on standard table cells */
    .stDataFrame td, .stDataFrame th {
        white-space: normal !important;
        word-wrap: break-word !important;
    }
</style>
""", unsafe_allow_html=True)

# --- DATABASE ARCHITECTURE INITIALIZATION ---
DB_FILE = "ark_enterprise.db"

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        # Users Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                is_verified INTEGER DEFAULT 0,
                verification_code TEXT
            )
        """)
        # Team Assignment Table (Director -> Manager hierarchy)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS team_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                director_id INTEGER,
                manager_id INTEGER,
                status TEXT DEFAULT 'PENDING',
                FOREIGN KEY(director_id) REFERENCES users(id),
                FOREIGN KEY(manager_id) REFERENCES users(id)
            )
        """)
        # Quotations Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                po_number TEXT UNIQUE NOT NULL,
                creator_id INTEGER,
                customer_name TEXT,
                project_name TEXT,
                attention_person TEXT,
                attention_email TEXT,
                attention_phone TEXT,
                status TEXT,
                issue_date TEXT,
                validity TEXT,
                lead_time TEXT,
                payment_term TEXT,
                terms_conditions TEXT,
                subtotal REAL,
                discount REAL,
                tax REAL,
                grand_total REAL,
                items_json TEXT,
                FOREIGN KEY(creator_id) REFERENCES users(id)
            )
        """)
        # Insert a Default Seed Admin if it does not exist
        admin_exists = conn.execute("SELECT 1 FROM users WHERE LOWER(email)='admin@arktechsolutions.net'").fetchone()
        if not admin_exists:
            pwd_hash = hashlib.sha256("ArkAdmin2026!".encode()).hexdigest()
            conn.execute("INSERT INTO users (email, password_hash, role, is_verified) VALUES (?, ?, ?, 1)",
                         ("admin@arktechsolutions.net", pwd_hash, "Admin"))
        conn.commit()

init_db()

# --- HELPER SECURITY FUNCTIONS ---
def hash_pwd(password):
    return hashlib.sha256(password.encode()).hexdigest()

def send_mock_verification_email(email, code):
    st.info(f"📧 Transactional System Log: Sent verification code `{code}` to verified destination mailbox {email}")

# --- PARSING HEURISTICS ENGINE ---
def parse_uploaded_document(df_raw):
    """
    Scans data columns dynamically to isolate Part Number and Description (longest text field).
    """
    structured_items = []
    if df_raw.empty:
        return structured_items

    # Identify the column with the longest text string to use as description
    sample_rows = df_raw.head(10).astype(str)
    desc_col = sample_rows.apply(lambda x: x.str.len().max()).idxmax()
    
    qty_col = None
    price_col = None
    for col in df_raw.columns:
        col_lower = str(col).lower()
        if 'qty' in col_lower or 'quant' in col_lower:
            qty_col = col
        elif 'price' in col_lower or 'rate' in col_lower or 'unit' in col_lower:
            price_col = col

    for idx, row in df_raw.iterrows():
        desc_val = str(row[desc_col]) if desc_col in df_raw.columns else ""
        if pd.isna(row[desc_col]) or desc_val.strip() == "" or "total" in desc_val.lower():
            continue
            
        qty_val = 1
        if qty_col:
            try: qty_val = int(float(str(row[qty_col]).replace(',', '')))
            except: pass
            
        price_val = 0.0
        if price_col:
            try: price_val = float(re.sub(r'[^\d\.]', '', str(row[price_col])))
            except: pass
            
        part_no = "ARK-PART"
        for col in df_raw.columns:
            if col != desc_col and col != qty_col and col != price_col:
                val = str(row[col]).strip()
                if val and len(val) < 15 and val != "nan":
                    part_no = val
                    break

        structured_items.append({
            "No": str(idx + 1),
            "Part Number/Model": part_no,
            "Description": desc_val,
            "Qty": qty_val,
            "Unit Price": price_val,
            "Margin %": 20.0,
            "Final Price": price_val
        })
    return structured_items

# --- CORE SESSION STATE STATEFUL ROUTING ---
if "user" not in st.session_state: st.session_state.user = None
if "viewing_page" not in st.session_state: st.session_state.viewing_page = "Auth Workspace"

# ==========================================
# AUTHENTICATION HUB
# ==========================================
if not st.session_state.user:
    st.subheader("🔒 ARK Premium Solutions Portal Authentication")
    auth_tab1, auth_tab2 = st.tabs(["Sign In System", "Register New Profile"])
    
    with auth_tab1:
        login_email = st.text_input("Corporate Email Address", key="login_em").strip()
        login_pwd = st.text_input("Password Secure Vector", type="password", key="login_pw")
        if st.button("Sign In"):
            with get_db() as conn:
                res = conn.execute("SELECT * FROM users WHERE LOWER(email)=LOWER(?) AND password_hash=?", (login_email, hash_pwd(login_pwd))).fetchone()
                if res:
                    if res["is_verified"] == 0:
                        st.error("Account verification code pending clearance.")
                    else:
                        st.session_state.user = {"id": res["id"], "email": res["email"], "role": res["role"]}
                        st.success("Access Granted! Loading your workspace...")
                        st.rerun()
                else:
                    st.error("Invalid credentials supplied. Check your password or email spelling.")
                    
    with auth_tab2:
        reg_email = st.text_input("Corporate Email Address", key="reg_em").strip()
        reg_pwd = st.text_input("Create Security Password", type="password", key="reg_pw")
        reg_role = st.selectbox("Requested Core Functional Target Profile", ["Account Manager"])
        
        if st.button("Initiate Sign Up Pipeline"):
            if not reg_email or not reg_pwd:
                st.error("All fields are mandatory.")
            else:
                code = str(random.randint(100000, 999999))
                try:
                    with get_db() as conn:
                        conn.execute("INSERT INTO users (email, password_hash, role, is_verified, verification_code) VALUES (?, ?, ?, 0, ?)",
                                     (reg_email, hash_pwd(reg_pwd), reg_role, code))
                        conn.commit()
                    send_mock_verification_email(reg_email, code)
                    st.success("Registration success! Check console window or informational alerts below for verification vector.")
                except sqlite3.IntegrityError:
                    st.error("Identity database conflict: Email already registered inside network ledger.")
                
        st.markdown("---")
        verify_email = st.text_input("Confirm Registered Email Destination Address", key="v_em").strip()
        verify_code = st.text_input("Enter 6-Digit OTP Secure Access Code", key="v_cd").strip()
        if st.button("Verify Credentials Clearance"):
            with get_db() as conn:
                user_rec = conn.execute("SELECT * FROM users WHERE LOWER(email)=LOWER(?) AND verification_code=?", (verify_email, verify_code)).fetchone()
                if user_rec:
                    conn.execute("UPDATE users SET is_verified=1 WHERE LOWER(email)=LOWER(?)", (verify_email,))
                    conn.commit()
                    st.success("Verification clearance complete! Proceed to Sign In.")
                else:
                    st.error("Verification matrix mismatch. Code rejected.")
    st.stop()

# --- POST-AUTHENTICATION ENVIRONMENT VARIABLES ---
current_user = st.session_state.user
st.sidebar.markdown(f"**Authenticated Entity:** `{current_user['email']}`")
st.sidebar.markdown(f"**Functional Domain Clearance:** `{current_user['role']}`")
if st.sidebar.button("Logout Session Log"):
    st.session_state.user = None
    st.rerun()

# ==========================================
# ADMIN PROMOTION VECTOR HUB
# ==========================================
if current_user["role"] == "Admin":
    st.header("👑 Global Infrastructure Admin Console")
    with get_db() as conn:
        all_users = conn.execute("SELECT id, email, role FROM users WHERE role != 'Admin'").fetchall()
    
    st.subheader("Manage User Roles")
    for u in all_users:
        col_u1, col_u2 = st.columns([3, 2])
        col_u1.write(f"👤 {u['email']} - Current Role: **{u['role']}**")
        new_r = col_u2.selectbox("Reassign Global Directives", ["Account Manager", "Account Director", "Top Management"], key=f"user_r_{u['id']}", index=["Account Manager", "Account Director", "Top Management"].index(u['role']) if u['role'] in ["Account Manager", "Account Director", "Top Management"] else 0)
        if new_r != u['role']:
            with get_db() as conn:
                conn.execute("UPDATE users SET role=? WHERE id=?", (new_r, u['id']))
                conn.commit()
            st.success(f"Updated {u['email']} to {new_r}")
            st.rerun()
    st.stop()

# ==========================================
# ROLE BASED DIRECTIVES NAVIGATION MATRIX
# ==========================================
nav_options = ["🏠 Dashboard Console", "➕ Build New Quotation Module"]
if current_user["role"] == "Account Director":
    nav_options.append("👥 Manage Assigned Account Teams")
    
page_selection = st.sidebar.radio("Navigation Directives", nav_options)

# ==========================================
# 🏠 DASHBOARD ENGINE
# ==========================================
if page_selection == "🏠 Dashboard Console":
    st.header(f"📊 Activity Metrics Control Dashboard - {current_user['role']}")
    
    with get_db() as conn:
        if current_user["role"] == "Account Manager":
            quotes = conn.execute("SELECT * FROM quotations WHERE creator_id=?", (current_user["id"],)).fetchall()
        elif current_user["role"] == "Account Director":
            quotes = conn.execute("""
                SELECT q.* FROM quotations q 
                WHERE q.creator_id = ? 
                OR q.creator_id IN (SELECT manager_id FROM team_mappings WHERE director_id=? AND status='ACCEPTED')
            """, (current_user["id"], current_user["id"])).fetchall()
        elif current_user["role"] == "Top Management":
            quotes = conn.execute("SELECT q.*, u.email as creator_email FROM quotations q JOIN users u ON q.creator_id = u.id").fetchall()

    df_quotes = pd.DataFrame([dict(q) for q in quotes]) if quotes else pd.DataFrame()
    
    if not df_quotes.empty:
        kpi1, kpi2, kpi3 = st.columns(