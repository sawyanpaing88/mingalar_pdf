# app.py
import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import random
import re
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
            "is_sub": False,
            "parent_idx": "",
            "Part Number/Model": part_no,
            "Description": desc_val,
            "Qty": qty_val,
            "Unit Price": price_val,
            "Margin": 20.0,
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
                        "No": str(idx),
                        "is_sub": False,
                        "parent_idx": "",
                        "Part Number/Model": part_no,
                        "Description": desc_val,
                        "Qty": qty_val if qty_val > 0 else 1,
                        "Unit Price": price_val if price_val > 0 else 100.0,
                        "Margin": 20.0,
                        "Total Price": 0.0
                    })
                    idx += 1
    except Exception as e:
        st.error(f"Failed handling PDF text context layout: {e}")
    return structured_items


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
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric("Total Quotations Processed", len(df_quotes))
        kpi2.metric("Total Revenue Pipeline", f"${df_quotes['grand_total'].sum():,.2f}")
        kpi3.metric("Pending/Submitted Confirmations", len(df_quotes[df_quotes['status'] == 'SUBMITTED']))
        
        st.subheader("🗃️ Active Ledger Workspace")
        
        for idx, row in df_quotes.iterrows():
            c_meta, c_act = st.columns([5, 1])
            with c_meta:
                st.markdown(f"**Quotation #:** `{row['po_number']}` | **Customer:** {row['customer_name']} | **Project:** {row['project_name']} | **Total:** {row['currency_unit']} {row['grand_total']:,.2f} | **Status:** `{row['status']}`")
            with c_act:
                if current_user["role"] == "Account Manager" or current_user["role"] == "Admin" or current_user["role"] == "Account Director":
                    if st.button("🗑️ Delete", key=f"del_q_{row['id']}"):
                        with get_db() as conn:
                            conn.execute("DELETE FROM quotations WHERE id=?", (row['id'],))
                            conn.commit()
                        st.success(f"Quotation {row['po_number']} removed successfully.")
                        st.rerun()
            st.markdown("---")
    else:
        st.info("No corporate quotation ledgers are currently mapped to this profile scope.")

# ==========================================
# 👥 ACCOUNT DIRECTOR TEAM MANAGEMENT HUB
# ==========================================
elif page_selection == "👥 Manage Assigned Account Teams" and current_user["role"] == "Account Director":
    st.header("👥 Account Team Allocation Panel")
    
    with get_db() as conn:
        all_managers = conn.execute("SELECT id, email FROM users WHERE role='Account Manager'").fetchall()
        current_relations = conn.execute("""
            SELECT tm.*, u.email as mgr_email FROM team_mappings tm 
            JOIN users u ON tm.manager_id = u.id 
            WHERE tm.director_id=?
        """, (current_user["id"],)).fetchall()
        
    st.subheader("Request Team Association Link")
    target_mgr = st.selectbox("Choose Account Manager to link", [m["email"] for m in all_managers] if all_managers else ["None"])
    if st.button("Send Team Link Invitation") and all_managers:
        with get_db() as conn:
            mgr_id = conn.execute("SELECT id FROM users WHERE LOWER(email)=LOWER(?)", (target_mgr,)).fetchone()["id"]
            dup = conn.execute("SELECT 1 FROM team_mappings WHERE director_id=? AND manager_id=?", (current_user["id"], mgr_id)).fetchone()
            if not dup:
                conn.execute("INSERT INTO team_mappings (director_id, manager_id, status) VALUES (?, ?, 'PENDING')", (current_user["id"], mgr_id))
                conn.commit()
                st.success("Association link sent to Manager's dashboard.")
                st.rerun()
                
    st.subheader("Current Grouping Status Ledger")
    for rel in current_relations:
        st.write(f"▪️ `{rel['mgr_email']}` - Status: **{rel['status']}**")

