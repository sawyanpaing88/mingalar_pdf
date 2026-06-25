import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import random
import re
import json
import base64
from datetime import datetime
from weasyprint import HTML
from pypdf import PdfReader

# --- PAGE SETUP & THEME INITIALIZATION ---
st.set_page_config(
    page_title="ARK Premium Solutions - Quotation Portal", 
    page_icon="🌐", 
    layout="wide"
)

st.markdown("""
<style>
    :root { --main-color: #00a8e8; }
    .stButton>button { background-color: #00a8e8 !important; color: white !important; font-weight: bold; }
    .reportview-container { background: #f4f7f6; }
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
                currency_unit TEXT,
                exchange_rate REAL,
                items_json TEXT,
                FOREIGN KEY(creator_id) REFERENCES users(id)
            )
        """)
        
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(quotations)")
        columns = [column[1] for column in cursor.fetchall()]
        if "currency_unit" not in columns:
            conn.execute("ALTER TABLE quotations ADD COLUMN currency_unit TEXT DEFAULT 'USD'")
        if "exchange_rate" not in columns:
            conn.execute("ALTER TABLE quotations ADD COLUMN exchange_rate REAL DEFAULT 1.0")

        admin_exists = conn.execute("SELECT 1 FROM users WHERE LOWER(email)='admin@arktechsolutions.net'").fetchone()
        if not admin_exists:
            pwd_hash = hashlib.sha256("ArkAdmin2026!".encode()).hexdigest()
            conn.execute("INSERT INTO users (email, password_hash, role, is_verified) VALUES (?, ?, ?, 1)",
                         ("admin@arktechsolutions.net", pwd_hash, "Admin"))
        conn.commit()

init_db()

def hash_pwd(password):
    return hashlib.sha256(password.encode()).hexdigest()

def send_mock_verification_email(email, code):
    st.info(f"📧 Transactional System Log: Sent verification code `{code}` to verified destination mailbox {email}")

# --- PARSING HEURISTICS ENGINE ---
def parse_uploaded_document(df_raw):
    structured_items = []
    if df_raw.empty:
        return structured_items

    df_raw.columns = [str(c).strip() for c in df_raw.columns]
    sample_rows = df_raw.head(10).astype(str)
    desc_col = sample_rows.apply(lambda x: x.str.len().max()).idxmax()
    
    qty_col = None
    price_col = None
    for col in df_raw.columns:
        col_lower = col.lower()
        if 'qty' in col_lower or 'quant' in col_lower:
            qty_col = col
        elif 'price' in col_lower or 'rate' in col_lower or 'unit' in col_lower:
            price_col = col

    for idx, row in df_raw.iterrows():
        desc_val = str(row[desc_col]) if desc_col in df_raw.columns else ""
        if pd.isna(row[desc_col]) or desc_val.strip() == "" or "total" in desc_val.lower():
            continue
            
        row_no_raw = str(row.get("No", idx + 1)).strip()
        if row_no_raw.endswith(".0"):
            row_no = row_no_raw.split(".")[0]  
            is_sub_row = False                  
        elif "." in row_no_raw:
            row_no = row_no_raw                 
            is_sub_row = True                    
        else:
            row_no = row_no_raw
            is_sub_row = False
            
        p_idx = row_no.split(".")[0]
            
        qty_val = 1 if is_sub_row else 0
        if qty_col and is_sub_row:
            try: qty_val = int(float(str(row[qty_col]).replace(',', '')))
            except: pass
            
        price_val = 0.0
        if price_col and is_sub_row:
            try: price_val = float(re.sub(r'[^\d\.]', '', str(row[price_col])))
            except: pass
            
        part_no = "ARK-PART" if is_sub_row else ""
        for col in df_raw.columns:
            if col not in [desc_col, qty_col, price_col, "No"] and is_sub_row:
                val = str(row[col]).strip()
                if val and len(val) < 15 and val != "nan":
                    part_no = val
                    break

        structured_items.append({
            "No": row_no,
            "is_sub": is_sub_row,
            "parent_idx": p_idx,
            "Part Number/Model": part_no if is_sub_row else "",
            "Description": desc_val,
            "Qty": qty_val,
            "Unit Price": price_val,
            "Margin": 20.0 if is_sub_row else 0.0,
            "Total Price": 0.0
        })
    return structured_items

