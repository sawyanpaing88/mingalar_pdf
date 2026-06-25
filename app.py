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
    .parent-row-box { background-color: #f1f5f9; padding: 12px; border-radius: 6px; margin-bottom: 15px; border-left: 4px solid #1e293b; }
    .sub-row-box { background-color: #ffffff; padding: 8px 12px; border-radius: 4px; margin: 6px 0 6px 20px; border-left: 3px solid #00a8e8; border: 1px solid #e2e8f0; }
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
            CREATE TABLE IF NOT EXISTS quotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                po_number TEXT UNIQUE NOT NULL,
                creator_id INTEGER,
                customer_name TEXT,
                project_name TEXT,
                attention_person TEXT,
                status TEXT,
                grand_total REAL,
                items_json TEXT,
                FOREIGN KEY(creator_id) REFERENCES users(id)
            )
        """)
        conn.commit()

init_db()

def hash_pwd(password):
    return hashlib.sha256(password.encode()).hexdigest()

if "user" not in st.session_state: st.session_state.user = None
if "default_logo_base64" not in st.session_state: st.session_state.default_logo_base64 = None

# --- AUTHENTICATION WALL ---
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
                    st.session_state.user = dict(res)
                    st.success("Access Granted!")
                    st.rerun()
                else:
                    st.error("Invalid credentials.")
    st.stop()

current_user = st.session_state.user

# Sync profile updates
with get_db() as conn:
    db_u = conn.execute("SELECT * FROM users WHERE id=?", (current_user["id"],)).fetchone()
    if db_u: current_user = dict(db_u)

st.sidebar.markdown(f"**Entity:** `{current_user['email']}` | **Clearance:** `{current_user['role']}`")
if st.sidebar.button("Logout Session"):
    st.session_state.user = None
    st.rerun()

nav_options = ["🏠 Dashboard Console", "➕ Build New Quotation Module", "👤 User Profile Management"]
page_selection = st.sidebar.radio("Navigation Directives", nav_options)

# ==========================================
# 👤 USER PROFILE MANAGEMENT
# ==========================================
if page_selection == "👤 User Profile Management":
    st.header("👤 User Account Profile Configuration")
    prof_name = st.text_input("Full Professional Name", current_user.get("name", ""))
    prof_desig = st.text_input("Corporate Designation / Title", current_user.get("designation", ""))
    prof_phone = st.text_input("Direct Phone Line", current_user.get("phone", ""))
    
    if current_user.get("signature_b64"):
        st.markdown("**Active Signature:**")
        st.markdown(f'<img src="{current_user["signature_b64"]}" style="max-height: 80px; background: white;">', unsafe_allow_html=True)
    
    uploaded_sig = st.file_uploader("Upload New Signature Image (PNG/JPG)", type=["png", "jpg", "jpeg"])
    
    if st.button("💾 Save Profile Changes"):
        sig_payload = current_user.get("signature_b64", "")
        if uploaded_sig is not None:
            sig_payload = f"data:{uploaded_sig.type};base64,{base64.b64encode(uploaded_sig.getvalue()).decode('utf-8')}"
            
        with get_db() as conn:
            conn.execute("UPDATE users SET name=?, designation=?, phone=?, signature_b64=? WHERE id=?", (prof_name, prof_desig, prof_phone, sig_payload, current_user["id"]))
            conn.commit()
        st.success("Profile records saved successfully.")
        st.rerun()

# ==========================================
# 🏠 DASHBOARD ENGINE
# ==========================================
elif page_selection == "🏠 Dashboard Console":
    st.header("📊 Activity Metrics Control Dashboard")
    with get_db() as conn:
        quotes = conn.execute("SELECT * FROM quotations").fetchall()
    if quotes:
        for row in quotes:
            st.markdown(f"**Quotation #:** `{row['po_number']}` | **Customer:** {row['customer_name']} | **Total:** {row['grand_total']:,.2f} | **Status:** `{row['status']}`")
    else:
        st.info("No documents compiled yet.")

# ==========================================
# ➕ ITEMIZATION MODULE (RESTORED OLD TREE UI)
# ==========================================
elif page_selection == "➕ Build New Quotation Module":
    st.header("➕ Document Generation Sandbox")
    quotation_auto_gen = f"ARK-QT-{datetime.now().strftime('%Y%m')}-{random.randint(100000, 999999)}"
    
    currency_selection = st.sidebar.selectbox("Currency Mode", ["USD", "MMK"])
    exchange_rate = st.sidebar.number_input("Exchange Rate (1 USD to MMK)", min_value=1.0, value=3250.0)
    currency_symbol = "USD " if currency_selection == "USD" else "MMK "
    conversion_multiplier = exchange_rate if currency_selection == "MMK" else 1.0
    
    st.sidebar.markdown("### 🖼 *Corporate Branding*")
    uploaded_logo_file = st.sidebar.file_uploader("Upload Logo Banner", type=["png", "jpg", "jpeg"])
    if uploaded_logo_file:
        st.session_state.default_logo_base64 = f"data:{uploaded_logo_file.type};base64,{base64.b64encode(uploaded_logo_file.getvalue()).decode('utf-8')}"

    # General Document Parameters
    client_company = st.text_input("Client Corporate Entity Name", "Acme Enterprise Corp")
    attn_person = st.text_input("Attention Person", "John Doe")
    attn_email = st.text_input("Contact Email", "johndoe@client.com")
    attn_phone = st.text_input("Contact Phone", "+959xxxxxxxxx")
    project_title = st.text_input("Project Title", "Network Overhaul Cluster")
    issue_date = st.date_input("Issue Date")
    validity_bound = st.text_input("Validity Frame", "30 Days")
    lead_time_frame = st.text_input("Lead Time", "4-6 Weeks")
    payment_terms_desc = st.text_input("Payment Terms", "50% Advance, 50% Upon Delivery")
    terms_and_cond = st.text_area("Custom Terms & Conditions Scope", "1. Standard ARK Warranty applies.\n2. Prices exclude deployment unless itemized below.")

    # RESTORED PREVIOUS TREE STATE STRUCTURING
    if "structure_blocks" not in st.session_state:
        st.session_state.structure_blocks = [
            {
                "id": 1,
                "title": "Main Core Infrastructure Switching Hardware",
                "subs": [
                    {"part": "C9300-48TX-E", "desc": "Catalyst 9300 48-port Layer 3 Managed Network Node Switch Base", "qty": 2, "price": 4200.0, "margin": 15.0},
                    {"part": "FOC-ENG-DEP", "desc": "Free Deployment, Installation, Metric Optimization Matrix Verification Engineering Services", "qty": 1, "price": 0.0, "margin": 0.0}
                ]
            }
        ]

    st.markdown("### 🛠 Itemization Matrix Framework (Nesting & Tree Rules)")
    
    updated_blocks = []
    for b_idx, block in enumerate(st.session_state.structure_blocks):
        p_num = b_idx + 1
        st.markdown(f'<div class="parent-row-box">', unsafe_allow_html=True)
        col1, col2 = st.columns([8, 2])
        with col1:
            new_title = st.text_input(f"Row Divider / Parent Heading Group {p_num}", block["title"], key=f"p_title_{block['id']}")
        with col2:
            st.markdown("<br>", unsafe_allow_html=True)
            delete_block = st.button("❌ Remove Group", key=f"del_p_{block['id']}")
            
        if delete_block:
            continue

        updated_subs = []
        for s_idx, sub in enumerate(block["subs"]):
            st.markdown(f'<div class="sub-row-box">', unsafe_allow_html=True)
            s_num = f"{p_num}.{s_idx + 1}"
            sc1, sc2, sc3, sc4, sc5 = st.columns([2, 4, 1, 2, 2])
            
            with sc1:
                sub_part = st.text_input(f"Part Number ({s_num})", sub["part"], key=f"part_{block['id']}_{s_idx}")
            with sc2:
                sub_desc = st.text_input(f"Item Description Specification ({s_num})", sub["desc"], key=f"desc_{block['id']}_{s_idx}")
            with sc3:
                sub_qty = st.number_input(f"Qty", min_value=1, value=int(sub["qty"]), key=f"qty_{block['id']}_{s_idx}")
            with sc4:
                sub_price = st.number_input(f"Base Unit Price (USD)", min_value=0.0, value=float(sub["price"]), format="%.2f", key=f"price_{block['id']}_{s_idx}")
            with sc5:
                sub_margin = st.number_input(f"Margin %", min_value=0.0, max_value=99.0, value=float(sub["margin"]), key=f"margin_{block['id']}_{s_idx}")
                
            st.markdown('</div>', unsafe_allow_html=True)
            updated_subs.append({"part": sub_part, "desc": sub_desc, "qty": sub_qty, "price": sub_price, "margin": sub_margin})
            
        col_actions = st.columns([3, 7])
        with col_actions[0]:
            if st.button(f"➕ Append Sub Item to Group {p_num}", key=f"add_sub_{block['id']}"):
                updated_subs.append({"part": "", "desc": "", "qty": 1, "price": 0.0, "margin": 0.0})
                st.rerun()
                
        st.markdown('</div>', unsafe_allow_html=True)
        updated_blocks.append({"id": block["id"], "title": new_title, "subs": updated_subs})

    if st.button("➕ Append New Row Divider / Heading Group"):
        new_id = max([b["id"] for b in st.session_state.structure_blocks]) + 1 if st.session_state.structure_blocks else 1
        updated_blocks.append({"id": new_id, "title": "New Equipment/Service Cluster Block", "subs": []})
        st.session_state.structure_blocks = updated_blocks
        st.rerun()
        
    st.session_state.structure_blocks = updated_blocks

    # --- TAX CONFIGURATIONS ---
    st.sidebar.markdown("### 🏛 Tax Configuration Options")
    tax_options_chosen = st.sidebar.multiselect("Select Tax Frameworks to Apply", ["Commercial Tax", "Withholding Tax (WHT)"], default=["Commercial Tax"])
    
    comm_tax_pct = st.sidebar.number_input("Commercial Tax (%)", min_value=0.0, value=5.0) if "Commercial Tax" in tax_options_chosen else 0.0
    wht_tax_pct = st.sidebar.number_input("Withholding Tax (%)", min_value=0.0, value=2.0) if "Withholding Tax (WHT)" in tax_options_chosen else 0.0

    # Calculate Totals Matrix
    gross_subtotal = 0.0
    table_rows_html = ""

    for b_idx, block in enumerate(st.session_state.structure_blocks):
        p_num = b_idx + 1
        # Divider Line
        table_rows_html += f'''
        <tr style="background-color: #f8fafc; font-weight: 600; border-top: 1px solid #e2e8f0;">
            <td style="text-align: center; padding: 8px;">{p_num}</td>
            <td colspan="5" style="padding: 8px; color: #1e293b;">{block["title"]}</td>
        </tr>
        '''
        for s_idx, sub in enumerate(block["subs"]):
            s_num = f"{p_num}.{s_idx + 1}"
            raw_p = float(sub["price"])
            qty = int(sub["qty"])
            margin_factor = float(sub["margin"]) / 100.0
            
            # Unit Calculation applying Margin Multipliers
            selling_unit_price = raw_p / (1.0 - margin_factor) if margin_factor < 1.0 else raw_p
            calculated_total = (selling_unit_price * qty) * conversion_multiplier
            gross_subtotal += calculated_total
            
            # FOC Detection Flag Injection
            if raw_p == 0.0:
                unit_str = '<span style="color:#059669; font-weight:bold; background:#ecfdf5; padding:2px 5px; border-radius:3px;">FOC</span>'
                total_str = '<span style="color:#059669; font-weight:bold; background:#ecfdf5; padding:2px 5px; border-radius:3px;">FOC</span>'
            else:
                unit_str = f"{currency_symbol}{selling_unit_price * conversion_multiplier:,.2f}"
                total_str = f"{currency_symbol}{calculated_total:,.2f}"

            table_rows_html += f'''
            <tr>
                <td style="text-align: center; padding: 8px; color: #64748b;">{s_num}</td>
                <td style="font-family: monospace; padding: 8px; color: #334155;">{sub["part"]}</td>
                <td style="padding: 8px; font-style: italic; color: #334155;">{sub["desc"]}</td>
                <td style="text-align: center; padding: 8px;">{qty}</td>
                <td style="text-align: right; padding: 8px;">{unit_str}</td>
                <td style="text-align: right; padding: 8px; font-weight: 600;">{total_str}</td>
            </tr>
            '''

    calculated_comm_tax = gross_subtotal * (comm_tax_pct / 100.0)
    calculated_wht_tax = gross_subtotal * (wht_tax_pct / 100.0)
    grand_total_calculated = gross_subtotal + calculated_comm_tax - calculated_wht_tax

    st.sidebar.markdown(f"**Subtotal:** {currency_symbol}{gross_subtotal:,.2f}")
    if comm_tax_pct > 0: st.sidebar.markdown(f"**Commercial Tax:** {currency_symbol}{calculated_comm_tax:,.2f}")
    if wht_tax_pct > 0: st.sidebar.markdown(f"**WHT Reduction:** -{currency_symbol}{calculated_wht_tax:,.2f}")
    st.sidebar.markdown(f"### **Grand Total:** {currency_symbol}{grand_total_calculated:,.2f}")

    if st.button("🖨 Compile Official Corporate PDF Engine Asset"):
        logo_html = f'<img src="{st.session_state.default_logo_base64}" style="max-height:65px;">' if st.session_state.default_logo_base64 else '<h2>ARK PREMIUM SOLUTION</h2>'

        tax_rows_markup = ""
        if comm_tax_pct > 0:
            tax_rows_markup += f'<tr><td style="padding:4px 0; color:#475569;">Commercial Tax ({comm_tax_pct}%):</td><td style="text-align:right; padding:4px 0; font-weight:600;">{currency_symbol}{calculated_comm_tax:,.2f}</td></tr>'
        if wht_tax_pct > 0:
            tax_rows_markup += f'<tr><td style="padding:4px 0; color:#475569;">Withholding Tax (WHT {wht_tax_pct}%):</td><td style="text-align:right; padding:4px 0; font-weight:600; color:#b91c1c;">-{currency_symbol}{calculated_wht_tax:,.2f}</td></tr>'

        sig_img_markup = f'<img src="{current_user["signature_b64"]}" style="max-height:55px; display:block; margin-top:5px;">' if current_user.get("signature_b64") else '<div style="height:45px; color:#cbd5e1; font-style:italic;">Signature Pending</div>'

        html_document = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                @page {{
                    size: A4; margin: 15mm;
                    @bottom-right {{ content: "Page " counter(page) " of " counter(pages); font-family: Arial; font-size: 8pt; color: #64748b; }}
                }}
                body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #1e293b; font-size: 9pt; line-height: 1.5; }}
                .header-container {{ text-align: center; margin-bottom: 15px; }}
                .header-address {{ font-size: 8pt; color: #475569; line-height: 1.4; }}
                .brand-title {{ font-weight: bold; color: #00a8e8; font-size: 12pt; margin-bottom: 2px; }}
                .divider {{ border-bottom: 2px solid #00a8e8; margin: 10px 0; }}
                
                .meta-table {{ width: 100%; border-collapse: collapse; margin-bottom: 15px; }}
                .card-box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px; padding: 10px; font-size: 8.5pt; vertical-align: top; width: 50%; }}
                
                .data-table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
                .data-table th {{ background-color: #1e293b; color: white; font-weight: 500; font-size: 8pt; padding: 8px; text-transform: uppercase; text-align: left; }}
                .data-table td {{ font-size: 8.5pt; border-bottom: 1px solid #f1f5f9; }}
                
                .breakdown-container {{ display: table; width: 100%; margin-top: 15px; page-break-inside: avoid; }}
                .terms-box {{ display: table-cell; width: 55%; vertical-align: top; padding-right: 20px; }}
                .totals-box {{ display: table-cell; width: 45%; vertical-align: top; }}
                
                .totals-table {{ width: 100%; border-collapse: collapse; font-size: 8.5pt; }}
                .grand-total-tr {{ background-color: #00a8e8; color: white; font-weight: bold; font-size: 10pt; }}
                
                .footer-terms {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px; font-size: 7.5pt; color: #475569; }}
                
                .signatory-left-container {{ margin-top: 30px; text-align: left; page-break-inside: avoid; width: 260px; float: left; }}
                .sig-line {{ border-bottom: 1px dashed #cbd5e1; padding-bottom: 5px; margin-bottom: 5px; }}
            </style>
        </head>
        <body>
            <div class="header-container">
                <div class="header-logo">{logo_html}</div>
                <div class="header-address">
                    <div class="brand-title">ARK Premium Solution Limited</div>
                    <strong>ARK Corporate Office:</strong> 18th floor, Times City(office tower-2), Kamayut, Yangon, Myanmar.<br>
                    <strong>ARK Headquarters Office:</strong> 91, Shwe Taung Kyar 1st Street, Golden Valley 1, Bahan, Yangon, Myanmar.<br>
                    <strong>ARK Thailand Office:</strong> 1, Soi Ramkhamhaeng 118 Yaek 33-3, Saphan Sung 10240, Bangkok, Thailand.<br>
                    <strong>Web:</strong> www.arktechsolutions.net | <strong>Tel:</strong> +95 9 445830101
                </div>
            </div>

            <div class="divider"></div>
            <h2 style="font-size:16pt; font-weight:normal; margin:0 0 10px 0;">Commercial Quotation</h2>

            <table class="meta-table">
                <tr>
                    <td class="card-box" style="margin-right:10px;">
                        <strong style="color:#64748b; text-transform:uppercase; font-size:7.5pt;">Prepared For</strong><br>
                        <strong>{client_company}</strong><br>
                        Attn: {attn_person}<br>
                        Email: {attn_email} | Phone: {attn_phone}
                    </td>
                    <td class="card-box">
                        <strong style="color:#64748b; text-transform:uppercase; font-size:7.5pt;">Quotation References</strong><br>
                        <strong>Ref:</strong> {quotation_auto_gen}<br>
                        <strong>Project Name:</strong> {project_title}<br>
                        <strong>Date:</strong> {issue_date.strftime('%Y-%m-%d')} | <strong>Validity:</strong> {validity_bound}
                    </td>
                </tr>
            </table>

            <table class="data-table">
                <thead>
                    <tr>
                        <th style="width: 6%; text-align: center;">No</th>
                        <th style="width: 20%;">Part Number</th>
                        <th style="width: 44%;">Functional Itemization / SPECIFICATIONS</th>
                        <th style="width: 6%; text-align: center;">Qty</th>
                        <th style="width: 12%; text-align: right;">Unit Price</th>
                        <th style="width: 12%; text-align: right;">Total Price</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows_html}
                </tbody>
            </table>

            <div class="breakdown-container">
                <div class="terms-box">
                    <div class="footer-terms">
                        <strong style="font-size:8.5pt; color:#0f172a; display:block; margin-bottom:5px;">Commercial Logistics Terms & Governance Conditions:</strong>
                        <table style="width:100%; border-collapse:collapse; line-height:1.5;">
                            <tr><td style="width:15px; vertical-align:top; color:#00a8e8; font-weight:bold;">1.</td><td><strong>Delivery Lead-Time Windows:</strong> Equipment delivery windows are anticipated at approximately <strong>{lead_time_frame}</strong> following official project sign-off matrix rules.</td></tr>
                            <tr><td style="width:15px; vertical-align:top; color:#00a8e8; font-weight:bold;">2.</td><td><strong>Explicit Milestone Commitments:</strong> All relative monetary settlement routes must maintain strict compliance with: <strong>{payment_terms_desc}</strong>.</td></tr>
                            <tr><td style="width:15px; vertical-align:top; color:#00a8e8; font-weight:bold;">3.</td><td><strong>Additional Execution Scope and Framework Matrix Parameters:</strong><br>
                                <div style="margin-top:4px; padding-left:8px; border-left:2px solid #00a8e8; font-style:italic; color:#334155;">
                                    {terms_and_cond.replace('\n', '<br>')}
                                </div>
                            </td></tr>
                        </table>
                    </div>
                </div>
                
                <div class="totals-box">
                    <table class="totals-table">
                        <tr>
                            <td style="padding:4px 0; color:#64748b;">Gross Subtotal:</td>
                            <td style="text-align:right; padding:4px 0; font-weight:600;">{currency_symbol}{gross_subtotal:,.2f}</td>
                        </tr>
                        {tax_rows_markup}
                        <tr class="grand-total-tr">
                            <td style="padding:7px; color:white;">Grand Total:</td>
                            <td style="text-align:right; padding:7px; color:white; white-space:nowrap;">{currency_symbol}{grand_total_calculated:,.2f}</td>
                        </tr>
                    </table>
                </div>
            </div>

            <div class="signatory-left-container">
                <div class="sig-line">
                    <span style="font-size:7.5pt; font-weight:bold; color:#64748b; text-transform:uppercase;">Issued & Authorized By:</span>
                    {sig_img_markup}
                </div>
                <div style="font-weight:bold; color:#0f172a; margin-top:3px;">{current_user.get("name", "Authorized Signatory")}</div>
                <div style="color:#475569; font-size:8pt;">{current_user.get("designation", "Account Operations Manager")}</div>
                <div style="color:#64748b; font-size:7.5pt;">
                    Email: {current_user["email"]}<br>
                    Phone: {current_user.get("phone", "N/A")}
                </div>
            </div>
            <div style="clear:both;"></div>
        </body>
        </html>
        """
        
        pdf_filename = f"ARK_Quotation_{quotation_auto_gen}.pdf"
        try:
            HTML(string=html_document).write_pdf(pdf_filename)
            with open(pdf_filename, "rb") as f:
                st.sidebar.download_button("📥 Download Finalized PDF Quote Asset", data=f.read(), file_name=pdf_filename, mime="application/pdf")
            st.sidebar.success("🎉 PDF Compiled Successfully!")
            
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO quotations (po_number, creator_id, customer_name, project_name, attention_person, status, grand_total, items_json) VALUES (?,?,?,?,?,?,?,?)",
                    (quotation_auto_gen, current_user["id"], client_company, project_title, attn_person, "COMPILED", grand_total_calculated, "[]")
                )
                conn.commit()
        except Exception as e:
            st.error(f"Engine compilation failure: {e}")