# ==========================================
# 📥 ACCOUNT MANAGER TEAM INBOX ALERTS
# ==========================================
if current_user["role"] == "Account Manager":
    with get_db() as conn:
        pending_invites = conn.execute("""
            SELECT tm.*, u.email as dir_email FROM team_mappings tm 
            JOIN users u ON tm.director_id = u.id 
            WHERE tm.manager_id=? AND tm.status='PENDING'
        """, (current_user["id"],)).fetchall()
        
    if pending_invites:
        st.sidebar.markdown("### 🔔 Inbound Hierarchy Request")
        for invite in pending_invites:
            st.sidebar.write(f"Director `{invite['dir_email']}` requests pipeline view mapping.")
            inv_col1, inv_col2 = st.sidebar.columns(2)
            if inv_col1.button("Accept", key=f"acc_{invite['id']}"):
                with get_db() as conn:
                    conn.execute("UPDATE team_mappings SET status='ACCEPTED' WHERE id=?", (invite['id'],))
                    conn.commit()
                st.rerun()
            if inv_col2.button("Decline", key=f"dec_{invite['id']}"):
                with get_db() as conn:
                    conn.execute("DELETE FROM team_mappings WHERE id=?", (invite['id'],))
                    conn.commit()
                st.rerun()

# ==========================================
# ➕ BUILD NEW QUOTATION MODULE
# ==========================================
if page_selection == "➕ Build New Quotation Module":
    st.header("➕ Document Generation Sandbox")
    
    quotation_auto_gen = f"ARK-QT-{random.randint(100000, 999999)}"
    
    # --- CURRENCY MATRIX SIDEBAR ROUTINES ---
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 💱 Currency Exchange Settings")
    currency_selection = st.sidebar.selectbox("Base Output Currency Mode", ["USD", "MMK"])
    exchange_rate = st.sidebar.number_input("Commercial Exchange Rate Value (1 USD to MMK)", min_value=1.0, value=3250.0, step=10.0)
    
    currency_symbol = "$" if currency_selection == "USD" else "Ks "
    
    # --- FORM METADATA INGESTION BLOCKS ---
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
    st.subheader("📑 Document Loading Optimization Subsystem")
    uploaded_doc = st.file_uploader("Ingest Document Vector (.xlsx, .xls, .csv, .pdf supported)", type=["xlsx", "xls", "csv", "pdf"])
    
    items_list = []
    if uploaded_doc:
        try:
            if uploaded_doc.name.endswith('.pdf'):
                items_list = parse_pdf_document(uploaded_doc)
            elif uploaded_doc.name.endswith('.csv'):
                raw_df = pd.read_csv(uploaded_doc)
                items_list = parse_uploaded_document(raw_df)
            else:
                raw_df = pd.read_excel(uploaded_doc)
                items_list = parse_uploaded_document(raw_df)
            st.success(f"Heuristics matrix mapped {len(items_list)} unique records from file layout.")
        except Exception as e:
            st.error(f"Ingestion compilation failure: {e}")

    # Set initial core session list state
    if "working_items" not in st.session_state or uploaded_doc:
        if items_list:
            st.session_state.working_items = items_list
        else:
            st.session_state.working_items = [
                {"No": "1", "is_sub": False, "parent_idx": "1", "Part Number/Model": "C9300-48TX-E", "Description": "Catalyst 9300 48-port Data Only Network Essentials", "Qty": 1, "Unit Price": 3500.0, "Margin": 20.0, "Total Price": 0.0},
                {"No": "1.1", "is_sub": True, "parent_idx": "1", "Part Number/Model": "STACK-M-50CM", "Description": "Cisco Catalyst 9300 Stack Cable 50CM", "Qty": 1, "Unit Price": 150.0, "Margin": 10.0, "Total Price": 0.0}
            ]

    st.subheader("✏️ Live Data Manipulation Grid")
    conversion_multiplier = exchange_rate if currency_selection == "MMK" else 1.0

    # Execute math directly across working rows BEFORE showing them to make it real-time
    for item in st.session_state.working_items:
        qty = float(item.get("Qty") or 1)
        u_p = float(item.get("Unit Price") or 0.0)
        m_pct = float(item.get("Margin") or 0.0) / 100.0
        final_unit_usd = u_p / (1 - m_pct) if m_pct < 1.0 else u_p
        item["Total Price"] = round((final_unit_usd * qty) * conversion_multiplier, 2)

    df_display = pd.DataFrame(st.session_state.working_items)
    visible_cols = ["No", "Part Number/Model", "Qty", "Unit Price", "Margin", "Total Price"]
    for c in visible_cols:
        if c not in df_display.columns:
            df_display[c] = 0.0 if c in ["Qty", "Unit Price", "Margin", "Total Price"] else ""

    # Display clean real-time table grid
    edited_df = st.data_editor(
        df_display[visible_cols],
        num_rows="dynamic",
        width="stretch",
        key="quotation_data_editor",
        column_config={
            "No": st.column_config.TextColumn("No", width="small"),
            "Part Number/Model": st.column_config.TextColumn("Part Number/Model"),
            "Qty": st.column_config.NumberColumn("Qty", min_value=1),
            "Unit Price": st.column_config.NumberColumn(f"Unit Price ({currency_selection if currency_selection == 'MMK' else 'USD'})", format=f"{currency_symbol}%.2f"),
            "Margin": st.column_config.NumberColumn("Margin (%)"),
            "Total Price": st.column_config.NumberColumn(f"Total Price ({currency_selection})", format=f"{currency_symbol}%.2f", disabled=True)
        }
    )

    # CRITICAL FIX: If user edits data, immediately sync and force state re-run to make it reflect instantly!
    if not edited_df.equals(df_display[visible_cols]):
        updated_records = []
        for idx, row in edited_df.iterrows():
            orig_meta = st.session_state.working_items[idx] if idx < len(st.session_state.working_items) else {"is_sub": False, "parent_idx": "1", "Description": "Custom item"}
            qty_val = row.get("Qty") or 1
            up_val = row.get("Unit Price") or 0.0
            margin_val = row.get("Margin") or 0.0

            updated_records.append({
                "No": str(row["No"] or ""),
                "is_sub": orig_meta.get("is_sub", False),
                "parent_idx": orig_meta.get("parent_idx", "1"),
                "Part Number/Model": row["Part Number/Model"] or "",
                "Description": orig_meta.get("Description", "Custom item"),
                "Qty": int(qty_val),
                "Unit Price": float(up_val),
                "Margin": float(margin_val),
                "Total Price": 0.0
            })
        st.session_state.working_items = updated_records
        st.rerun()

    # --- ADD RELATIONAL ROW CONTROLS ---
    btn_c1, btn_c2 = st.columns(2)
    with btn_c1:
        if st.button("➕ Add Main Row"):
            main_rows = []
            for item in st.session_state.working_items:
                if not item.get("is_sub", False):
                    try: main_rows.append(int(float(item["No"] or 0)))
                    except ValueError: pass
            next_no = str(max(main_rows) + 1 if main_rows else 1)
            st.session_state.working_items.append({
                "No": next_no, "is_sub": False, "parent_idx": next_no, 
                "Part Number/Model": "NEW-ITEM", "Description": "Main Asset Block", 
                "Qty": 1, "Unit Price": 0.0, "Margin": 0.0, "Total Price": 0.0
            })
            st.rerun()

    with btn_c2:
        if st.button("🌿 Add Sub-Row"):
            if st.session_state.working_items:
                last_item = st.session_state.working_items[-1]
                p_idx = last_item.get("parent_idx", "1")
                siblings = [item for item in st.session_state.working_items if item.get("is_sub", False) and item.get("parent_idx") == p_idx]
                sub_id = len(siblings) + 1
                st.session_state.working_items.append({
                    "No": f"{p_idx}.{sub_id}", "is_sub": True, "parent_idx": p_idx, 
                    "Part Number/Model": "SUB-ITEM", "Description": "Nested component asset", 
                    "Qty": 1, "Unit Price": 0.0, "Margin": 0.0, "Total Price": 0.0
                })
                st.rerun()

    # --- ADD SERVICES VECTOR BLOCKS ---
    st.markdown("---")
    st.subheader("⚙️ Appended Professional & Maintenance Services Adjustments")
    srv_c1, srv_c2 = st.columns(2)
    with srv_c1:
        ps_desc = st.text_area("Professional Service (PS) Work Description", "ARK Implementation & Engineering Configuration Support", height=120)
        ps_price_usd = st.number_input("Professional Service (PS) Package Total Price (USD)", min_value=0.0, value=0.0)
    with srv_c2:
        ms_desc = st.text_area("Managed Service (MS) Operational Description", "ARK Premium 24/7 Monitoring & Critical SLA Support Contract", height=120)
        ms_price_usd = st.number_input("Managed Service (MS) Package Total Price (USD)", min_value=0.0, value=0.0)

    # --- FINANCIAL TRANSLATION VALUE POOLS ---
    item_subtotal_base = sum([float(item.get("Total Price") or 0.0) for item in st.session_state.working_items])
    global_subtotal_base = item_subtotal_base + ((ps_price_usd + ms_price_usd) * conversion_multiplier)
    
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"### 💰 Financial Aggregations Summary ({currency_selection})")
    global_discount_base = st.sidebar.number_input(f"Apply Overall Summary Discount ({currency_selection})", min_value=0.0, value=0.0)
    subtotal_after_disc = max(0.0, global_subtotal_base - global_discount_base)
    global_tax_pct = st.sidebar.number_input("Apply National Commercial Tax/VAT (%)", min_value=0.0, value=5.0)
    calculated_tax = subtotal_after_disc * (global_tax_pct / 100.0)
    calculated_grand_total = subtotal_after_disc + calculated_tax
    
    st.sidebar.markdown(f"**Gross Subtotal:** {currency_symbol}{global_subtotal_base:,.2f}")
    st.sidebar.markdown(f"**Tax Pool:** {currency_symbol}{calculated_tax:,.2f}")
    st.sidebar.markdown(f"### **Grand Total:** {currency_symbol}{calculated_grand_total:,.2f}")

    # --- OPERATION TRIGGER COMMANDS ---
    action_c1, action_c2 = st.columns(2)
    
    if action_c1.button("💾 Persist Document Configuration (Save Draft)"):
        with get_db() as conn:
            conn.execute("""
                INSERT INTO quotations (po_number, creator_id, customer_name, project_name, attention_person, attention_email, attention_phone, status, issue_date, validity, lead_time, payment_term, terms_conditions, subtotal, discount, tax, grand_total, currency_unit, exchange_rate, items_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (quotation_auto_gen, current_user["id"], client_company, project_title, attn_person, attn_email, attn_phone, str(issue_date), validity_bound, lead_time_frame, payment_terms_desc, terms_and_cond, global_subtotal_base, global_discount_base, calculated_tax, calculated_grand_total, currency_selection, exchange_rate, edited_df.to_json()))
            conn.commit()
        st.success(f"Quotation layout successfully archived locally as Draft reference hash `{quotation_auto_gen}`")

    if action_c2.button("🖨️ Compile Official Corporate PDF Engine Asset"):
        html_table_rows = ""
        for item in st.session_state.working_items:
            row_class = "class='sub-row'" if item.get("is_sub", False) else ""
            indent_prefix = "└── " if item.get("is_sub", False) else ""
            
            qty = float(item.get("Qty") or 1)
            u_p = float(item.get("Unit Price") or 0.0)
            m_pct = float(item.get("Margin") or 0.0) / 100.0
            final_unit_usd = u_p / (1 - m_pct) if m_pct < 1.0 else u_p
            
            converted_unit_price = final_unit_usd * conversion_multiplier
            converted_total_price = item.get("Total Price") or 0.0
            
            html_table_rows += f"""
            <tr {row_class}>
                <td style="text-align: center;">{item.get('No') or ''}</td>
                <td style="font-size: 8pt; word-break: break-all !important;">{item.get('Part Number/Model') or ''}</td>
                <td style="font-size: 8pt; word-break: break-all !important;">{indent_prefix}{item.get('Description') or ''}</td>
                <td style="text-align: center;">{int(qty)}</td>
                <td style="text-align: right; font-size: 8pt; white-space: nowrap !important;">{currency_symbol}{converted_unit_price:,.2f}</td>
                <td style="text-align: right; font-weight: bold; font-size: 8pt; white-space: nowrap !important;">{currency_symbol}{converted_total_price:,.2f}</td>
            </tr>
            """
            
        if ps_price_usd > 0:
            ps_converted = ps_price_usd * conversion_multiplier
            formatted_ps_desc = ps_desc.replace('\n', '<br>')
            html_table_rows += f"<tr><td style='text-align:center;'>-</td><td style='font-size: 8pt; word-break: break-all !important;'>PS-SERVICE</td><td style='font-size: 8pt; word-break: break-all !important;'>{formatted_ps_desc}</td><td style='text-align:center;'>1</td><td style='text-align:right; font-size: 8pt; white-space: nowrap !important;'>{currency_symbol}{ps_converted:,.2f}</td><td style='text-align:right; font-weight:bold; font-size: 8pt; white-space: nowrap !important;'>{currency_symbol}{ps_converted:,.2f}</td></tr>"
        if ms_price_usd > 0:
            ms_converted = ms_price_usd * conversion_multiplier
            formatted_ms_desc = ms_desc.replace('\n', '<br>')
            html_table_rows += f"<tr><td style='text-align:center;'>-</td><td style='font-size: 8pt; word-break: break-all !important;'>MS-SERVICE</td><td style='font-size: 8pt; word-break: break-all !important;'>{formatted_ms_desc}</td><td style='text-align:center;'>1</td><td style='text-align:right; font-size: 8pt; white-space: nowrap !important;'>{currency_symbol}{ms_converted:,.2f}</td><td style='text-align:right; font-weight:bold; font-size: 8pt; white-space: nowrap !important;'>{currency_symbol}{ms_converted:,.2f}</td></tr>"

        exchange_rate_notice = f"<div style='font-size:8pt;color:#4b5563;margin-bottom:10px;'>🌐 <strong>Calculated Conversion Rate Profile:</strong> 1 USD = {exchange_rate:,.2f} MMK</div>" if currency_selection == "MMK" else ""

        full_printable_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                @page {{ size: A4; margin: 15mm 15mm; }}
                body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #1f2937; font-size: 8.5pt; line-height: 1.4; }}
                .brand-header {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
                .brand-header td {{ vertical-align: middle; border: none; }}
                .logo-img {{ max-height: 50px; display: block; }}
                .address-text {{ font-size: 7.5pt; color: #4b5563; text-align: right; line-height: 1.4; }}
                .title-bar {{ background-color: #00a8e8; color: white; padding: 8px; font-size: 14pt; font-weight: bold; text-transform: uppercase; margin-bottom: 20px; text-align: center; }}
                .meta-table {{ width: 100%; margin-bottom: 20px; border-collapse: collapse; }}
                .meta-table td {{ border: 1px solid #e5e7eb; padding: 8px; vertical-align: top; width: 50%; }}
                
                .items-table {{ width: 100%; border-collapse: collapse; margin-top: 15px; table-layout: auto; }}
                .items-table th {{ background-color: #1f2937; color: white; padding: 8px; font-size: 8.5pt; text-transform: uppercase; border: 1px solid #1f2937; }}
                .items-table td {{ border: 1px solid #e5e7eb; padding: 6px; vertical-align: top; white-space: normal; overflow: visible; }}
                
                .col-no {{ width: 6%; }}
                .col-qty {{ width: 5%; }}
                .col-part {{ width: 18%; }}
                .col-desc {{ width: 30%; }}
                .col-uprice {{ width: auto; text-align: right; }}
                .col-tprice {{ width: auto; text-align: right; }}
                
                .sub-row td {{ background-color: #f9fafb; color: #4b5563; font-style: italic; }}
                .totals-table {{ width: 45%; margin-left: auto; border-collapse: collapse; margin-top: 20px; }}
                .totals-table td {{ padding: 6px; border-bottom: 1px solid #e5e7eb; }}
                .grand-total-row {{ background-color: #00a8e8; color: white; font-weight: bold; }}
                .footer-notes {{ margin-top: 30px; font-size: 8pt; color: #6b7280; border-top: 1px solid #e5e7eb; padding-top: 10px; }}
            </style>
        </head>
        <body>
            <table class="brand-header">
                <tr>
                    <td><img src="https://arktechsolutions.net/wp-content/themes/wp-ark/assets/img/logo-ark.png" class="logo-img"></td>
                    <td class="address-text">
                        <strong>ARK Premium Solutions Limited</strong><br>
                        ARK Corporate Office : 12th floor, Times City(office tower-2), Kamayut, Yangon, Myanmar.<br>
                        Tel: +95 9 445830101
                    </td>
                </tr>
            </table>
            
            <div class="title-bar">Commercial Quotation</div>
            
            <table class="meta-table">
                <tr>
                    <td>
                        <strong>Prepared For:</strong><br>
                        {client_company}<br>
                        Attn: {attn_person}<br>
                        Email: {attn_email} | Tel: {attn_phone}
                    </td>
                    <td>
                        <strong>Reference Details:</strong><br>
                        Quotation Number: {quotation_auto_gen}<br>
                        Issue Date: {issue_date}<br>
                        Validity Limit: {validity_bound}<br>
                        Currency Unit: {currency_selection}
                    </td>
                </tr>
            </table>

            {exchange_rate_notice}

            <table class="items-table">
                <thead>
                    <tr>
                        <th class="col-no">No</th>
                        <th class="col-part">Part Number</th>
                        <th class="col-desc">Description</th>
                        <th class="col-qty">Qty</th>
                        <th class="col-uprice">Unit Price</th>
                        <th class="col-tprice">Total Price</th>
                    </tr>
                </thead>
                <tbody>
                    {html_table_rows}
                </tbody>
            </table>

            <table class="totals-table">
                <tr><td>Gross Subtotal:</td><td style="text-align: right; white-space: nowrap !important;">{currency_symbol}{global_subtotal_base:,.2f}</td></tr>
                <tr><td>Global Discount:</td><td style="text-align: right; white-space: nowrap !important;">-{currency_symbol}{global_discount_base:,.2f}</td></tr>
                <tr><td>Commercial Tax ({global_tax_pct}%):</td><td style="text-align: right; white-space: nowrap !important;">{currency_symbol}{calculated_tax:,.2f}</td></tr>
                <tr class="grand-total-row"><td>Grand Total ({currency_selection}):</td><td style="text-align: right; white-space: nowrap !important;">{currency_symbol}{calculated_grand_total:,.2f}</td></tr>
            </table>

            <div class="footer-notes">
                <strong>Commercial Delivery Terms & Scope:</strong><br>
                Estimated Production Delivery Lead Time: {lead_time_frame}<br>
                Target Execution Payment Schedule Terms: {payment_terms_desc}<br>
                <strong>Operational Provisions:</strong><br>
                {terms_and_cond.replace('\n', '<br>')}
            </div>
        </body>
        </html>
        """
        
        pdf_filename = f"ARK_Quotation_{quotation_auto_gen}.pdf"
        HTML(string=full_printable_html).write_pdf(pdf_filename)
        
        with open(pdf_filename, "rb") as f:
            st.download_button(
                label=f"📥 Download Compiled A4 Quotation PDF Bundle ({currency_selection})",
                data=f.read(),
                file_name=pdf_filename,
                mime="application/pdf"
            )
            
        with get_db() as conn:
            conn.execute("""
                INSERT INTO quotations (po_number, creator_id, customer_name, project_name, attention_person, attention_email, attention_phone, status, issue_date, validity, lead_time, payment_term, terms_conditions, subtotal, discount, tax, grand_total, currency_unit, exchange_rate, items_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'SUBMITTED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (quotation_auto_gen, current_user["id"], client_company, project_title, attn_person, attn_email, attn_phone, str(issue_date), validity_bound, lead_time_frame, payment_terms_desc, terms_and_cond, global_subtotal_base, global_discount_base, calculated_tax, calculated_grand_total, currency_selection, exchange_rate, edited_df.to_json()))
            conn.commit()
        st.success("PDF payload successfully generated. Click the action button above to export.")