def parse_pdf_document(uploaded_file):
    structured_items = []
    try:
        reader = PdfReader(uploaded_file)
        idx = 1
        for page in reader.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split('\n'):
                line_str = line.strip()
                if not line_str or "total" in line_str.lower() or "description" in line_str.lower():
                    continue
                
                prices = re.findall(r'\d[\d,\.]*', line_str)
                price_val = 0.0
                qty_val = 1
                
                if len(prices) >= 1:
                    try: price_val = float(prices[-1].replace(',', ''))
                    except: pass
                if len(prices) >= 2:
                    try: qty_val = int(float(prices[-2].replace(',', '')))
                    except: pass
                
                words = line_str.split()
                part_no = words[0] if len(words) > 0 and len(words[0]) < 18 else "ARK-PART"
                desc_val = " ".join(words[1:-2]) if len(words) > 3 else line_str
                
                if len(desc_val) > 5:
                    structured_items.append({
                        "No": f"1.{idx}",
                        "is_sub": True,
                        "parent_idx": "1",
                        "Part Number/Model": part_no,
                        "Description": desc_val,
                        "Qty": qty_val if qty_val > 0 else 1,
                        "Unit Price": price_val if price_val > 0 else 100.0,
                        "Margin": 20.0,
                        "Total Price": 0.0
                    })
                    idx += 1
        if structured_items:
            structured_items.insert(0, {
                "No": "1", "is_sub": False, "parent_idx": "1", "Part Number/Model": "",
                "Description": "Imported PDF Bill of Materials Block", "Qty": 0, "Unit Price": 0.0, "Margin": 0.0, "Total Price": 0.0
            })
    except Exception as e:
        st.error(f"Failed handling PDF text context layout: {e}")
    return structured_items

if "user" not in st.session_state: st.session_state.user = None
if "default_logo_base64" not in st.session_state: st.session_state.default_logo_base64 = None

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
                    st.error("Invalid credentials supplied.")
                    
    with auth_tab2:
        reg_email = st.text_input("Corporate Email Address", key="reg_em").strip()
        reg_pwd = st.text_input("Create Security Password", type="password", key="reg_pw")
        reg_role = st.selectbox("Requested Core Functional Target Profile", ["Account Manager", "Account Director", "Top Management"])
        
        if st.button("Identity Activation Request"):
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
                    st.success("Registration success!")
                except sqlite3.IntegrityError:
                    st.error("Identity database conflict.")
                
        st.markdown("---")
        verify_email = st.text_input("Confirm Registered Email Destination Address", key="v_em").strip()
        verify_code = st.text_input("Enter 6-Digit OTP Secure Access Code", key="v_cd").strip()
        if st.button("Verify Credentials Clearance"):
            with get_db() as conn:
                user_rec = conn.execute("SELECT * FROM users WHERE LOWER(email)=LOWER(?) AND verification_code=?", (verify_email, verify_code)).fetchone()
                if user_rec:
                    conn.execute("UPDATE users SET is_verified=1 WHERE LOWER(email)=LOWER(?)", (verify_email,))
                    conn.commit()
                    st.success("Verification complete! Sign in above.")
                else:
                    st.error("Code rejected.")
    st.stop()

current_user = st.session_state.user
st.sidebar.markdown(f"**Authenticated Entity:** `{current_user['email']}`")
st.sidebar.markdown(f"**Functional Domain Clearance:** `{current_user['role']}`")
if st.sidebar.button("Logout Session Log"):
    st.session_state.user = None
    st.session_state.default_logo_base64 = None
    st.rerun()

# Navigation Router
nav_options = ["🏠 Dashboard Console", "➕ Build New Quotation Module"]
if current_user["role"] == "Account Director":
    nav_options.append("👥 Manage Assigned Account Teams")
