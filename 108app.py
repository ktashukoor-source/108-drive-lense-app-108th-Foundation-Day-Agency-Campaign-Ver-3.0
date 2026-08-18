This makes perfect sense. The old code had a beautifully comprehensive `cat_map` dictionary and a highly specific rule engine for evaluating Motor Body Types and GVW, which was lost when we rebuilt the validation layer.

I have fully merged that precise **LOB extraction** (`pol_num[6:12]`), the complete **`cat_map` dictionary**, and the **detailed Motor Categorization logic** (checking for Taxis, Staff Buses, and Goods Carrying GVW <= 7500) back into our latest, ultra-secure version of the app.

Here is the ultimate, fully merged `app.py`. Copy this and overwrite your file:

```python
import streamlit as st
import pandas as pd
import re
from io import BytesIO
from datetime import datetime

# --- Configuration & Campaign Dates ---
CAMPAIGN_START = pd.to_datetime('2026-07-23')
CAMPAIGN_END = pd.to_datetime('2026-08-22')

st.set_page_config(page_title="108 Drive Lense", page_icon="🏆", layout="wide")

# --- Helper Functions ---
def clean_policy_numbers(df, col_name):
    """Aggressively removes all special characters, spaces, and punctuation from policy numbers."""
    if col_name in df.columns:
        df[col_name] = df[col_name].apply(lambda x: re.sub(r'[^a-zA-Z0-9]', '', str(x)) if pd.notna(x) else x)
    return df

def process_campaign_data(prem_file, mot_file, ho_master_file):
    try:
        # 1. LOAD PREMIUM REGISTER
        prem_df = pd.read_csv(prem_file, dtype=str)
        prem_df.columns = prem_df.columns.str.strip().str.upper()

        required_prem_cols = ['POLICY NUMBER', 'ENDORSEMENT NUMBER', 'COLLECTION DATE', 'SOURCE INDICATOR']
        missing_prem = [col for col in required_prem_cols if col not in prem_df.columns]
        if missing_prem:
            return f"Validation Error: Premium Register missing columns: {', '.join(missing_prem)}.", None, None, None

        if 'AGENT CODE' in prem_df.columns and 'DEV OFFICER CODE' in prem_df.columns:
            prem_df['AGENT CODE'] = prem_df['AGENT CODE'].fillna('Unknown').str.strip()
            direct_mask = (prem_df['AGENT CODE'].isin(['', 'Unknown', 'NA'])) & (prem_df['DEV OFFICER CODE'].notna()) & (prem_df['DEV OFFICER CODE'].str.strip() != '')
            prem_df.loc[direct_mask, 'AGENT CODE'] = prem_df.loc[direct_mask, 'DEV OFFICER CODE']
            if 'AGENT NAME' in prem_df.columns:
                prem_df.loc[direct_mask, 'AGENT NAME'] = 'DIRECT'

        prem_df = clean_policy_numbers(prem_df, 'POLICY NUMBER')
        prem_df['COLLECTION DATE'] = pd.to_datetime(prem_df['COLLECTION DATE'], errors='coerce') 

        # 2. LOAD MOTOR DETAILS
        mot_df = pd.DataFrame()
        if mot_file is not None:
            mot_df = pd.read_csv(mot_file, dtype=str)
            mot_df.columns = mot_df.columns.str.strip().str.upper()
            
            required_mot_cols = ['POLICY_NUMBER', 'CLASS_OF_VEHICLE', 'PRODUCT_NAME']
            missing_mot = [col for col in required_mot_cols if col not in mot_df.columns]
            if missing_mot:
                 return f"Validation Error: Motor Details missing columns: {', '.join(missing_mot)}.", None, None, None
            
            mot_df = clean_policy_numbers(mot_df, 'POLICY_NUMBER')
            mot_df = clean_policy_numbers(mot_df, 'PREVIOUS_POLICY_NO')

        # 3. LOAD HO MASTER LIST
        ho_fresh_policies = set()
        if ho_master_file is not None:
            try:
                ho_df = pd.read_excel(ho_master_file, sheet_name='Total', dtype=str)
                ho_df.columns = ho_df.columns.str.strip().str.upper()
                
                if 'POLICY_NUMBER' not in ho_df.columns:
                    ho_df = pd.read_excel(ho_master_file, sheet_name='Total', dtype=str, header=1)
                    ho_df.columns = ho_df.columns.str.strip().str.upper()
                
                if 'POLICY_NUMBER' in ho_df.columns and 'TYPE_OF_POLICIES' in ho_df.columns:
                    ho_df = clean_policy_numbers(ho_df, 'POLICY_NUMBER')
                    fresh_mask = ho_df['TYPE_OF_POLICIES'].str.strip().str.upper() == 'NEW POLICY'
                    ho_fresh_policies = set(ho_df.loc[fresh_mask, 'POLICY_NUMBER'].dropna().tolist())
                else:
                    return "Validation Error: HO Master List missing 'POLICY_NUMBER' or 'TYPE_OF_POLICIES'.", None, None, None
            except Exception as e:
                return f"Error reading HO Master List: {str(e)}", None, None, None

        # --- LOB CATEGORY MAP (From Original Code) ---
        cat_map = {
            '612695': (1, 4, 'New India Mediclaim'), '612628': (1, 4, 'Floater Mediclaim'), 
            '612693': (1, 4, 'Arogya Sanjeevani'), '612624': (1, 4, 'Yuva Bharat'), '692630': (1, 4, 'Overseas Travel Ease Policy'),
            '612678': (2, 3, 'Top Up Policy'), '612650': (2, 3, 'Arogya Pragati Plus'),
            '612637': (3, 5, 'Cancer Guard Policy'),
            '112686': (7, 4, 'Bharat Griha Raksha'), '112650': (7, 4, 'Bharat Griha Raksha'), 
            '112680': (7, 4, 'Bharat Sookshma Udyam Suraksha Policy'), '112687': (7, 4, 'Bharat Sookshma Udyam Suraksha Policy'),
            '112643': (8, 5, 'Bharat Laghu Udyam Suraksha Policy'), '112696': (8, 5, 'New India Bharat Flexi Laghu Udyam Suraksha'),
            '652601': (9, 2, 'Personal Accident Policy'), '672601': (9, 2, 'Personal Accident Policy'), 
            '682601': (9, 2, 'Personal Accident Policy'), '482668': (9, 2, 'Rasta Apatti Kavach (RAK) Policy'),
            '412601': (10, 3, 'Employee Compensation (WC) Policy'),
            '462689': (11, 3, 'Mahila Udyam Policy'), '462630': (11, 3, 'Bima Saathi Policy'),
            '462607': (12, 5, 'Jewellers Block Policy'),
            '482605': (13, 4, 'Householder Policy'), '482698': (13, 4, 'Griha Suvidha Policy'), 
            '482606': (13, 4, 'Shopkeepers Policy'), '482607': (13, 4, 'Office Protection Shield Policy'),
            '492607': (14, 4, 'Public Liability Policy'),
            '362641': (15, 1, 'My Cyber Policy')
        }

        # 4. INITIALIZE LOGS
        eligible_records = []
        ineligible_records = []

        # 5. RULE ENGINE
        for index, row in prem_df.iterrows():
            policy_no = str(row['POLICY NUMBER'])
            col_date = row['COLLECTION DATE']
            src_ind = str(row.get('SOURCE INDICATOR', '')).strip().upper()
            endorsement_no = str(row.get('ENDORSEMENT NUMBER', '')).strip()
            agent_code = str(row.get('AGENT CODE', 'Unknown')).strip()
            agent_name = str(row.get('AGENT NAME', 'Unknown')).strip()
            premium = float(row.get('PREMIUM AMOUNT', 0)) if pd.notna(row.get('PREMIUM AMOUNT')) else 0.0

            # Exact LOB Extraction from Old Code
            lob_col_val = str(row.get('LOB ID', '')).strip()
            lob = policy_no[6:12] if len(policy_no) >= 12 else lob_col_val
            is_motor = lob in ['312601', '312602', '312603']

            is_eligible = True
            ineligible_reason = ""
            review_needed = ""

            # Line 1 & 2 Constraints
            if pd.isna(col_date) or col_date < CAMPAIGN_START or col_date > CAMPAIGN_END:
                is_eligible = False
                ineligible_reason = "Date out of Campaign Period (Line 1)"
            elif endorsement_no != ':':
                is_eligible = False
                ineligible_reason = "Endorsement Record (Line 2)"
            elif premium < 500:
                is_eligible = False
                ineligible_reason = "Premium < 500 (Line 3)"
            else:
                # Line 4A/4B Constraints
                if not is_motor:
                    if policy_no in ho_fresh_policies:
                        pass 
                    elif 'RENEWAL' in src_ind:
                        is_eligible = False
                        ineligible_reason = f"Policy is a Renewal. Source Indicator: '{src_ind}' (Line 4A)"
                    elif 'FRESH POLICY' not in src_ind:
                        review_needed = f"Confirm if fresh business. Source Indicator is '{src_ind}' (Line 4A)."
                else:
                    if mot_df.empty:
                        review_needed = "Motor policy, but Motor Details CSV not provided."
                    else:
                        mot_matches = mot_df[mot_df['POLICY_NUMBER'] == policy_no]
                        if mot_matches.empty:
                            review_needed = "Motor policy not found in Motor Details CSV."
                        else:
                            mot_row = mot_matches.iloc[0]
                            if policy_no in ho_fresh_policies:
                                pass 
                            else:
                                prev_ins = str(mot_row.get('PREVIOUS_INSURER_NAME', '')).strip(" .,-").upper()
                                if prev_ins == 'THE NEW INDIA ASSURANCE COMPANY LTD':
                                    prev_pol = str(mot_row.get('PREVIOUS_POLICY_NO', ''))
                                    prev_pol_clean = re.sub(r'[^a-zA-Z0-9]', '', prev_pol)
                                    if len(prev_pol_clean) >= 10:
                                        try:
                                            val = int(prev_pol_clean[8:10])
                                            if val >= 25:
                                                is_eligible = False
                                                ineligible_reason = f"Previous Insurer: New India Assurance & Previous Policy digits >= 25 ({val}) (Line 4B)"
                                        except ValueError:
                                            pass

            # --- PRODUCT CATEGORIZATION ENGINE ---
            cat_id = 0
            cat_name = "Unmapped LOB"
            points = 0

            if is_eligible:
                if not is_motor:
                    if lob in cat_map:
                        cat_id, points, cat_name = cat_map[lob]
                    else:
                        review_needed += " Unrecognized Non-Motor LOB code."
                else:
                    if not mot_df.empty:
                        mot_matches = mot_df[mot_df['POLICY_NUMBER'] == policy_no]
                        if not mot_matches.empty:
                            mot_row = mot_matches.iloc[0]
                            m_prod = str(mot_row.get('PRODUCT_NAME', '')).upper()
                            m_class = str(mot_row.get('CLASS_OF_VEHICLE', '')).upper()
                            m_body = str(mot_row.get('BODY_TYPE', '')).upper()
                            m_gvw_str = str(mot_row.get('GROSS_VEHICLE_WEIGHT', '0'))
                            m_gvw = float(re.sub(r'[^0-9.]', '', m_gvw_str)) if m_gvw_str.strip() != '' else 0

                            if 'PRIVATE CAR' in m_prod:
                                if lob in ['312601', '312603']:
                                    cat_id, points, cat_name = 4, 2, 'Private Car'
                                else:
                                    is_eligible = False
                                    ineligible_reason = "Liability Only (312602) not eligible for Private Car (Line 6)"
                            elif 'COMMERCIAL VEH' in m_prod:
                                if 'GOODS CARRYING' in m_class and m_gvw <= 7500:
                                    cat_id, points, cat_name = 5, 3, 'Goods Carrying'
                                elif 'PASSENGER CARRYING' in m_class:
                                    taxi_bodies = ['SALOON', 'SEDAN', 'HATCH-BACK', 'STATION WAGON/WAGON', 'SUV', 'SPORTS CAR/SUPER CAR']
                                    if any(tb in m_body for tb in taxi_bodies):
                                        cat_id, points, cat_name = 5, 3, 'Taxis'
                                        review_needed += " Verify Seating Capacity <= 6 (Line 6)."
                                    elif 'STAFF BUS' in m_body:
                                        cat_id, points, cat_name = 6, 4, 'Staff Bus'
                                    else:
                                        is_eligible = False
                                        ineligible_reason = "Unrecognized Body Type for Passenger Carrying"
                                        review_needed = "Check manual records to verify if actual usage is Taxi (<=6) or Staff Bus (Line 6)"
                                elif 'SCHOOL BUS' in m_class:
                                    cat_id, points, cat_name = 6, 4, 'School Bus'

            # Build Final Rows
            if is_eligible and cat_id == 0:
                 # Demote unmapped eligible policies to ineligible log per original behavior
                 is_eligible = False
                 ineligible_reason = "Unmapped LOB / Missing Categorization Data (Line 5/6)"

            if is_eligible:
                cat_remark = f"Meets criteria (Rule Line 5/6). mapped to {cat_name}"
                eligible_records.append({
                    'Policy Number': policy_no,
                    'Agent Code': agent_code,
                    'Agent Name': agent_name,
                    'Premium': premium,
                    'Product Category & Nar': f"Cat {cat_id} - {cat_name}",
                    'Points': points,
                    'Remarks': cat_remark,
                    'Review Needed': review_needed.strip(),
                    'Cat_ID': cat_id # Internal mapping key
                })
            else:
                ineligible_records.append({
                    'Policy Number': policy_no,
                    'Agent Code': agent_code,
                    'Premium': premium,
                    'Reason for Ineligibility': ineligible_reason,
                    'Review Needed': review_needed.strip()
                })

        # 6. CREATE OUTPUT DATAFRAMES
        df_eligible = pd.DataFrame(eligible_records)
        df_ineligible = pd.DataFrame(ineligible_records)

        # 7. AGENT SCOREBOARD CALCULATIONS
        scoreboard = pd.DataFrame()
        if not df_eligible.empty:
            grouped = df_eligible.groupby(['Agent Code', 'Agent Name']).agg(
                Eligible_Total_Premium=('Premium', 'sum'),
                Eligible_Policy_Count=('Policy Number', 'count'),
                Total_Points=('Points', 'sum'),
                Unique_Cats=('Cat_ID', lambda x: x[x > 0].nunique())
            ).reset_index()

            score_list = []
            for _, r in grouped.iterrows():
                pts = r['Total_Points']
                cats = r['Unique_Cats']
                achieved = 'Y' if pts >= 108 and cats >= 5 else 'N'
                remark = "Achieved target!" if achieved == 'Y' else f"Missed target. Pts: {pts}/108, Cats: {cats}/5"

                score_list.append({
                    'Agent Code': r['Agent Code'],
                    'Agent Name': r['Agent Name'],
                    'Eligible Total Premium': r['Eligible_Total_Premium'],
                    'Eligible Policy Count': r['Eligible_Policy_Count'],
                    'Total Points': pts,
                    'Achieved Product Categ Eligible(Y/N)': achieved,
                    'Remark': remark
                })
            
            scoreboard = pd.DataFrame(score_list).sort_values(by='Total Points', ascending=False)
            df_eligible = df_eligible.drop(columns=['Cat_ID'])

        return None, df_eligible, df_ineligible, scoreboard

    except Exception as e:
        import traceback
        return f"A critical error occurred: {str(e)}\nTraceback: {traceback.format_exc()}", None, None, None


# --- UI Setup ---
st.title("🏆 108 Drive Lense: Campaign Analyzer \u00A9 Ver 3.1")
st.markdown("Welcome to the offline, secure data processor. Upload your exact CSV files from the core system. No data leaves your browser.")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### 1. Premium Register")
    st.info("Download Path: Dashboard -> Core reports -> Premium -> Premium Register")
    prem_file = st.file_uploader("Upload Premium CSV", type=['csv'])

with col2:
    st.markdown("### 2. Motor Details")
    st.info("Download Path: Dashboard -> Core reports -> Motor(Premium) -> Motor Business Details")
    mot_file = st.file_uploader("Upload Motor CSV", type=['csv'])

with col3:
    st.markdown('<div style="opacity: 0.4;">', unsafe_allow_html=True)
    st.markdown("### 3. HO Master List (Optional)")
    st.info("HO Master Policy List up to 11th: Upload for tracking Fresh/Renewal only.")
    ho_master_file = st.file_uploader("Upload HO Master List (.xlsx)", type=['xlsx'])
    st.markdown('</div>', unsafe_allow_html=True)

if st.button("Process Campaign Data", type="primary"):
    if not prem_file:
        st.error("Please upload the Premium Register CSV to proceed.")
    else:
        with st.spinner("Analyzing rules and processing data..."):
            error_msg, df_el, df_inel, df_score = process_campaign_data(prem_file, mot_file, ho_master_file)
            
            if error_msg:
                st.error(error_msg)
            else:
                st.success("Processing Complete!")
                
                tab1, tab2, tab3 = st.tabs(["Agent Scoreboard", "Eligible Policies", "Ineligible Policies"])
                
                with tab1:
                    st.dataframe(df_score, use_container_width=True)
                with tab2:
                    st.dataframe(df_el, use_container_width=True)
                with tab3:
                    st.dataframe(df_inel, use_container_width=True)
                
                # Excel Generation with Column Width Auto-Adjustment
                output = BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    def format_sheet(df, name):
                        if df is not None and not df.empty:
                            df.to_excel(writer, sheet_name=name, index=False)
                            worksheet = writer.sheets[name]
                            for idx, col in enumerate(df):
                                max_len = max(df[col].astype(str).map(len).max(), len(str(col))) + 2
                                worksheet.set_column(idx, idx, min(max_len, 45))
                    
                    format_sheet(df_score, 'Agent Summary Scoreboard')
                    format_sheet(df_el, 'Eligible Policies Log')
                    format_sheet(df_inel, 'Ineligible Policies Log')
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                file_name = f"108th_Campaign_Report_{timestamp}.xlsx"
                
                st.download_button(
                    label="📥 Download Full Report (Excel)",
                    data=output.getvalue(),
                    file_name=file_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

```
