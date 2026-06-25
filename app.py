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
                name TEXT DEFAULT '',
                designation TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                signature_b64 TEXT DEFAULT '',
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
                tax_type TEXT DEFAULT 'Commercial Tax',
                tax_rate REAL DEFAULT 5.0,
                tax_amount REAL DEFAULT 0.0,
                grand_total REAL,
                currency_unit TEXT,
                exchange_rate REAL,
                items_json TEXT,
                FOREIGN KEY(creator_id) REFERENCES users(id)
            )
        """)
        
        # Database schema patching helpers
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(users)")
        u_cols = [c[1] for c in cursor.fetchall()]
        for col, col_type in [("name", "TEXT DEFAULT ''"), ("designation", "TEXT DEFAULT ''"), ("phone", "TEXT DEFAULT ''"), ("signature_b64", "TEXT DEFAULT ''")]:
            if col not in u_cols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
                
        cursor.execute("PRAGMA table_info(quotations)")
        q_cols = [c[1] for c in cursor.fetchall()]
        if "tax_type" not in q_cols:
            conn.execute("ALTER TABLE quotations ADD COLUMN tax_type TEXT DEFAULT 'Commercial Tax'")
        if "tax_rate" not in q_cols:
            conn.execute("ALTER TABLE quotations ADD COLUMN tax_rate REAL DEFAULT 5.0")
        if "tax_amount" not in q_cols:
            conn.execute("ALTER TABLE quotations ADD COLUMN tax_amount REAL DEFAULT 0.0")

        admin_exists = conn.execute("SELECT 1 FROM users WHERE LOWER(email)='admin@arktechsolutions.net'").fetchone()
        if not admin_exists:
            pwd_hash = hashlib.sha256("ArkAdmin2026!".encode()).hexdigest()
            conn.execute("INSERT INTO users (email, password_hash, role, is_verified, name, designation) VALUES (?, ?, ?, 1, 'System Administrator', 'Infrastructure Root')",
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
            "Part Number": part_no if is_sub_row else "",
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
                        "Part Number": part_no,
                        "Description": desc_val,
                        "Qty": qty_val if qty_val > 0 else 1,
                        "Unit Price": price_val if price_val > 0 else 100.0,
                        "Margin": 20.0,
                        "Total Price": 0.0
                    })
                    idx += 1
        if structured_items:
            structured_items.insert(0, {
                "No": "1", "is_sub": False, "parent_idx": "1", "Part Number": "",
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
                        st.session_state.user = {
                            "id": res["id"], 
                            "email": res["email"], 
                            "role": res["role"],
                            "name": res["name"],
                            "designation": res["designation"],
                            "phone": res["phone"],
                            "signature_b64": res["signature_b64"]
                        }
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

# Sync current user metadata from DB
with get_db() as conn:
    db_u = conn.execute("SELECT * FROM users WHERE id=?", (st.session_state.user["id"],)).fetchone()
    if db_u:
        current_user = {
            "id": db_u["id"], "email": db_u["email"], "role": db_u["role"],
            "name": db_u["name"], "designation": db_u["designation"],
            "phone": db_u["phone"], "signature_b64": db_u["signature_b64"]
        }
        st.session_state.user = current_user

st.sidebar.markdown(f"**Authenticated Entity:** `{current_user['email']}`")
st.sidebar.markdown(f"**Functional Domain Clearance:** `{current_user['role']}`")
if st.sidebar.button("Logout Session Log"):
    st.session_state.user = None
    st.session_state.default_logo_base64 = None
    st.rerun()

# Navigation Router
nav_options = ["🏠 Dashboard Console", "➕ Build New Quotation Module", "👤 User Profile Management"]
if current_user["role"] == "Account Director":
    nav_options.append("👥 Manage Assigned Account Teams")
elif current_user["role"] == "Admin":
    nav_options.append("👥 User Role Management")
page_selection = st.sidebar.radio("Navigation Directives", nav_options)

# ==========================================
# 👤 USER PROFILE MANAGEMENT
# ==========================================
if page_selection == "👤 User Profile Management":
    st.header("👤 User Account Profile Configuration")
    st.write("Complete your corporate identity to populate quote documents automatically.")
    
    prof_name = st.text_input("Full Professional Name", current_user["name"])
    prof_desig = st.text_input("Corporate Designation / Title", current_user["designation"])
    prof_phone = st.text_input("Direct Phone/Mobile Contact Line", current_user["phone"])
    
    st.markdown("#### 🖋️ Corporate Authorization Signature")
    if current_user["signature_b64"]:
        st.markdown("**Active Signature File Detected:**")
        st.markdown(f'<img src="{current_user["signature_b64"]}" style="max-height: 80px; border: 1px solid #cbd5e0; padding: 4px; background: white;">', unsafe_allow_html=True)
    
    uploaded_sig = st.file_uploader("Upload New Signature Image File (PNG/JPG)", type=["png", "jpg", "jpeg"])
    
    if st.button("💾 Persist Profile Changes"):
        sig_payload = current_user["signature_b64"]
        if uploaded_sig is not None:
            sig_bytes = uploaded_sig.getvalue()
            encoded_sig = base64.b64encode(sig_bytes).decode('utf-8')
            sig_payload = f"data:{uploaded_sig.type};base64,{encoded_sig}"
            
        with get_db() as conn:
            conn.execute("""
                UPDATE users SET name=?, designation=?, phone=?, signature_b64=? WHERE id=?
            """, (prof_name, prof_desig, prof_phone, sig_payload, current_user["id"]))
            conn.commit()
        st.success("Profile records saved successfully.")
        st.rerun()

# ==========================================
# 🏠 DASHBOARD ENGINE
# ==========================================
elif page_selection == "🏠 Dashboard Console":
    st.header(f"📊 Activity Metrics Control Dashboard - {current_user['role']}")
    quotes = []
    
    with get_db() as conn:
        if current_user["role"] == "Account Manager":
            quotes = conn.execute("SELECT q.*, u.name as creator_name, u.designation as creator_desig, u.email as creator_email, u.phone as creator_phone, u.signature_b64 as creator_sig FROM quotations q JOIN users u ON q.creator_id = u.id WHERE q.creator_id=?", (current_user["id"],)).fetchall()
        elif current_user["role"] == "Account Director":
            quotes = conn.execute("""
                SELECT q.*, u.name as creator_name, u.designation as creator_desig, u.email as creator_email, u.phone as creator_phone, u.signature_b64 as creator_sig FROM quotations q 
                JOIN users u ON q.creator_id = u.id
                WHERE q.creator_id = ? 
                OR q.creator_id IN (SELECT manager_id FROM team_mappings WHERE director_id=? AND status='ACCEPTED')
            """, (current_user["id"], current_user["id"])).fetchall()
        elif current_user["role"] in ["Top Management", "Admin"]:
            quotes = conn.execute("SELECT q.*, u.name as creator_name, u.designation as creator_desig, u.email as creator_email, u.phone as creator_phone, u.signature_b64 as creator_sig FROM quotations q JOIN users u ON q.creator_id = u.id").fetchall()

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
                    st.write(f"**Account Manager Owner:** {row['creator_name']} ({row['creator_desig']})")
                    
                    try:
                        items_data = json.loads(row['items_json'])
                        df_items = pd.DataFrame(items_data)
                        display_cols = ["No", "Part Number", "Description", "Qty", "Unit Price", "Margin", "Total Price"]
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
    
    currency_symbol = "USD " if currency_selection == "USD" else "MMK "
    conversion_multiplier = exchange_rate if currency_selection == "MMK" else 1.0
    
    st.sidebar.markdown("### 📋 System Template")
    sample_df = pd.DataFrame({
        "No": ["1", "1.1", "1.2", "2"],
        "Part Number": ["", "C9300-48TX-E", "STACK-M-50CM", ""],
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
        terms_and_cond = st.text_area("Custom Legal Terms & Conditions Scope", "1. Standard Vendor Warranty applies.\n2. Prices exclude deployment unless itemized below.")

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
                {"No": "1", "is_sub": False, "parent_idx": "1", "Part Number": "", "Description": "Cisco Routing Core Platform Matrix", "Qty": 0, "Unit Price": 4500.0, "Margin": 0.0, "Total Price": 0.0},
                {"No": "1.1", "is_sub": True, "parent_idx": "1", "Part Number": "C9300-48TX-E", "Description": "Catalyst 9300 48-port Data Only Network Essentials", "Qty": 1, "Unit Price": 4500.0, "Margin": 10.0, "Total Price": 0.0},
                {"No": "1.2", "is_sub": True, "parent_idx": "1", "Part Number": "STACK-M-50CM", "Description": "Cisco Catalyst 9300 Stack Cable 50CM", "Qty": 1, "Unit Price": 250.0, "Margin": 10.0, "Total Price": 0.0}
            ]

    st.markdown("#### ⚡ Global Commercial Adjustments")
    m_col1, m_col2 = st.columns([2, 3])
    with m_col1:
        global_margin_input = st.number_input("Set Target Uniform Margin (%)", min_value=0.0, max_value=99.0, value=10.0, step=1.0)
    with m_col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("⚡ Apply Margin to All Rows"):
            for item in st.session_state.working_items:
                if item.get("is_sub", False):
                    item["Margin"] = float(global_margin_input)
            st.success(f"Applied a uniform {global_margin_input}% margin setting across all sub-portfolio entries.")
            st.rerun()

    # --- LIVE CALCULATION PIPELINE ---
    for item in st.session_state.working_items:
        if not item.get("is_sub", False):
            item["Part Number"] = ""
            item["Qty"] = None
            item["Unit Price"] = None
            item["Margin"] = None
            item["Total Price"] = None
        else:
            qty = float(item.get("Qty") or 0)
            u_p = float(item.get("Unit Price") or 0.0)
            m_pct = float(item.get("Margin") or 0.0) / 100.0
            final_unit_price = u_p / (1 - m_pct) if m_pct < 1.0 else u_p
            item["Calculated Unit Price Base"] = round(final_unit_price, 2)
            item["Total Price"] = round((final_unit_price * qty) * conversion_multiplier, 2)

    blueprint_columns = ["No", "Part Number", "Description", "Qty", "Unit Price", "Margin", "Total Price"]
    
    if st.session_state.working_items:
        df_display = pd.DataFrame(st.session_state.working_items)
        for col in blueprint_columns:
            if col not in df_display.columns:
                df_display[col] = None
    else:
        df_display = pd.DataFrame(columns=blueprint_columns)

    edited_df = st.data_editor(
        df_display[blueprint_columns],
        num_rows="dynamic",
        width="stretch",
        key="quotation_data_grid",
        column_config={
            "No": st.column_config.TextColumn("No", width="small"),
            "Part Number": st.column_config.TextColumn("Part Number", width="medium"),
            "Description": st.column_config.TextColumn("Item Description Specifications", width="large"),
            "Qty": st.column_config.NumberColumn("Qty", min_value=0, width="small"),
            "Unit Price": st.column_config.NumberColumn("Unit Price (Base)", format="$%.2f", width="medium"),
            "Margin": st.column_config.NumberColumn("Margin (%)", width="small"),
            "Total Price": st.column_config.NumberColumn(f"Total Price ({currency_selection})", format="%.2f", disabled=True, width="medium")
        }
    )

    if not edited_df.equals(df_display[blueprint_columns]):
        updated_records = []
        for idx, row in edited_df.iterrows():
            orig_meta = st.session_state.working_items[idx] if idx < len(st.session_state.working_items) else {"is_sub": "." in str(row["No"]), "parent_idx": "1"}
            row_no = str(row["No"] or "")
            is_sub_row = "." in row_no
            p_idx = row_no.split(".")[0] if is_sub_row else row_no
            
            try: ui_margin = float(row.get("Margin") or 0.0) if not pd.isna(row.get("Margin")) else 0.0
            except: ui_margin = float(global_margin_input) if is_sub_row else 0.0
                
            try: old_margin = float(orig_meta.get("Margin") or 0.0) if orig_meta.get("Margin") is not None else 0.0
            except: old_margin = 0.0

            target_margin = ui_margin
            if is_sub_row:
                parent_row_matches = [r for _, r in edited_df.iterrows() if str(r.get("No")) == p_idx]
                if parent_row_matches:
                    p_row = parent_row_matches[0]
                    try: p_ui_margin = float(p_row.get("Margin") or 0.0) if not pd.isna(p_row.get("Margin")) else 0.0
                    except: p_ui_margin = 0.0
                        
                    p_orig_matches = [i for i in st.session_state.working_items if str(i.get("No")) == p_idx]
                    p_old_margin = float(p_orig_matches[0].get("Margin", 0.0)) if (p_orig_matches and p_orig_matches[0].get("Margin") is not None) else 0.0
                    
                    if p_ui_margin != p_old_margin and ui_margin == old_margin:
                        target_margin = p_ui_margin

            updated_records.append({
                "No": row_no, 
                "is_sub": is_sub_row, 
                "parent_idx": p_idx,
                "Part Number": "" if not is_sub_row else (row["Part Number"] or ""),
                "Description": row["Description"] or "Structural Node",
                "Qty": 0 if not is_sub_row else int(row.get("Qty") or 0),
                "Unit Price": 0.0 if not is_sub_row else float(row.get("Unit Price") or 0.0),
                "Margin": 0.0 if not is_sub_row else float(target_margin), 
                "Total Price": 0.0
            })
        st.session_state.working_items = updated_records
        st.rerun()

    btn_c1, btn_c2 = st.columns(2)
    with btn_c1:
        if st.button("➕ Add Main Row Divider"):
            main_rows = []
            for item in st.session_state.working_items:
                if not item.get("is_sub", False):
                    try: main_rows.append(int(float(item["No"] or 0)))
                    except: pass
            next_no = str(max(main_rows) + 1 if main_rows else 1)
            st.session_state.working_items.append({
                "No": next_no, "is_sub": False, "parent_idx": next_no, 
                "Part Number": "", "Description": "NEW STRUCTURAL BLOCK HEADER", 
                "Qty": None, "Unit Price": None, "Margin": None, "Total Price": None
            })
            st.rerun()
    with btn_c2:
        if st.button("🌿 Add Sub-Row Element"):
            if st.session_state.working_items:
                last_item = st.session_state.working_items[-1]
                p_idx = last_item.get("parent_idx", "1")
                siblings = [item for item in st.session_state.working_items if item.get("is_sub", False) and item.get("parent_idx") == p_idx]
                st.session_state.working_items.append({
                    "No": f"{p_idx}.{len(siblings) + 1}", "is_sub": True, "parent_idx": p_idx, 
                    "Part Number": "NEW-ITEM", "Description": "Nested equipment asset line specifications", 
                    "Qty": 1, "Unit Price": 0.0, "Margin": float(global_margin_input), "Total Price": 0.0
                })
                st.rerun()

    st.markdown("---")
    srv_c1, srv_c2 = st.columns(2)
    with srv_c1:
        ps_desc = st.text_area("Professional Service Description", "ARK Implementation Support")
        ps_price_usd = st.number_input("Professional Service (USD)", min_value=0.0, value=0.0)
        ps_tax_exempt = st.checkbox("Exempt Professional Services from Tax", value=False)
    with srv_c2:
        ms_desc = st.text_area("Maintenance Service Description", "ARK Premium 24/7 Monitoring")
        ms_price_usd = st.number_input("Maintenance Service (USD)", min_value=0.0, value=0.0)
        ms_tax_exempt = st.checkbox("Exempt Maintenance Services from Tax", value=False)

    # --- SIDEBAR TAX CONFIGURATION SELECTION MAPPING ---
    st.sidebar.markdown("### 🏛️ Tax Strategies")
    enable_commercial_tax = st.sidebar.checkbox("Apply Commercial Tax", value=True)
    commercial_tax_pct = 5.0
    if enable_commercial_tax:
        commercial_tax_pct = st.sidebar.number_input("Commercial Tax Factor (%)", min_value=0.0, value=5.0, key="comm_tax_val")
        
    enable_wht = st.sidebar.checkbox("Apply Withholding Tax (WHT)", value=False)
    wht_pct = 2.0
    if enable_wht:
        wht_pct = st.sidebar.number_input("Withholding Tax (WHT) Factor (%)", min_value=0.0, value=2.0, key="wht_tax_val")

    # Calculate subtotal using totals already containing conversion values
    item_subtotal_rendered = sum([float(item.get("Total Price") or 0.0) for item in st.session_state.working_items if item.get("Total Price") is not None])
    global_subtotal_calculated = item_subtotal_rendered + ((ps_price_usd + ms_price_usd) * conversion_multiplier)
    
    global_discount_input = st.sidebar.number_input(f"Discount ({currency_selection})", min_value=0.0, value=0.0)
    subtotal_after_disc = max(0.0, global_subtotal_calculated - global_discount_input)
    
    # --- DYNAMIC TAX EXEMPTION CALCULATION ENGINE ---
    ps_total = ps_price_usd * conversion_multiplier
    ms_total = ms_price_usd * conversion_multiplier
    
    taxable_base = item_subtotal_rendered
    if not ps_tax_exempt:
        taxable_base += ps_total
    if not ms_tax_exempt:
        taxable_base += ms_total
        
    if global_subtotal_calculated > 0:
        discount_factor = subtotal_after_disc / global_subtotal_calculated
        taxable_subtotal_after_disc = taxable_base * discount_factor
    else:
        taxable_subtotal_after_disc = 0.0
        
    comm_tax_amount = (taxable_subtotal_after_disc * (commercial_tax_pct / 100.0)) if enable_commercial_tax else 0.0
    wht_tax_amount = (taxable_subtotal_after_disc * (wht_pct / 100.0)) if enable_wht else 0.0
    
    # Grand total logic handles both adjustments simultaneously
    calculated_grand_total = subtotal_after_disc + comm_tax_amount - wht_tax_amount
    
    # Telemetry data mapping strings for database archival 
    active_strategies = []
    if enable_commercial_tax: active_strategies.append(f"Commercial Tax ({commercial_tax_pct}%)")
    if enable_wht: active_strategies.append(f"WHT ({wht_pct}%)")
    tax_type_selection = " + ".join(active_strategies) if active_strategies else "None"
    global_tax_pct = commercial_tax_pct if enable_commercial_tax else wht_pct
    calculated_tax = comm_tax_amount + wht_tax_amount
    
    st.sidebar.markdown(f"**Gross Subtotal:** {currency_symbol}{global_subtotal_calculated:,.2f}")
    if enable_commercial_tax:
        st.sidebar.markdown(f"**CT:** +{currency_symbol}{comm_tax_amount:,.2f}")
    if enable_wht:
        st.sidebar.markdown(f"**Withholding Tax (WHT) ({wht_pct}%):** -{currency_symbol}{wht_tax_amount:,.2f}")
    st.sidebar.markdown(f"### **Grand Total:** {currency_symbol}{calculated_grand_total:,.2f}")

    action_c1, action_c2 = st.columns(2)
    if action_c1.button("💾 Persist Document Configuration (Save Draft)"):
        with get_db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO quotations (po_number, creator_id, customer_name, project_name, attention_person, attention_email, attention_phone, status, issue_date, validity, lead_time, payment_term, terms_conditions, subtotal, discount, tax_type, tax_rate, tax_amount, grand_total, currency_unit, exchange_rate, items_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (quotation_auto_gen, current_user["id"], client_company, project_title, attn_person, attn_email, attn_phone, str(issue_date), validity_bound, lead_time_frame, payment_terms_desc, terms_and_cond, global_subtotal_calculated, global_discount_input, tax_type_selection, global_tax_pct, calculated_tax, calculated_grand_total, currency_selection, exchange_rate, json.dumps(st.session_state.working_items)))
            conn.commit()
        st.success("Draft compiled and archived.")

    if action_c2.button("🖨️ Compile Official Corporate PDF Engine Asset"):
        if st.session_state.default_logo_base64 is not None:
            logo_html = f'<img src="{st.session_state.default_logo_base64}" style="max-height: 65px; max-width: 220px; object-fit: contain;">'
        else:
            logo_html = '<h2 style="color:#00a8e8; margin:0; font-family:\'Helvetica Neue\',Arial; font-size: 18pt; font-weight: normal; letter-spacing: 0.5px;">ARK PREMIUM SOLUTION</h2>'

        max_main_no = max([int(float(item.get("parent_idx", 0))) for item in st.session_state.working_items if str(item.get("parent_idx", "")).isdigit()] + [1])

        # --- HTML ROW POPULATION BUILDER ---
        table_rows_html = ""
        for item in st.session_state.working_items:
            is_sub = item.get("is_sub", False)
            
            if not is_sub:
                table_rows_html += f'''
                <tr style="background-color: #f8fafc; font-weight: 600; border-top: 1px solid #e2e8f0;">
                    <td style="text-align: center; color: #1e293b; padding: 8px;">{item.get("No", "")}</td>
                    <td colspan="5" style="padding-left: 10px; color: #1e293b; font-size: 8.5pt; padding: 8px;">
                        {item.get("Description", "Main Section")}
                    </td>
                </tr>
                '''
            else:
                raw_base_unit = float(item.get("Calculated Unit Price Base") or 0.0)
                unit_p = raw_base_unit * conversion_multiplier
                total_p = (raw_base_unit * float(item.get("Qty") or 0)) * conversion_multiplier
                
                # --- FOC LOGIC START ---
                if total_p <= 0:
                    display_total = "FOC"
                    display_unit = "FOC"
                else:
                    display_total = f"{currency_symbol}{total_p:,.2f}"
                    display_unit = f"{currency_symbol}{unit_p:,.2f}"
                # --- FOC LOGIC END ---

                table_rows_html += f'''
                <tr style="background-color: #ffffff;">
                    <td style="text-align: center; color: #64748b; padding: 8px;">{item.get("No", "")}</td>
                    <td style="color: #334155; font-family: monospace; word-break: break-all; padding: 8px;">{item.get("Part Number", "")}</td>
                    <td style="padding-left: 10px; color: #334155; font-style: italic; word-break: break-word; padding: 8px;">{item.get("Description", "")}</td>
                    <td style="text-align: center; color: #334155; padding: 8px;">{item.get("Qty", 1)}</td>
                    <td style="text-align: right; color: #334155; white-space: nowrap; padding: 8px;">{display_unit}</td>
                    <td style="text-align: right; font-weight: 600; color: #1e293b; white-space: nowrap; padding: 8px;">{display_total}</td>
                </tr>
                '''

        current_service_index = max_main_no
        if ps_price_usd > 0:
            current_service_index += 1
            ps_total = ps_price_usd * conversion_multiplier
            # Block Header for Professional Services
            table_rows_html += f'''
            <tr style="background-color: #f8fafc; font-weight: 600; border-top: 1px solid #e2e8f0;">
                <td style="text-align: center; color: #1e293b; padding: 8px;">{current_service_index}</td>
                <td colspan="5" style="padding-left: 10px; color: #1e293b; font-size: 8.5pt; padding: 8px;">
                    ARK Professional Services
                </td>
            </tr>
            <tr style="background-color: #ffffff;">
                <td style="text-align: center; color: #64748b; padding: 8px;">{current_service_index}.1</td>
                <td style="color: #334155; font-family: monospace; word-break: break-all; padding: 8px;">SRV-ARK-PS</td>
                <td style="white-space: pre-line; padding-left: 10px; color: #334155; padding: 8px; font-style: italic;">{ps_desc}</td>
                <td style="text-align: center; color: #334155; padding: 8px;">1</td>
                <td style="text-align: right; color: #334155; white-space: nowrap; padding: 8px;">{currency_symbol}{ps_total:,.2f}</td>
                <td style="text-align: right; font-weight: 600; color: #1e293b; white-space: nowrap; padding: 8px;">{currency_symbol}{ps_total:,.2f}</td>
            </tr>
            '''
        if ms_price_usd > 0:
            current_service_index += 1
            ms_total = ms_price_usd * conversion_multiplier
            # Block Header for Maintenance Services
            table_rows_html += f'''
            <tr style="background-color: #f8fafc; font-weight: 600; border-top: 1px solid #e2e8f0;">
                <td style="text-align: center; color: #1e293b; padding: 8px;">{current_service_index}</td>
                <td colspan="5" style="padding-left: 10px; color: #1e293b; font-size: 8.5pt; padding: 8px;">
                    ARK Maintenance Service
                </td>
            </tr>
            <tr style="background-color: #ffffff;">
                <td style="text-align: center; color: #64748b; padding: 8px;">{current_service_index}.1</td>
                <td style="color: #334155; font-family: monospace; word-break: break-all; padding: 8px;">SRV-ARK-MS</td>
                <td style="white-space: pre-line; padding-left: 10px; color: #334155; padding: 8px; font-style: italic;">{ms_desc}</td>
                <td style="text-align: center; color: #334155; padding: 8px;">1</td>
                <td style="text-align: right; color: #334155; white-space: nowrap; padding: 8px;">{currency_symbol}{ms_total:,.2f}</td>
                <td style="text-align: right; font-weight: 600; color: #1e293b; white-space: nowrap; padding: 8px;">{currency_symbol}{ms_total:,.2f}</td>
            </tr>
            '''

        discount_row_markup = ""
        if global_discount_input > 0:
            discount_row_markup = f'''
            <tr>
                <td style="color: #475569; padding: 4px 0;">Discount Applied:</td>
                <td style="text-align: right; font-weight: 600; color: #b91c1c; white-space: nowrap; padding: 4px 0;">-{currency_symbol}{global_discount_input:,.2f}</td>
            </tr>
            '''

        tax_row_markup = ""
        if enable_commercial_tax:
            tax_row_markup += f'''
            <tr>
                <td style="color: #475569; padding: 4px 0;">CT:</td>
                <td style="text-align: right; font-weight: 600; color: #475569; white-space: nowrap; padding: 4px 0;">+{currency_symbol}{comm_tax_amount:,.2f}</td>
            </tr>
            '''
        if enable_wht:
            tax_row_markup += f'''
            <tr>
                <td style="color: #475569; padding: 4px 0;">Withholding Tax WHT ({wht_pct}%):</td>
                <td style="text-align: right; font-weight: 600; color: #b91c1c; white-space: nowrap; padding: 4px 0;">-{currency_symbol}{wht_tax_amount:,.2f}</td>
            </tr>
            '''

        sig_img_markup = ""
        if current_user["signature_b64"]:
            sig_img_markup = f'<img src="{current_user["signature_b64"]}" style="max-height: 55px; margin-top: 5px; margin-bottom: 2px; display: block;">'
        else:
            sig_img_markup = '<div style="height: 45px; margin-top: 5px; color: #cbd5e1; font-style: italic; font-size: 8pt;">Signature Pending</div>'

        html_document = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                @page {{
                    size: A4;
                    margin: 15mm 15mm 20mm 15mm;
                    @bottom-right {{
                        content: "Page " counter(page) " of " counter(pages);
                        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                        font-size: 8pt;
                        color: #64748b;
                    }}
                }}
                @page :first {{
                    margin-top: 5mm;
                }}
                body {{
                    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                    color: #1e293b;
                    font-size: 9pt;
                    line-height: 1.6;
                    width: 100%;
                }}
                .header-container {{ 
                    text-align: center; 
                    max-height: 1.6in; 
                    overflow: fixed; 
                    margin-bottom: 10px;
                }}    
                .header-logo {{
                    margin-bottom: 8px;
                }}
                .header-address {{
                    font-size: 8pt;
                    color: #475569;
                    line-height: 1.4;
                }}
                .company-group-title {{
                    font-weight: bold;
                    color: #00a8e8;
                    font-size: 11pt;
                    letter-spacing: 0.3px;
                    margin-bottom: 2px;
                }}
                .divider {{ border-bottom: 2px solid #00a8e8; margin-top: 5px; margin-bottom: 15px; }}
                .doc-title {{ font-size: 18pt; font-weight: normal; color: #0f172a; margin: 0; text-align: left; }}
                
                .meta-table {{ width: 100%; margin-bottom: 15px; table-layout: fixed; border-collapse: collapse; }}
                .meta-table td {{ vertical-align: top; border: none; padding: 0; width: 50%; }}
                
                .card-box {{ background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px; padding: 10px; height: 110px; min-height: 110px; box-sizing: border-box; margin-right: 5px; font-size: 8.5pt; }}
                .card-box-right {{ background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px; padding: 10px; height: 110px; min-height: 110px; box-sizing: border-box; margin-left: 5px; font-size: 8.5pt; }}
                .card-title {{ font-size: 7.5pt; font-weight: bold; color: #64748b; text-transform: uppercase; margin-bottom: 4px; letter-spacing: 0.5px; }}
                
                .clear {{ clear: both; height: 5px; }}
                
                .data-table {{ width: 100%; max-width: 100%; border-collapse: collapse; margin-top: 10px; margin-bottom: 15px; clear: both; table-layout: auto; }}
                .data-table th {{ background-color: #1e293b; color: white; font-weight: 500; text-transform: uppercase; font-size: 8pt; padding: 8px; text-align: left; letter-spacing: 0.3px; }}
                .data-table td {{ font-size: 8.5pt; border-bottom: 1px solid #f1f5f9; }}
                
                .totals-box {{ float: right; width: 40%; margin-top: 5px; page-break-inside: avoid; }}
                .totals-table {{ width: 100%; border-collapse: collapse; font-size: 8.5pt; }}
                .grand-total-tr {{ background-color: #00a8e8; color: white; font-weight: bold; font-size: 10pt; }}
                .grand-total-tr td {{ padding: 8px; color: white !important; }}
                
                .footer-terms {{ margin-top: 25px; font-size: 8pt; color: #475569; border-top: 1px solid #e2e8f0; padding-top: 10px; page-break-inside: avoid; clear: both; line-height: 1.4; }}
                .signatory-container {{ margin-top: 25px; width: 100%; page-break-inside: avoid; clear: both; }}
                .signatory-box {{ width: 240px; float: right; text-align: left; font-size: 8.5pt; color: #1e293b; }}
            </style>
        </head>
        <body>
            <div class="header-container">
                <div class="header-logo">{logo_html}</div>
                <div class="header-address">
                    <div class="company-group-title">ARK Premium Solution Limited</div>
                    <strong>ARK Corporate Office :</strong> 18th floor, Times City(office tower-2), Kamayut, Yangon, Myanmar.<br>
                    <strong>ARK Headquarters Office :</strong> 91, Shwe Taung Kyar 1st Street, Golden Valley 1, Bahan, Yangon, Myanmar.<br>
                    <strong>ARK Thailand Office :</strong> 1, Soi Ramkhamhaeng 118 Yaek 33-3, Saphan Sung 10240, Bangkok, Thailand.<br>
                    <strong>website:</strong> www.arktechsolutions.net
                </div>
            </div>

            <div class="divider"></div>
            <h2 class="doc-title">Quotation</h2>
            <br>

            <table class="meta-table">
                <tr>
                    <td>
                        <div class="card-box">
                            <div class="card-title">Prepared For</div>
                            <strong style="font-size: 9.5pt; color: #0f172a; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{client_company}</strong>
                            Attn: {attn_person}<br>
                            Email: {attn_email}<br>
                            Phone: {attn_phone}
                        </div>
                    </td>
                    <td>
                        <div class="card-box-right">
                            <div class="card-title">Quotation References</div>
                            <strong>Ref:</strong> {quotation_auto_gen}<br>
                            <strong>Project:</strong> {project_title}<br>
                            <strong>Date:</strong> {issue_date.strftime('%Y-%m-%d')}<br>
                            <strong>Validity:</strong> {validity_bound}
                        </div>
                    </td>
                </tr>
            </table>
            
            <div class="clear"></div>

            <table class="data-table">
                <thead>
                    <tr>
                        <th style="width: 6%; text-align: center;">No</th>
                        <th style="width: 22%;">Part Number</th>
                        <th style="width: 42%;">Item Description Specifications</th>
                        <th style="width: 5%; text-align: center;">Qty</th>
                        <th style="width: 12%; text-align: right;">Unit Price</th>
                        <th style="width: 13%; text-align: right;">Total Price</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows_html}
                </tbody>
            </table>

            <div class="totals-box">
                <table class="totals-table">
                    <tr>
                        <td style="color: #475569; padding: 4px 0;">Gross Subtotal:</td>
                        <td style="text-align: right; font-weight: 600; white-space: nowrap; padding: 4px 0;">{currency_symbol}{global_subtotal_calculated:,.2f}</td>
                    </tr>
                    {discount_row_markup}
                    {tax_row_markup}
                    <tr class="grand-total-tr">
                        <td>Grand Total:</td>
                        <td style="text-align: right; white-space: nowrap;">{currency_symbol}{calculated_grand_total:,.2f}</td>
                    </tr>
                </table>
            </div>
            <div class="clear"></div>

            <div class="footer-terms">
                <strong>Commercial Logistics Terms & Governance Conditions:</strong><br>
                1. Delivery Lead-Time Windows: Equipment delivery windows are anticipated at approximately <strong>{lead_time_frame}</strong> following official project sign-off matrix rules.<br>
                2. Explicit Milestone Commitments: All relative monetary settlement routes must maintain strict compliance with: <strong>{payment_terms_desc}</strong>.<br>
                3. Additional Execution Scope and Framework Matrix Parameters: {terms_and_cond.replace('\n', '<br>')}
            </div>

            <div class="signatory-container">
                <div class="signatory-box">
                    <div style="border-bottom: 1px solid #cbd5e1; padding-bottom: 4px;">
                        <span style="font-size: 7.5pt; font-weight: bold; color: #64748b; text-transform: uppercase; display: block;">Issued & Authorized By:</span>
                        {sig_img_markup}
                    </div>
                    <div style="margin-top: 6px; font-weight: bold; color: #0f172a; font-size: 9.5pt;">{current_user["name"] or "Authorized Signatory"}</div>
                    <div style="color: #475569; font-size: 8.5pt; font-weight: 500; margin-top: 2px;">{current_user["designation"] or "Account Operations Manager"}</div>
                    <div style="color: #64748b; font-size: 8pt; margin-top: 4px; line-height: 1.4;">
                        Email: {current_user["email"]}<br>
                        Phone: {current_user["phone"] or "N/A"}
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        
        pdf_filename = f"ARK_Quotation_{quotation_auto_gen}.pdf"
        try:
            HTML(string=html_document).write_pdf(pdf_filename)
            with open(pdf_filename, "rb") as pdf_file:
                pdf_payload = pdf_file.read()
                
            st.sidebar.markdown("---")
            st.sidebar.success("🎉 Enterprise compilation structural integrity cleared!")
            st.sidebar.download_button(
                label="📥 Download Finished Quotation PDF Document",
                data=pdf_payload,
                file_name=pdf_filename,
                mime="application/pdf"
            )
            
            with get_db() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO quotations 
                    (po_number, creator_id, customer_name, project_name, attention_person, attention_email, attention_phone, status, issue_date, validity, lead_time, payment_term, terms_conditions, subtotal, discount, tax_type, tax_rate, tax_amount, grand_total, currency_unit, exchange_rate, items_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'SUBMITTED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (quotation_auto_gen, current_user["id"], client_company, project_title, attn_person, attn_email, attn_phone, str(issue_date), validity_bound, lead_time_frame, payment_terms_desc, terms_and_cond, global_subtotal_calculated, global_discount_input, tax_type_selection, global_tax_pct, calculated_tax, calculated_grand_total, currency_selection, exchange_rate, json.dumps(st.session_state.working_items)))
                conn.commit()
                
        except Exception as pdf_err:
            st.error(f"Engine compilation fault isolated: {pdf_err}")