elif current_user["role"] == "Admin":
    nav_options.append("👥 User Role Management")
page_selection = st.sidebar.radio("Navigation Directives", nav_options)

# ==========================================
# 🏠 DASHBOARD ENGINE
# ==========================================
if page_selection == "🏠 Dashboard Console":
    st.header(f"📊 Activity Metrics Control Dashboard - {current_user['role']}")
    quotes = []
    
    with get_db() as conn:
        if current_user["role"] == "Account Manager":
            quotes = conn.execute("SELECT * FROM quotations WHERE creator_id=?", (current_user["id"],)).fetchall()
        elif current_user["role"] == "Account Director":
            quotes = conn.execute("""
                SELECT q.* FROM quotations q 
                WHERE q.creator_id = ? 
                OR q.creator_id IN (SELECT manager_id FROM team_mappings WHERE director_id=? AND status='ACCEPTED')
            """, (current_user["id"], current_user["id"])).fetchall()
        elif current_user["role"] in ["Top Management", "Admin"]:
            quotes = conn.execute("SELECT q.*, u.email as creator_email FROM quotations q JOIN users u ON q.creator_id = u.id").fetchall()

    df_quotes = pd.DataFrame([dict(q) for q in quotes]) if quotes else pd.DataFrame()
    
    if not df_quotes.empty:
        submitted_df = df_quotes[df_quotes['status'] == 'SUBMITTED']
        won_df = df_quotes[df_quotes['status'] == 'WON']
        
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric("Total Quotes Processed", len(df_quotes))
        kpi2.metric("Gross Pending Pipeline", f"${submitted_df['grand_total'].sum():,.2f}")
        kpi3.metric("Actual Won Portfolio (PO Got)", f"${won_df['grand_total'].sum():,.2f}", delta=f"{len(won_df)} Projects")
        
        st.subheader("📈 Pipeline Conversion Analytics")
        spacer1, g_col1, g_col2, spacer2 = st.columns([1, 3, 3, 1])
        
        with g_col1:
            st.markdown("<p style='text-align: center; font-weight: bold;'>Total Quotation Count</p>", unsafe_allow_html=True)
            chart_count_data = pd.DataFrame({"Submitted (Pending)": [len(submitted_df)], "Won (PO Received)": [len(won_df)]})
            st.bar_chart(chart_count_data, color=["#00a8e8", "#2ecc71"])
            
        with g_col2:
            st.markdown("<p style='text-align: center; font-weight: bold;'>Cumulative Pipeline Value ($)</p>", unsafe_allow_html=True)
            chart_value_data = pd.DataFrame({"Submitted (Pending)": [submitted_df['grand_total'].sum()], "Won (PO Received)": [won_df['grand_total'].sum()]})
            st.bar_chart(chart_value_data, color=["#00a8e8", "#2ecc71"])

        st.subheader("🗃️ Active Ledger Workspace")
        for idx, row in df_quotes.iterrows():
            c_meta, c_act1, c_act2, c_act3 = st.columns([4, 1, 1, 1])
            with c_meta:
                st.markdown(f"**Quotation #:** `{row['po_number']}` | **Customer:** {row['customer_name']} | **Project:** {row['project_name']} | **Total:** {row['currency_unit']} {row['grand_total']:,.2f} | **Status:** `{row['status']}`")
            with c_act1:
                if st.button("👁️ View Details", key=f"view_q_{row['id']}"):
                    st.session_state[f"expanded_view_{row['id']}"] = not st.session_state.get(f"expanded_view_{row['id']}", False)
            with c_act2:
                if row['status'] != 'WON':
                    if st.button("🏆 Mark Won", key=f"won_q_{row['id']}"):
                        with get_db() as conn:
                            conn.execute("UPDATE quotations SET status='WON' WHERE id=?", (row['id'],))
                            conn.commit()
                        st.success("Project updated to WON!")
                        st.rerun()
                else:
                    st.write("✅ PO Confirmed")
            with c_act3:
                if st.button("🗑️ Delete", key=f"del_q_{row['id']}"):
                    with get_db() as conn:
                        conn.execute("DELETE FROM quotations WHERE id=?", (row['id'],))
                        conn.commit()
                    st.success("Quotation deleted.")
                    st.rerun()
            
            if st.session_state.get(f"expanded_view_{row['id']}", False):
                with st.container():
                    st.markdown("#### 📋 Comprehensive Itemization Breakdown Table")
                    
                    if st.button("🔄 Load Draft back to Sandbox Workspace", key=f"reload_draft_{row['id']}"):
                        try:
                            st.session_state.working_items = json.loads(row['items_json'])
                            st.success("Configuration loaded back to your working workspace! Navigate to 'Build New Quotation Module' tab.")
                        except Exception as e:
                            st.error(f"Failed reloading configuration: {e}")
                            
                    st.write(f"**Attention Party Contact:** {row['attention_person']} ({row['attention_email']})")
                    st.write(f"**Valid Frame:** {row['validity']} | **Payment Terms:** {row['payment_term']}")
                    
                    try:
                        items_data = json.loads(row['items_json'])
                        df_items = pd.DataFrame(items_data)
                        display_cols = ["No", "Part Number/Model", "Description", "Qty", "Unit Price", "Margin", "Total Price"]
                        for col in display_cols:
                            if col not in df_items.columns:
                                df_items[col] = ""
                        st.table(df_items[display_cols])
                    except Exception as err:
                        st.info("Item structure unmapped or empty data vectors found.")
            st.markdown("---")
    else:
        st.info("No quotation records discovered.")

