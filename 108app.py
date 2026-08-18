import streamlit as st
import pandas as pd
import re
from io import BytesIO

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

        required_prem_cols = ['POLICY NUMBER', 'ENDORSEMENT NUMBER', 'COLLECTION DATE', 'SOURCE INDICATOR', 'LOB ID']
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

        # 4. INITIALIZE LOGS
        eligible_records = []
        ineligible_records = []

        # 5. RULE ENGINE
        for index, row in prem_df.iterrows():
            policy_no = str(row['POLICY NUMBER'])
            col_date = row['COLLECTION DATE']
            lob = str(row.get('LOB ID', '')).strip()
            src_ind = str(row.get('SOURCE INDICATOR', '')).strip().upper()
            endorsement_no = str(row.get('ENDORSEMENT NUMBER', '')).strip()
            agent_code = str(row.get('AGENT CODE', 'Unknown')).strip()
            agent_name = str(row.get('AGENT NAME', 'Unknown')).strip()
            premium = float(row.get('PREMIUM AMOUNT', 0)) if pd.notna(row.get('PREMIUM AMOUNT')) else 0.0

            is_eligible = True
            ineligible_reason = ""
            review_needed = ""

            # Rule 1 & 2
            if pd.isna(col_date) or col_date < CAMPAIGN_START or col_date > CAMPAIGN_END:
                is_eligible = False
                ineligible_reason = "Date out of Campaign Period (Line 1)"
            elif endorsement_no != ':':
                is_eligible = False
                ineligible_reason = "Endorsement Record (Line 2)"
            else:
                is_motor = lob.startswith('31')
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
                            
                            m_prod = str(mot_row.get('PRODUCT_NAME', '')).upper()
                            m_class = str(mot_row.get('CLASS_OF_VEHICLE', '')).upper()
                            if is_eligible:
                                if 'LIABILITY ONLY' in m_prod or lob == '312602':
                                    if 'PRIVATE CAR' in m_class or 'TWO WHEELER' in m_class:
                                         is_eligible = False
                                         ineligible_reason = f"Liability Only ({lob}) is not eligible for Private Car/Two Wheeler (Line 6)"
                                elif 'COMMERCIAL VEH' in m_prod or 'GOODS CARRYING' in m_class:
                                    gvw_str = str(mot_row.get('GROSS_VEHICLE_WEIGHT', '0'))
                                    try:
                                        gvw = float(re.sub(r'[^0-9.]', '', gvw_str)) if gvw_str.strip() != '' else 0
                                        if gvw >= 7500:
                                            is_eligible = False
                                            ineligible_reason = "Commercial Vehicle GVW >= 7500kg (Line 6)"
                                    except ValueError:
                                        review_needed = "Could not parse GVW for Commercial Vehicle."

            # --- PRODUCT CATEGORIZATION & FORMATTING OUTPUT ---
            if is_eligible:
                # Default Unmapped
                cat_id = 0
                cat_name = "Unmapped LOB"
                points = 0
                
                # Basic Categorization Engine (Expand this block as needed)
                if lob.startswith('11265'):
                    cat_id = 7
                    cat_name = "Bharat Griha Raksha"
                    points = 4
                elif lob.startswith('312601'):
                    cat_id = 4
                    cat_name = "Private Car"
                    points = 2
                
                cat_remark = f"Meets criteria (Rule Line 5/6). mapped to {cat_name}" if cat_id > 0 else f"Meets criteria (Rule Line 5/6). Unrecognized LOB code."

                eligible_records.append({
                    'Policy Number': policy_no,
                    'Agent Code': agent_code,
                    'Agent Name': agent_name,
                    'Premium': premium,
                    'Product Category & Nar': f"Cat {cat_id} - {cat_name}",
                    'Points': points,
                    'Remarks': cat_remark,
                    'Review Needed': review_needed,
                    'Cat_ID': cat_id # Internal use for scoreboard count
                })
            else:
                ineligible_records.append({
                    'Policy Number': policy_no,
                    'Agent Code': agent_code,
                    'Premium': premium,
                    'Reason for Ineligibility': ineligible_reason,
                    'Review Needed': review_needed
                })

        # 6. CREATE OUTPUT DATAFRAMES
        df_eligible = pd.DataFrame(eligible_records)
        df_ineligible = pd.DataFrame(ineligible_records)

        # 7. AGENT SCOREBOARD CALCULATIONS
        scoreboard = pd.DataFrame()
        if not df_eligible.empty:
            # Group by Agent Code and Agent Name
            grouped = df_eligible.groupby(['Agent Code', 'Agent Name']).agg(
                Eligible_Total_Premium=('Premium', 'sum'),
                Eligible_Policy_Count=('Policy Number', 'count'),
                Total_Points=('Points', 'sum'),
                Unique_Cats=('Cat_ID', lambda x: x[x > 0].nunique()) # Count unique categories (ignoring unmapped Cat 0)
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
            df_eligible = df_eligible.drop(columns=['Cat_ID']) # Clean up internal column

        return None, df_eligible, df_ineligible, scoreboard

    except Exception as e:
        return f"A critical error occurred during processing: {str(e)}", None, None, None


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
                
                output = BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    if df_score is not None and not df_score.empty:
                        df_score.to_excel(writer, sheet_name='Agent Summary Scoreboard', index=False)
                    if df_el is not None and not df_el.empty:
                        df_el.to_excel(writer, sheet_name='Eligible Policies Log', index=False)
                    if df_inel is not None and not df_inel.empty:
                        df_inel.to_excel(writer, sheet_name='Ineligible Policies Log', index=False)
                
                st.download_button(
                    label="📥 Download Full Report (Excel)",
                    data=output.getvalue(),
                    file_name="108th_Campaign_Report.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
