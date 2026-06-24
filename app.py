# app.py
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
            
        # --- FIXED STR-BASED INDEX HIERARCHY LOGIC ---
        row_no_raw = str(row.get("No", idx + 1)).strip()
        
        if row_no_raw.endswith(".0"):
            row_no = row_no_raw.split(".")[0]  # Transforms "1.0" -> "1"
            is_sub_row = False                  # It is a root parent row
        elif "." in row_no_raw:
            row_no = row_no_raw                 # Keeps "1.1" intact
            is_sub_row = True                   # It is a sub-component row
        else:
            row_no = row_no_raw
            is_sub_row = False
            
        p_idx = row_no.split(".")[0]
            
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
            if col not in [desc_col, qty_col, price_col, "No"]:
                val = str(row[col]).strip()
                if val and len(val) < 15 and val != "nan":
                    part_no = val
                    break

        structured_items.append({
            "No": row_no,
            "is_sub": is_sub_row,
            "parent_idx": p_idx,
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
                        "parent_idx": str(idx),
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
    st.rerun()

# Navigation Router
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
            chart_count_data = pd.DataFrame({
                "Submitted (Pending)": [len(submitted_df)],
                "Won (PO Received)": [len(won_df)]
            })
            st.bar_chart(chart_count_data, color=["#00a8e8", "#2ecc71"])
            
        with g_col2:
            st.markdown("<p style='text-align: center; font-weight: bold;'>Cumulative Pipeline Value ($)</p>", unsafe_allow_html=True)
            chart_value_data = pd.DataFrame({
                "Submitted (Pending)": [submitted_df['grand_total'].sum()],
                "Won (PO Received)": [won_df['grand_total'].sum()]
            })
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
    currency_symbol = "$" if currency_selection == "USD" else "Ks "
    
    st.sidebar.markdown("### 📋 System Template")
    sample_df = pd.DataFrame({
        "No": ["1", "1.1", "1.2", "2"],
        "Part Number": ["C9300-48TX-E", "STACK-M-50CM", "PWR-C1-1100WAC", "CON-SNT-C930048T"],
        "Description": ["Catalyst 9300 48-port Data Only Network Essentials", "Cisco Catalyst 9300 Stack Cable 50CM", "Cisco Catalyst Power Supply 1100W", "SNTC-8X5XNBD Catalyst 9300 48-port Data Only"],
        "Qty": [1, 1, 1, 1],
        "Unit Price": [4500.00, 250.00, 600.00, 850.00]
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
                # Enforce No to parse as pure string to protect .0 endings
                items_list = parse_uploaded_document(pd.read_csv(uploaded_doc, dtype={"No": str}))
            else:
                items_list = parse_uploaded_document(pd.read_excel(uploaded_doc, dtype={"No": str}))
            st.success(f"Mapped {len(items_list)} items.")
        except Exception as e:
            st.error(f"Ingestion failure: {e}")

    if "working_items" not in st.session_state or uploaded_doc:
        if items_list:
            st.session_state.working_items = items_list
        else:
            st.session_state.working_items = [
                {"No": "1", "is_sub": False, "parent_idx": "1", "Part Number/Model": "C9300-48TX-E", "Description": "Catalyst 9300 48-port Data Only Network Essentials", "Qty": 1, "Unit Price": 100.0, "Margin": 10.0, "Total Price": 0.0},
                {"No": "1.1", "is_sub": True, "parent_idx": "1", "Part Number/Model": "STACK-M-50CM", "Description": "Cisco Catalyst 9300 Stack Cable 50CM", "Qty": 1, "Unit Price": 50.0, "Margin": 10.0, "Total Price": 0.0},
                {"No": "1.2", "is_sub": True, "parent_idx": "1", "Part Number/Model": "PWR-C1-1100WAC", "Description": "Cisco Catalyst Power Supply 1100W", "Qty": 1, "Unit Price": 50.0, "Margin": 10.0, "Total Price": 0.0}
            ]

    conversion_multiplier = exchange_rate if currency_selection == "MMK" else 1.0

    st.markdown("#### ⚡ Global Commercial Adjustments")
    m_col1, m_col2 = st.columns([2, 3])
    with m_col1:
        global_margin_input = st.number_input("Set Target Uniform Margin (%)", min_value=0.0, max_value=99.0, value=10.0, step=1.0)
    with m_col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("⚡ Apply Margin to All Rows"):
            for item in st.session_state.working_items:
                item["Margin"] = float(global_margin_input)
            st.success(f"Applied a uniform {global_margin_input}% margin setting across all portfolio entries.")
            st.rerun()

    # Calculation execution loop
    for item in st.session_state.working_items:
        qty = float(item.get("Qty") or 1)
        u_p = float(item.get("Unit Price") or 0.0)
        m_pct = float(item.get("Margin") or 0.0) / 100.0
        final_unit_price = u_p / (1 - m_pct) if m_pct < 1.0 else u_p
        item["Total Price"] = round((final_unit_price * qty) * conversion_multiplier, 2)

    df_display = pd.DataFrame(st.session_state.working_items)
    visible_cols = ["No", "Part Number/Model", "Description", "Qty", "Unit Price", "Margin", "Total Price"]
    for c in visible_cols:
        if c not in df_display.columns:
            df_display[c] = 0.0 if c in ["Qty", "Unit Price", "Margin", "Total Price"] else ""

    # Live Data Editor Workspace Rendering
    edited_df = st.data_editor(
        df_display[visible_cols],
        num_rows="dynamic",
        width="stretch",
        key="quotation_data_grid",
        column_config={
            "No": st.column_config.TextColumn("No", width="small"),
            "Part Number/Model": st.column_config.TextColumn("Part Number/Model"),
            "Description": st.column_config.TextColumn("Item Description Specifications", width="large"),
            "Qty": st.column_config.NumberColumn("Qty", min_value=1),
            "Unit Price": st.column_config.NumberColumn(f"Unit Price ({currency_selection})", format=f"{currency_symbol}%.2f"),
            "Margin": st.column_config.NumberColumn("Margin (%)"),
            "Total Price": st.column_config.NumberColumn(f"Total Price ({currency_selection})", format=f"{currency_symbol}%.2f", disabled=True)
        }
    )

    if not edited_df.equals(df_display[visible_cols]):
        updated_records = []
        
        # --- ROBUST OVERRIDE HIERARCHY LOGIC ENGINE ---
        for idx, row in edited_df.iterrows():
            orig_meta = st.session_state.working_items[idx] if idx < len(st.session_state.working_items) else {"is_sub": False, "parent_idx": "1", "Description": "Custom item"}
            row_no = str(row["No"] or "")
            is_sub_row = "." in row_no
            p_idx = row_no.split(".")[0] if is_sub_row else row_no
            
            try:
                ui_margin = float(row.get("Margin") or 0.0)
            except ValueError:
                ui_margin = float(global_margin_input)
                
            try:
                old_margin = float(orig_meta.get("Margin") or 0.0)
            except:
                old_margin = float(global_margin_input)

            target_margin = ui_margin
            
            if is_sub_row:
                parent_row_matches = [r for _, r in edited_df.iterrows() if str(r.get("No")) == p_idx]
                if parent_row_matches:
                    p_row = parent_row_matches[0]
                    try:
                        p_ui_margin = float(p_row.get("Margin") or 0.0)
                    except:
                        p_ui_margin = float(global_margin_input)
                        
                    p_orig_matches = [i for i in st.session_state.working_items if str(i.get("No")) == p_idx]
                    p_old_margin = float(p_orig_matches[0].get("Margin", 0.0)) if p_orig_matches else 0.0
                    
                    if p_ui_margin != p_old_margin and ui_margin == old_margin:
                        target_margin = p_ui_margin

            updated_records.append({
                "No": row_no, 
                "is_sub": is_sub_row, 
                "parent_idx": p_idx,
                "Part Number/Model": row["Part Number/Model"] or "",
                "Description": row["Description"] or "Custom item",
                "Qty": int(row.get("Qty") or 1),
                "Unit Price": float(row.get("Unit Price") or 0.0),
                "Margin": float(target_margin), 
                "Total Price": 0.0
            })
        st.session_state.working_items = updated_records
        st.rerun()

    btn_c1, btn_c2 = st.columns(2)
    with btn_c1:
        if st.button("➕ Add Main Row"):
            main_rows = []
            for item in st.session_state.working_items:
                if not item.get("is_sub", False):
                    try: main_rows.append(int(float(item["No"] or 0)))
                    except: pass
            next_no = str(max(main_rows) + 1 if main_rows else 1)
            st.session_state.working_items.append({
                "No": next_no, "is_sub": False, "parent_idx": next_no, 
                "Part Number/Model": "NEW-ITEM", "Description": "Main Asset Block Description Specs", 
                "Qty": 1, "Unit Price": 0.0, "Margin": float(global_margin_input), "Total Price": 0.0
            })
            st.rerun()
    with btn_c2:
        if st.button("🌿 Add Sub-Row"):
            if st.session_state.working_items:
                last_item = st.session_state.working_items[-1]
                p_idx = last_item.get("parent_idx", "1")
                siblings = [item for item in st.session_state.working_items if item.get("is_sub", False) and item.get("parent_idx") == p_idx]
                st.session_state.working_items.append({
                    "No": f"{p_idx}.{len(siblings) + 1}", "is_sub": True, "parent_idx": p_idx, 
                    "Part Number/Model": "SUB-ITEM", "Description": "Nested component asset specification detail", 
                    "Qty": 1, "Unit Price": 0.0, "Margin": last_item.get("Margin", 0.0), "Total Price": 0.0
                })
                st.rerun()

    st.markdown("---")
    srv_c1, srv_c2 = st.columns(2)
    with srv_c1:
        ps_desc = st.text_area("Professional Service Description", "ARK Implementation Support")
        ps_price_usd = st.number_input("Professional Service (USD)", min_value=0.0, value=0.0)
    with srv_c2:
        ms_desc = st.text_area("Managed Service Description", "ARK Premium 24/7 Monitoring")
        ms_price_usd = st.number_input("Managed Service (USD)", min_value=0.0, value=0.0)

    # --- MATH ENGINE PIPELINE ---
    item_subtotal_base = sum([float(item.get("Total Price") or 0.0) for item in st.session_state.working_items if not item.get("is_sub", False)])
    global_subtotal_base = item_subtotal_base + ((ps_price_usd + ms_price_usd) * conversion_multiplier)
    
    global_discount_base = st.sidebar.number_input(f"Discount ({currency_selection})", min_value=0.0, value=0.0)
    subtotal_after_disc = max(0.0, global_subtotal_base - global_discount_base)
    global_tax_pct = st.sidebar.number_input("Tax (%)", min_value=0.0, value=5.0)
    calculated_tax = subtotal_after_disc * (global_tax_pct / 100.0)
    calculated_grand_total = subtotal_after_disc + calculated_tax
    
    st.sidebar.markdown(f"**Gross Subtotal:** {currency_symbol}{global_subtotal_base:,.2f}")
    st.sidebar.markdown(f"**Tax Pool:** {currency_symbol}{calculated_tax:,.2f}")
    st.sidebar.markdown(f"### **Grand Total:** {currency_symbol}{calculated_grand_total:,.2f}")

    action_c1, action_c2 = st.columns(2)
    if action_c1.button("💾 Persist Document Configuration (Save Draft)"):
        with get_db() as conn:
            conn.execute("""
                INSERT INTO quotations (po_number, creator_id, customer_name, project_name, attention_person, attention_email, attention_phone, status, issue_date, validity, lead_time, payment_term, terms_conditions, subtotal, discount, tax, grand_total, currency_unit, exchange_rate, items_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (quotation_auto_gen, current_user["id"], client_company, project_title, attn_person, attn_email, attn_phone, str(issue_date), validity_bound, lead_time_frame, payment_terms_desc, terms_and_cond, global_subtotal_base, global_discount_base, calculated_tax, calculated_grand_total, currency_selection, exchange_rate, json.dumps(st.session_state.working_items)))
            conn.commit()
        st.success("Draft archived.")

    if action_c2.button("🖨️ Compile Official Corporate PDF Engine Asset"):
        if uploaded_logo_file is not None:
            logo_bytes = uploaded_logo_file.read()
            encoded_logo = base64.b64encode(logo_bytes).decode('utf-8')
            mime_type = uploaded_logo_file.type
            logo_src_uri = f"data:{mime_type};base64,{encoded_logo}"
        else:
            logo_src_uri = "https://arktechsolutions.net/wp-content/themes/wp-ark/assets/img/logo-ark.png"

        html_table_rows = ""
        for item in st.session_state.working_items:
            row_class = "class='sub-row'" if item.get("is_sub", False) else ""
            indent_prefix = "└── " if item.get("is_sub", False) else ""
            qty = float(item.get("Qty") or 1)
            u_p = float(item.get("Unit Price") or 0.0)
            
            try: m_pct = float(item.get("Margin") or 0.0) / 100.0
            except: m_pct = 0.0
                
            final_unit_price = u_p / (1 - m_pct) if m_pct < 1.0 else u_p
            converted_unit_price = final_unit_price * conversion_multiplier
            converted_total_price = item.get("Total Price") or 0.0
            
            html_table_rows += f"""
            <tr {row_class}>
                <td style="text-align: center;">{item.get('No') or ''}</td>
                <td style="white-space: nowrap;">{item.get('Part Number/Model') or ''}</td>
                <td>{indent_prefix}{item.get('Description') or ''}</td>
                <td style="text-align: center;">{int(qty)}</td>
                <td class="num-cell">{currency_symbol}{converted_unit_price:,.2f}</td>
                <td class="num-cell" style="font-weight: bold;">{currency_symbol}{converted_total_price:,.2f}</td>
            </tr>
            """
            
        if ps_price_usd > 0:
            ps_conv = ps_price_usd * conversion_multiplier
            html_table_rows += f"<tr><td style='text-align:center;'>-</td><td>PS-SERVICE</td><td>{ps_desc}</td><td style='text-align:center;'>1</td><td class='num-cell'>{currency_symbol}{ps_conv:,.2f}</td><td class='num-cell' style='font-weight:bold;'>{currency_symbol}{ps_conv:,.2f}</td></tr>"
        if ms_price_usd > 0:
            ms_conv = ms_price_usd * conversion_multiplier
            html_table_rows += f"<tr><td style='text-align:center;'>-</td><td>MS-SERVICE</td><td>{ms_desc}</td><td style='text-align:center;'>1</td><td class='num-cell'>{currency_symbol}{ms_conv:,.2f}</td><td class='num-cell' style='font-weight:bold;'>{currency_symbol}{ms_conv:,.2f}</td></tr>"

        exchange_rate_notice = f"<div style='font-size:8.5pt; color:#4b5563; margin-bottom:12px;'>🌐 <strong>Conversion Profile:</strong> 1 USD = {exchange_rate:,.2f} MMK</div>" if currency_selection == "MMK" else ""

        full_printable_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                @page {{ size: A4; margin: 15mm 15mm 15mm 12mm; }}
                body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #1f2937; font-size: 9pt; line-height: 1.5; padding-right: 5px; }}
                
                .brand-header-center {{ width: 100%; margin-bottom: 25px; text-align: center; }}
                .logo-container-center {{ margin-bottom: 12px; }}
                .logo-img {{ max-height: 60px; display: inline-block; object-fit: contain; }}
                .address-text-center {{ font-size: 8.5pt; color: #4b5563; line-height: 1.5; margin: 0 auto; max-width: 85%; text-align: center; }}
                
                .title-bar {{ background-color: #00a8e8; color: white; padding: 10px; font-size: 14pt; font-weight: bold; text-transform: uppercase; margin-bottom: 20px; text-align: center; border-radius: 3px; }}
                
                .meta-table {{ width: 100%; margin-bottom: 25px; border-collapse: collapse; }}
                .meta-table td {{ border: 1px solid #e5e7eb; padding: 10px; vertical-align: top; width: 50%; background-color: #fafafa; }}
                
                .items-table {{ width: 100%; border-collapse: collapse; margin-top: 15px; page-break-inside: auto; }}
                .items-table tr {{ page-break-inside: avoid; page-break-after: auto; }}
                .items-table th {{ background-color: #1f2937; color: white; padding: 10px 6px; font-size: 9pt; text-transform: uppercase; border: 1px solid #1f2937; font-weight: bold; }}
                .items-table td {{ border: 1px solid #e5e7eb; padding: 8px 6px; vertical-align: top; font-size: 8.5pt; }}
                
                .col-no {{ width: 5%; }}
                .col-qty {{ width: 6%; }}
                
                .num-cell {{ text-align: right; white-space: nowrap; }}
                .sub-row td {{ background-color: #f9fafb; color: #4b5563; font-style: italic; }}
                
                .totals-container {{ width: 100%; margin-top: 25px; display: block; }}
                .totals-table {{ width: 55%; margin-left: auto; border-collapse: collapse; }}
                .totals-table td {{ padding: 8px; border-bottom: 1px solid #e5e7eb; font-size: 9pt; }}
                .grand-total-row {{ background-color: #00a8e8; color: white; font-weight: bold; }}
                .grand-total-row td {{ border: none; }}
                
                .footer-notes {{ margin-top: 35px; font-size: 8.5pt; color: #4b5563; border-top: 1px solid #e5e7eb; padding-top: 15px; page-break-inside: avoid; }}
            </style>
        </head>
        <body>
            <div class="brand-header-center">
                <div class="logo-container-center">
                    <img src="{logo_src_uri}" class="logo-img">
                </div>
                <div class="address-text-center">
                    <strong>ARK Premium Solutions Limited</strong><br>
                    Corporate Office: 12th Floor, Times City (Office Tower-2), Kamayut, Yangon, Myanmar.<br>
                    Contact Hotlines: +95 9 445830101 | info@arktechsolutions.net
                </div>
            </div>
            
            <div class="title-bar">Commercial Quotation</div>
            
            <table class="meta-table">
                <tr>
                    <td>
                        <strong>Prepared For:</strong><br>
                        <span style="font-size: 10pt; font-weight: bold; color: #111;">{client_company}</span><br>
                        Attn: {attn_person}<br>
                        Email: {attn_email} | Tel: {attn_phone}
                    </td>
                    <td>
                        <strong>Reference Context Ledger:</strong><br>
                        Quotation ID Ref: <strong>{quotation_auto_gen}</strong><br>
                        Generation Timestamp: {issue_date}<br>
                        Validity Scope Limit: {validity_bound}<br>
                        Base Operational Currency: {currency_selection}
                    </td>
                </tr>
            </table>

            {exchange_rate_notice}

            <table class="items-table">
                <thead>
                    <tr>
                        <th class="col-no">No</th>
                        <th>Part Number</th>
                        <th>Description</th>
                        <th class="col-qty">Qty</th>
                        <th style="text-align: right;">Unit Price</th>
                        <th style="text-align: right;">Total Price</th>
                    </tr>
                </thead>
                <tbody>
                    {html_table_rows}
                </tbody>
            </table>

            <div class="totals-container">
                <table class="totals-table">
                    <tr>
                        <td>Gross Framework Subtotal:</td>
                        <td style="text-align: right; font-weight: 500; white-space: nowrap;">{currency_symbol}{global_subtotal_base:,.2f}</td>
                    </tr>
                    <tr>
                        <td>Global Aggregate Discount Adjustment:</td>
                        <td style="text-align: right; color: #dc2626; white-space: nowrap;">-{currency_symbol}{global_discount_base:,.2f}</td>
                    </tr>
                    <tr>
                        <td>Commercial Tax Pool Value ({global_tax_pct}%):</td>
                        <td style="text-align: right; white-space: nowrap;">{currency_symbol}{calculated_tax:,.2f}</td>
                    </tr>
                    <tr class="grand-total-row">
                        <td>Grand Total ({currency_selection}):</td>
                        <td style="text-align: right; font-size: 10.5pt; white-space: nowrap;">{currency_symbol}{calculated_grand_total:,.2f}</td>
                    </tr>
                </table>
            </div>

            <div class="footer-notes">
                <strong>Commercial Delivery Terms & Scope:</strong><br>
                Estimated Production Delivery Lead Time: {lead_time_frame}<br>
                Target Execution Payment Schedule Terms: {payment_terms_desc}<br><br>
                <strong>Operational Provisions & Custom Legal Scope:</strong><br>
                {terms_and_cond.replace('\n', '<br>')}
            </div>
        </body>
        </html>
        """
        
        pdf_filename = f"ARK_Quotation_{quotation_auto_gen}.pdf"
        HTML(string=full_printable_html).write_pdf(pdf_filename)
        
        with open(pdf_filename, "rb") as f:
            st.download_button(label="📥 Download Clean Untruncated PDF Bundle", data=f.read(), file_name=pdf_filename, mime="application/pdf")
            
        with get_db() as conn:
            conn.execute("""
                INSERT INTO quotations (po_number, creator_id, customer_name, project_name, attention_person, attention_email, attention_phone, status, issue_date, validity, lead_time, payment_term, terms_conditions, subtotal, discount, tax, grand_total, currency_unit, exchange_rate, items_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'SUBMITTED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (quotation_auto_gen, current_user["id"], client_company, project_title, attn_person, attn_email, attn_phone, str(issue_date), validity_bound, lead_time_frame, payment_terms_desc, terms_and_cond, global_subtotal_base, global_discount_base, calculated_tax, calculated_grand_total, currency_selection, exchange_rate, json.dumps(st.session_state.working_items)))
            conn.commit()
        st.success("PDF payload built with complete formatting vectors.")