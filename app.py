import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import random
import re
import base64
from weasyprint import HTML

# --- PAGE SETUP & THEME ---
st.set_page_config(page_title="ARK Premium Solutions - Quotation Portal", page_icon="🌐", layout="wide")

# Custom UI CSS Inject for Sky Blue/Dark Slate theme pairing
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
        admin_exists = conn.execute("SELECT 1 FROM users WHERE email='admin@arktechsolutions.net'").fetchone()
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
    # Mocking outgoing transactional SMTP email service
    st.info(f"📧 Transactional System Log: Sent code `{code}` to verified destination mailbox {email}")

# --- PARSING HEURISTICS ENGINE ---
def parse_uploaded_document(df_raw):
    """
    Scans columns dynamically to isolate Part Number and Description (longest text field).
    Supports hierarchal groupings.
    """
    structured_items = []
    if df_raw.empty:
        return structured_items

    # Identify the column with the longest text string to use as description
    sample_rows = df_raw.head(10).astype(str)
    desc_col = sample_rows.apply(lambda x: x.str.len().max()).idxmax()
    
    # Simple guess for numeric columns
    qty_col = None
    price_col = None
    for col in df_raw.columns:
        col_lower = str(col).lower()
        if 'qty' in col_lower or 'quant' in col_lower:
            qty_col = col
        elif 'price' in col_lower or 'rate' in col_lower or 'unit' in col_lower:
            price_col = col

    for idx, row in df_raw.iterrows():
        desc_val = str(row[desc_col]) if desc_col in df_raw.columns else f"Item Reference Line {idx+1}"
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
            "No": f"{idx+1}",
            "Part Number": part_no,
            "Description": desc_val,
            "Qty": qty_val,
            "Unit Price": price_val,
            "Margin %": 20.0,
            "Discount %": 0.0,
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
        login_email = st.text_input("Corporate Email Address Address", key="login_em")
        login_pwd = st.text_input("Password Secure Vector", type="password", key="login_pw")
        if st.button("Sign In"):
            with get_db() as conn:
                res = conn.execute("SELECT * FROM users WHERE email=? AND password_hash=?", (login_email, hash_pwd(login_pwd))).fetchone()
                if res:
                    if res["is_verified"] == 0:
                        st.error("Account verification code pending clearance.")
                    else:
                        st.session_state.user = {"id": res["id"], "email": res["email"], "role": res["role"]}
                        st.rerun()
                else:
                    st.error("Invalid credentials supplied.")
                    
    with auth_tab2:
        reg_email = st.text_input("Corporate Email Address Address", key="reg_em")
        reg_pwd = st.text_input("Create Security Password", type="password", key="reg_pw")
        reg_role = st.selectbox("Requested Core Functional Target Profile", ["Account Manager"]) # Directors & Top Management require explicit Admin promotion vectors
        
        if st.button("Initiate Sign Up Pipeline"):
            code = str(random.randint(100000, 999999))
            try:
                with get_db() as conn:
                    conn.execute("INSERT INTO users (email, password_hash, role, is_verified, verification_code) VALUES (?, ?, ?, 0, ?)",
                                 (reg_email, hash_pwd(reg_pwd), reg_role, code))
                    conn.commit()
                send_mock_verification_email(reg_email, code)
                st.success("Registration success! Check console window for temporary confirmation vector.")
            except sqlite3.IntegrityError:
                st.error("Identity database conflict: Email already registered inside network ledger.")
                
        st.markdown("---")
        verify_email = st.text_input("Confirm Registered Email Destination Address", key="v_em")
        verify_code = st.text_input("Enter 6-Digit OTP Secure Access Code", key="v_cd")
        if st.button("Verify Credentials Clearance"):
            with get_db() as conn:
                user_rec = conn.execute("SELECT * FROM users WHERE email=? AND verification_code=?", (verify_email, verify_code)).fetchone()
                if user_rec:
                    conn.execute("UPDATE users SET is_verified=1 WHERE email=?", (verify_email,))
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
            # Select own quotes + quotes from approved managed accounts
            quotes = conn.execute("""
                SELECT q.* FROM quotations q 
                WHERE q.creator_id = ? 
                OR q.creator_id IN (SELECT manager_id FROM team_mappings WHERE director_id=? AND status='ACCEPTED')
            """, (current_user["id"], current_user["id"])).fetchall()
        elif current_user["role"] == "Top Management":
            quotes = conn.execute("SELECT q.*, u.email as creator_email FROM quotations q JOIN users u ON q.creator_id = u.id").fetchall()

    df_quotes = pd.DataFrame([dict(q) for q in quotes]) if quotes else pd.DataFrame()
    
    if not df_quotes.empty:
        # High Level KPI Matrix
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric("Total Quotations Processed", len(df_quotes))
        kpi2.metric("Total Revenue Pipeline", f"${df_quotes['grand_total'].sum():,.2f}")
        kpi3.metric("Pending Confirmations", len(df_quotes[df_quotes['status'] == 'PENDING']))
        
        st.subheader("🗃️ Active Ledger Workspace")
        if current_user["role"] == "Top Management":
            # Advanced Filtering matrix across historical dimensions
            cust_filter = st.selectbox("Categorize by Customer Entity", ["ALL"] + list(df_quotes["customer_name"].unique()))
            proj_filter = st.selectbox("Categorize by Technical Project Title", ["ALL"] + list(df_quotes["project_name"].unique()))
            
            filtered_df = df_quotes.copy()
            if cust_filter != "ALL": filtered_df = filtered_df[filtered_df["customer_name"] == cust_filter]
            if proj_filter != "ALL": filtered_df = filtered_df[filtered_df["project_name"] == proj_filter]
            st.dataframe(filtered_df[["po_number", "customer_name", "project_name", "status", "grand_total", "creator_email"]], use_container_width=True)
        else:
            st.dataframe(df_quotes[["po_number", "customer_name", "project_name", "status", "grand_total"]], use_container_width=True)
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
            mgr_id = conn.execute("SELECT id FROM users WHERE email=?", (target_mgr,)).fetchone()["id"]
            # Avoid duplications
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
# 📥 ACCOUNT MANAGER INBOX / WORKSPACE
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
            st.sidebar.write(f"Director `{invite['dir_email']}` wants to view your logs.")
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
elif page_selection == "➕ Build New Quotation Module":
    st.header("➕ Document Generation Sandbox")
    
    # Prefix constraints setting
    po_auto_gen = f"ARK-{random.randint(100000, 999999)}"
    
    # --- FORM METADATA INGESTION BLOCKS ---
    meta_c1, meta_c2, meta_c3 = st.columns(3)
    with meta_c1:
        client_company = st.text_input("Client Corporate Entity Name", "Client Corporation Ltd.")
        attn_person = st.text_input("Attention Person Point of Contact", "John Doe")
        attn_email = st.text_input("Contact Email Destination", "johndoe@client.com")
        attn_phone = st.text_input("Contact Direct Phone Line", "+959xxxxxxxxx")
    with meta_c2:
        project_title = st.text_input("Internal Assignment / Project Title", "Network Phase 2 Upgrade")
        issue_date = st.date_input("Official Registration / Issue Date")
        validity_bound = st.text_input("Quotation Validity Frame", "30 Days from issuance")
    with meta_c3:
        lead_time_frame = st.text_input("Estimated Equipment Delivery Lead Time", "4-6 Weeks")
        payment_terms_desc = st.text_input("Agreed Commercial Payment Terms", "50% Advance, 50% Upon Delivery")
        terms_and_cond = st.text_area("Custom Legal Terms & Conditions Scope", "1. Standard ARK Warranty applies.\n2. Prices exclude deployment unless itemized below.")

    st.markdown("---")
    st.subheader("📑 Document Loading Optimization Subsystem")
    uploaded_doc = st.file_uploader("Ingest Document Vector (.xlsx, .xls, .csv, .pdf supported)", type=["xlsx", "xls", "csv"])
    
    items_list = []
    if uploaded_doc:
        try:
            if uploaded_doc.name.endswith('.csv'):
                raw_df = pd.read_csv(uploaded_doc)
            else:
                raw_df = pd.read_excel(uploaded_doc)
            items_list = parse_uploaded_document(raw_df)
            st.success(f"Heuristics matrix mapped {len(items_list)} unique records from file layout.")
        except Exception as e:
            st.error(f"Ingestion compilation failure: {e}")

    if "working_items" not in st.session_state or uploaded_doc:
        st.session_state.working_items = items_list if items_list else [{
            "No": "1", "Part Number": "C9300-48TX-E", "Description": "Catalyst 9300 48-port Data Only Network Essentials", "Qty": 1, "Unit Price": 3500.0, "Margin %": 20.0, "Discount %": 0.0, "Final Price": 4375.0
        }]

    # --- CELL EDITOR GRID INTERACTION LAYOUT ---
    st.subheader("✏️ Live Data Manipulation Grid")
    st.caption("Every text block and value wraps completely. Use decimals to represent sub-items (e.g., 1.1 for sub-items under item 1).")
    
    edited_items_df = st.data_editor(
        pd.DataFrame(st.session_state.working_items),
        num_rows="dynamic",
        use_container_width=True
    )
    
    # Recalculation Core Calculations
    if not edited_items_df.empty:
        # Safe casting conversion variables
        edited_items_df["Qty"] = pd.to_numeric(edited_items_df["Qty"]).fillna(1)
        edited_items_df["Unit Price"] = pd.to_numeric(edited_items_df["Unit Price"]).fillna(0.0)
        edited_items_df["Margin %"] = pd.to_numeric(edited_items_df["Margin %"]).fillna(0.0)
        edited_items_df["Discount %"] = pd.to_numeric(edited_items_df["Discount %"]).fillna(0.0)
        
        # Calculate individual line items with margin and discount applied
        # Formula: Base Configured Price = Cost / (1 - Margin)
        # Final Price = Base Configured Price * (1 - Discount)
        final_prices = []
        for idx, r in edited_items_df.iterrows():
            m_dec = r["Margin %"] / 100.0
            d_dec = r["Discount %"] / 100.0
            base_price = r["Unit Price"] / (1 - m_dec) if m_dec < 1 else r["Unit Price"]
            disc_price = base_price * (1 - d_dec)
            final_prices.append(round(disc_price, 2))
            
        edited_items_df["Final Price"] = final_prices
        st.session_state.working_items = edited_items_df.to_dict(orient="records")

    # --- ADD SERVICES VECTOR BLOCKS ---
    st.markdown("---")
    st.subheader("⚙️ Appended Professional & Maintenance Services Adjustments")
    srv_c1, srv_c2 = st.columns(2)
    with srv_c1:
        ps_desc = st.text_input("Professional Service (PS) Work Description", "ARK Implementation & Engineering Configuration Support")
        ps_price = st.number_input("Professional Service (PS) Package Total Price ($)", min_value=0.0, value=0.0)
    with srv_c2:
        ms_desc = st.text_input("Managed Service (MS) Operational Description", "ARK Premium 24/7 Monitoring & Critical SLA Support Contract")
        ms_price = st.number_input("Managed Service (MS) Package Total Price ($)", min_value=0.0, value=0.0)

    # --- GLOBAL CALCULATIONS LEDGER ---
    item_subtotal = (edited_items_df["Qty"] * edited_items_df["Final Price"]).sum() if not edited_items_df.empty else 0.0
    global_subtotal = item_subtotal + ps_price + ms_price
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 💰 Financial Aggregations Summary")
    global_discount = st.sidebar.number_input("Apply Overall Summary Discount ($)", min_value=0.0, value=0.0)
    subtotal_after_disc = max(0.0, global_subtotal - global_discount)
    global_tax_pct = st.sidebar.number_input("Apply National Commercial Tax/VAT (%)", min_value=0.0, value=5.0)
    calculated_tax = subtotal_after_disc * (global_tax_pct / 100.0)
    calculated_grand_total = subtotal_after_disc + calculated_tax
    
    st.sidebar.markdown(f"**Gross Subtotal:** ${global_subtotal:,.2f}")
    st.sidebar.markdown(f"**Tax Pool:** ${calculated_tax:,.2f}")
    st.sidebar.markdown(f"### **Grand Total:** ${calculated_grand_total:,.2f}")

    # --- OPERATION TRIGGER COMMANDS ---
    action_c1, action_c2 = st.columns(2)
    
    if action_c1.button("💾 Persist Document Configuration (Save Draft)"):
        with get_db() as conn:
            conn.execute("""
                INSERT INTO quotations (po_number, creator_id, customer_name, project_name, attention_person, attention_email, attention_phone, status, issue_date, validity, lead_time, payment_term, terms_conditions, subtotal, discount, tax, grand_total, items_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (po_auto_gen, current_user["id"], client_company, project_title, attn_person, attn_email, attn_phone, str(issue_date), validity_bound, lead_time_frame, payment_terms_desc, terms_and_cond, global_subtotal, global_discount, calculated_tax, calculated_grand_total, edited_items_df.to_json()))
            conn.commit()
        st.success(f"Quotation state preserved securely under transaction hash reference `{po_auto_gen}`")

    if action_c2.button("🖨️ Compile Official Corporate PDF Engine Asset"):
        # Generate the dynamic HTML rows with strict CSS text wrapping
        html_table_rows = ""
        for idx, r in edited_items_df.iterrows():
            is_sub = "." in str(r["No"])
            indent_style = "padding-left: 20px; font-style: italic; color: #475569;" if is_sub else "font-weight: bold;"
            html_table_rows += f"""
            <tr>
                <td style="text-align: center; white-space: normal; word-break: break-all;">{r['No']}</td>
                <td style="white-space: normal; word-break: break-all;">{r['Part Number']}</td>
                <td style="white-space: normal; word-break: break-all; {indent_style}">{r['Description']}</td>
                <td style="text-align: center;">{int(r['Qty'])}</td>
                <td style="text-align: right;">${r['Final Price']:,.2f}</td>
                <td style="text-align: right; font-weight: bold;">${(r['Qty']*r['Final Price']):,.2f}</td>
            </tr>
            """
            
        if ps_price > 0:
            html_table_rows += f"<tr><td>-</td><td>PS-SERVICE</td><td style='white-space: normal; word-break: break-all;'>{ps_desc}</td><td style='text-align:center;'>1</td><td style='text-align:right;'>${ps_price:,.2f}</td><td style='text-align:right;font-weight:bold;'>${ps_price:,.2f}</td></tr>"
        if ms_price > 0:
            html_table_rows += f"<tr><td>-</td><td>MS-SERVICE</td><td style='white-space: normal; word-break: break-all;'>{ms_desc}</td><td style='text-align:center;'>1</td><td style='text-align:right;'>${ms_price:,.2f}</td><td style='text-align:right;font-weight:bold;'>${ms_price:,.2f}</td></tr>"

        # HTML Layout customized to match ARK Premium Solutions branding
        full_printable_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                @page {{ size: A4; margin: 20mm 15mm; }}
                body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #1f2937; font-size: 9.5pt; line-height: 1.4; }}
                .brand-header {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
                .brand-header td {{ vertical-align: middle; border: none; }}
                .address-text {{ font-size: 8pt; color: #4b5563; text-align: right; line-height: 1.3; }}
                .title-bar {{ background-color: #00a8e8; color: white; padding: 10px; font-size: 16pt; font-weight: bold; text-transform: uppercase; margin-bottom: 20px; text-align: center; }}
                .meta-table {{ width: 100%; margin-bottom: 20px; border-collapse: collapse; }}
                .meta-table td {{ border: 1px solid #e5e7eb; padding: 8px; vertical-align: top; width: 50%; }}
                .items-table {{ width: 100%; border-collapse: collapse; margin-top: 15px; table-layout: fixed; }}
                .items-table th {{ background-color: #1f2937; color: white; padding: 8px; font-size: 9pt; text-transform: uppercase; border: 1px solid #1f2937; }}
                .items-table td {{ border: 1px solid #e5e7eb; padding: 8px; vertical-align: top; word-wrap: break-word; white-space: normal; }}
                .totals-table {{ width: 40%; margin-left: auto; border-collapse: collapse; margin-top: 20px; }}
                .totals-table td {{ padding: 6px; border-bottom: 1px solid #e5e7eb; }}
                .grand-total-row {{ background-color: #00a8e8; color: white; font-weight: bold; }}
                .footer-notes {{ margin-top: 40px; font-size: 8pt; color: #6b7280; border-top: 1px solid #e5e7eb; padding-top: 10px; }}
            </style>
        </head>
        <body>
            <table class="brand-header">
                <tr>
                    <td><img src="https://arktechsolutions.net/wp-content/themes/wp-ark/assets/img/logo-ark.png" style="max-height: 55px;"></td>
                    <td class="address-text">
                        <strong>ARK Premium Solutions Limited</strong><br>
                        HQ: 91, Shwe Taung Kyar 1st Street, Golden Valley 1, Bahan, Yangon, Myanmar.<br>
                        Corporate Office: 12th floor, Times City(office tower-2), Kamayut, Yangon.<br>
                        Thailand Office: 1, Soi Ramkhamhaeng 118 Yaek 33-3, Bangkok.<br>
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
                        Ref / PO Number: {po_auto_gen}<br>
                        Issue Date: {issue_date}<br>
                        Validity Limit: {validity_bound}
                    </td>
                </tr>
            </table>

            <table class="items-table">
                <thead>
                    <tr>
                        <th style="width: 7%;">No</th>
                        <th style="width: 20%;">Part Number</th>
                        <th style="width: 43%;">Description Matrix</th>
                        <th style="width: 8%;">Qty</th>
                        <th style="width: 10%;">Unit Price</th>
                        <th style="width: 12%;">Total Price</th>
                    </tr>
                </thead>
                <tbody>
                    {html_table_rows}
                </tbody>
            </table>

            <table class="totals-table">
                <tr><td>Gross Subtotal:</td><td style="text-align: right;">${global_subtotal:,.2f}</td></tr>
                <tr><td>Global Discount:</td><td style="text-align: right;">-${global_discount:,.2f}</td></tr>
                <tr><td>Commercial Tax ({global_tax_pct}%):</td><td style="text-align: right;">${calculated_tax:,.2f}</td></tr>
                <tr class="grand-total-row"><td>Grand Total (USD):</td><td style="text-align: right;">${calculated_grand_total:,.2f}</td></tr>
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
        
        pdf_filename = f"ARK_Quotation_{po_auto_gen}.pdf"
        HTML(string=full_printable_html).write_pdf(pdf_filename)
        
        with open(pdf_filename, "rb") as f:
            st.download_button(
                label="📥 Download Compiled A4 Quotation PDF Bundle",
                data=f.read(),
                file_name=pdf_filename,
                mime="application/pdf"
            )
            
        # Log the finalized document record into the analytical backend database
        with get_db() as conn:
            conn.execute("""
                INSERT INTO quotations (po_number, creator_id, customer_name, project_name, attention_person, attention_email, attention_phone, status, issue_date, validity, lead_time, payment_term, terms_conditions, subtotal, discount, tax, grand_total, items_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'SUBMITTED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (po_auto_gen, current_user["id"], client_company, project_title, attn_person, attn_email, attn_phone, str(issue_date), validity_bound, lead_time_frame, payment_terms_desc, terms_and_cond, global_subtotal, global_discount, calculated_tax, calculated_grand_total, edited_items_df.to_json()))
            conn.commit()
        st.success("PDF payload successfully generated. Click the action button above to export.")