# ==========================================
# 👥 USER ROLE MANAGEMENT (ADMIN ONLY)
# ==========================================
elif page_selection == "👥 User Role Management" and current_user["role"] == "Admin":
    st.header("👥 User Directory & Authorization Matrix")
    with get_db() as conn:
        all_users = conn.execute("SELECT id, email, role, is_verified FROM users WHERE role != 'Admin'").fetchall()
        
    if all_users:
        for u in all_users:
            uc1, uc2, uc3, uc4 = st.columns([3, 2, 2, 2])
            with uc1:
                st.markdown(f"**User:** `{u['email']}`")
            with uc2:
                new_role = st.selectbox("Assign System Role", ["Account Manager", "Account Director", "Top Management"], index=["Account Manager", "Account Director", "Top Management"].index(u["role"]), key=f"role_sel_{u['id']}")
            with uc3:
                is_ok = "Verified" if u["is_verified"] == 1 else "Pending Activation"
                st.markdown(f"**Status:** `{is_ok}`")
            with uc4:
                if st.button("💾 Apply Modifications", key=f"save_u_{u['id']}"):
                    with get_db() as conn:
                        conn.execute("UPDATE users SET role=?, is_verified=1 WHERE id=?", (new_role, u["id"]))
                        conn.commit()
                    st.success(f"Permissions updated for {u['email']}!")
                    st.rerun()
            st.markdown("---")
    else:
        st.info("No subordinate system user accounts found inside the platform.")

# ==========================================
# ➕ BUILD NEW QUOTATION MODULE
# ==========================================
elif page_selection == "➕ Build New Quotation Module":
    st.header("➕ Document Generation Sandbox")
    
    current_time_stamp = datetime.now()
    year_month_prefix = current_time_stamp.strftime("%Y%m")
    quotation_auto_gen = f"ARK-QT-{year_month_prefix}-{random.randint(100000, 999999)}"
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 💱 Currency Settings")
    currency_selection = st.sidebar.selectbox("Base Output Currency Mode", ["USD", "MMK"])
    exchange_rate = st.sidebar.number_input("Commercial Exchange Rate Value (1 USD to MMK)", min_value=1.0, value=3250.0, step=10.0)
    
    # SYSTEM CONFIGURATION UNIFIED TEXT DISPLAY TO MATCH REQUESTED GLOBALS
    currency_symbol = "$" if currency_selection == "USD" else "MMK "
    conversion_multiplier = exchange_rate if currency_selection == "MMK" else 1.0
    
    st.sidebar.markdown("### 📋 System Template")
    sample_df = pd.DataFrame({
        "No": ["1", "1.1", "1.2", "2"],
        "Part Number/Model": ["", "C9300-48TX-E", "STACK-M-50CM", ""],
        "Description": ["Cisco Core Router Stack Frame", "Catalyst 9300 48-port Data Only", "Cisco Catalyst 9300 Stack Cable 50CM", "ARK Professional Services Division"],
        "Qty": [0, 1, 1, 0],
        "Unit Price": [0.0, 4500.00, 250.00, 0.0]
    })
    csv_payload = sample_df.to_csv(index=False).encode('utf-8')
    st.sidebar.download_button(
        label="📥 Download Sample CSV Structure",
        data=csv_payload,
        file_name="ark_sample_template.csv",
        mime="text/csv"
    )
    
    st.sidebar.markdown("### 🖼️ Corporate Branding")
    uploaded_logo_file = st.sidebar.file_uploader("Upload Corporate Logo Image", type=["png", "jpg", "jpeg"])
    
    if uploaded_logo_file is not None:
        logo_bytes = uploaded_logo_file.getvalue()
        encoded_logo = base64.b64encode(logo_bytes).decode('utf-8')
        st.session_state.default_logo_base64 = f"data:{uploaded_logo_file.type};base64,{encoded_logo}"
        st.sidebar.success("Logo configuration registered as layout default!")
    
    meta_c1, meta_c2, meta_c3 = st.columns(3)
    with meta_c1:
        client_company = st.text_input("Client Corporate Entity Name", "Acme Enterprise Corp")
        attn_person = st.text_input("Attention Person Point of Contact", "John Doe")
        attn_email = st.text_input("Contact Email Destination", "johndoe@client.com")
        attn_phone = st.text_input("Contact Direct Phone Line", "+959xxxxxxxxx")
    with meta_c2:
        project_title = st.text_input("Internal Assignment / Project Title", "Network Infrastructure Overhaul")
        issue_date = st.date_input("Official Registration / Issue Date")
        validity_bound = st.text_input("Quotation Validity Frame", "30 Days from issuance")
    with meta_c3:
        lead_time_frame = st.text_input("Estimated Equipment Delivery Lead Time", "4-6 Weeks")
        payment_terms_desc = st.text_input("Agreed Commercial Payment Terms", "50% Advance, 50% Upon Delivery")
        terms_and_cond = st.text_area("Custom Legal Terms & Conditions Scope", "1. Standard ARK Warranty applies.\n2. Prices exclude deployment unless itemized below.")

    st.markdown("---")
    uploaded_doc = st.file_uploader("Ingest Document Vector (.xlsx, .xls, .csv, .pdf supported)", type=["xlsx", "xls", "csv", "pdf"])
    
    items_list = []
    if uploaded_doc:
        try:
            if uploaded_doc.name.endswith('.pdf'):
                items_list = parse_pdf_document(uploaded_doc)
            elif uploaded_doc.name.endswith('.csv'):
                items_list = parse_uploaded_document(pd.read_csv(uploaded_doc, dtype={"No": str}))
            else:
                items_list = parse_uploaded_document(pd.read_excel(uploaded_doc, dtype={"No": str}))
            st.success(f"Mapped {len(items_list)} items lines dynamically.")
        except Exception as e:
            st.error(f"Ingestion failure: {e}")

    if "working_items" not in st.session_state or uploaded_doc:
        if items_list:
            st.session_state.working_items = items_list
        else:
            st.session_state.working_items = [
                {"No": "1", "is_sub": False, "parent_idx": "1", "Part Number/Model": "", "Description": "Cisco Routing Core Platform Matrix", "Qty": 0, "Unit Price": 4500.0, "Margin": 0.0, "Total Price": 0.0},
                {"No": "1.1", "is_sub": True, "parent_idx": "1", "Part Number/Model": "C9300-48TX-E", "Description": "Catalyst 9300 48-port Data Only Network Essentials", "Qty": 1, "Unit Price": 4500.0, "Margin": 10.0
