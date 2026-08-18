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

        # Premium Schema Validation
        required_prem_cols = ['POLICY NUMBER', 'ENDORSEMENT NUMBER', 'COLLECTION DATE', 'SOURCE INDICATOR', 'LOB ID']
        missing_prem = [col for col in required_prem_cols if col not in prem_df.columns]
        if missing_prem:
            return f"Validation Error: Premium Register is missing columns: {', '.join(missing_prem)}. Please ensure you uploaded the correct report.", None, None, None

        # Standardize Agent / Dev Officer Codes
        if 'AGENT CODE' in prem_df.columns and 'DEV OFFICER CODE' in prem_df.columns:
            prem_df['AGENT CODE'] = prem_df['AGENT CODE'].fillna('Unknown').str.strip()
            # If Agent Code is missing/Unknown but Dev Officer exists, map to DIRECT
            direct_mask = (prem_df['AGENT CODE'].isin(['', 'Unknown', 'NA'])) & (prem_df['DEV OFFICER CODE'].notna()) & (prem_df['DEV OFFICER CODE'].str.strip() != '')
            prem_df.loc[direct_mask, 'AGENT CODE'] = prem_df.loc[direct_mask, 'DEV OFFICER CODE']
            if 'AGENT NAME' in prem_df.columns:
                prem_df.loc[direct_mask, 'AGENT NAME'] = 'DIRECT'

        # Clean Identifiers and Dates
        prem_df = clean_policy_numbers(prem_df, 'POLICY NUMBER')
        # Smart date parsing: let pandas infer format, errors='coerce' turns bad dates to NaT instead of crashing
        prem_df['COLLECTION DATE'] = pd.to_datetime(prem_df['COLLECTION DATE'], errors='coerce') 

        # 2. LOAD MOTOR DETAILS (Optional)
        mot_df = pd.DataFrame()
        if mot_file is not None:
            mot_df = pd.read_csv(mot_file, dtype=str)
            mot_df.columns = mot_df.columns.str.strip().str.upper()
            
            # Motor Schema Validation
            required_mot_cols = ['POLICY_NUMBER', 'CLASS_OF_VEHICLE', 'PRODUCT_NAME']
            missing_mot = [col for col in required_mot_cols if col not in mot_df.columns]
            if missing_mot:
                 return f"Validation Error: Motor Details is missing columns: {', '.join(missing_mot)}. Please ensure you uploaded the correct report.", None, None, None
            
            mot_df = clean_policy_numbers(mot_df, 'POLICY_NUMBER')
            mot_df = clean_policy_numbers(mot_df, 'PREVIOUS_POLICY_NO')

        # 3. LOAD HO MASTER LIST (Optional)
        ho_fresh_policies = set()
        if ho_master_file is not None:
            try:
                ho_df = pd.read_excel(ho_master_file, sheet_name='Total', dtype=str)
                ho_df.columns = ho_df.columns.str.strip().str.upper()
                
                if 'POLICY_NUMBER' in ho_df.columns and 'TYPE_OF_POLICIES' in ho_df.columns:
                    ho_df = clean_policy_numbers(ho_df, 'POLICY_NUMBER')
                    fresh_mask = ho_df['TYPE_OF_POLICIES'].str.strip().str.upper() == 'NEW POLICY'
                    ho_fresh_policies = set(ho_df.loc[fresh_mask, 'POLICY_NUMBER'].dropna().tolist())
                else:
                    return "Validation Error: HO Master List 'Total' sheet missing 'POLICY_NUMBER' or 'TYPE_OF_POLICIES'.", None, None, None
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
            premium = float(row.get('PREMIUM AMOUNT', 0)) if pd.notna(row.get('PREMIUM AMOUNT')) else 0.0

            is_eligible = True
            ineligible_reason = ""
            review_needed = ""

            # Rule 1: Date Check (Campaign Period)
            if pd.isna(col_date) or col_date < CAMPAIGN_START or col_date > CAMPAIGN_END:
                is_eligible = False
                ineligible_reason = "Date out of Campaign Period (Line 1)"
            
            # Rule 2: Endorsement Check (Must be exactly ':')
            elif endorsement_no != ':':
                is_eligible = False
                ineligible_reason = "Endorsement Record (Line 2)"
            
            # Non-Motor vs Motor Processing
            else:
                is_motor = lob.startswith('31')

                if not is_motor:
                    # Non-Motor Rule 4A: Fresh Business Check
                    if policy_no in ho_fresh_policies:
                        pass # Bypassed by Master List
                    elif 'RENEWAL' in src_ind:
                        is_eligible = False
                        ineligible_reason = f"Policy is a Renewal. Source Indicator: '{src_ind}' (Line 4A)"
                    elif 'FRESH POLICY' not in src_ind:
                        review_needed = f"Confirm if fresh business. Source Indicator is '{src_ind}' (Line 4A)."
                
                else:
                    # Motor Processing
                    if mot_df.empty:
                        review_needed = "Motor policy, but Motor Details CSV not provided. Unverified category."
                    else:
                        mot_matches = mot_df[mot_df['POLICY_NUMBER'] == policy_no]
                        if mot_matches.empty:
                            review_needed = "Motor policy not found in Motor Details CSV."
                        else:
                            mot_row = mot_matches.iloc[0]
                            
                            # Rule 4B: Motor Fresh Business Check
                            if policy_no in ho_fresh_policies:
                                pass # Bypassed by Master List
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

                            # Rule 5/6: Motor Categorization & LOB 312602 Exclusions
                            m_prod = str(mot_row.get('PRODUCT_NAME', '')).upper()
                            m_class = str(mot_row.get('CLASS_OF_VEHICLE', '')).upper()
                            
                            # Example Category matching based on previous rules
                            if is_eligible:
                                if 'LIABILITY ONLY' in m_prod or lob == '312602':
                                    if 'PRIVATE CAR' in m_class or 'TWO WHEELER' in m_class:
                                         is_eligible = False
                                         ineligible_reason = f"Liability Only ({lob}) is not eligible for Private Car/Two Wheeler category (Line 6)"
                                # Apply smarter partial matching
                                elif 'COMMERCIAL VEH' in m_prod or 'GOODS CARRYING' in m_class:
                                    gvw_str = str(mot_row.get('GROSS_VEHICLE_WEIGHT', '0'))
                                    try:
                                        gvw = float(re.sub(r'[^0-9.]', '', gvw_str)) if gvw_str.strip() != '' else 0
                                        if gvw >= 7500:
                                            is_eligible = False
                                            ineligible_reason = "Commercial Vehicle GVW >= 7500kg (Line 6)"
                                    except ValueError:
                                        review_needed = "Could not parse GVW for Commercial Vehicle."

            # Append to appropriate list
            record_data = row.to_dict()
            record_data['Agent Code'] = agent_code
            record_data['Premium'] = premium
            record_data['Review Needed'] = review_needed
            
            if is_eligible:
                eligible_records.append(record_data)
            else:
                record_data['Reason for Ineligibility'] = ineligible_reason
                ineligible_records.append(record_data)

        # 6. CREATE OUTPUT DATAFRAMES
        df_eligible = pd.DataFrame(eligible_records)
        df_ineligible = pd.DataFrame(ineligible_records)

        # 7. AGENT SCOREBOARD
        scoreboard = pd.DataFrame()
        if not df_eligible.empty:
            scoreboard = df_eligible.groupby('Agent Code')['Premium'].sum().reset_index()
            scoreboard = scoreboard.sort_values(by='Premium', ascending=False)

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
                
                # Layout for Results
                tab1, tab2, tab3 = st.tabs(["Agent Scoreboard", "Eligible Policies", "Ineligible Policies"])
                
                with tab1:
                    st.dataframe(df_score, use_container_width=True)
                with tab2:
                    st.dataframe(df_el, use_container_width=True)
                with tab3:
                    st.dataframe(df_inel, use_container_width=True)
                
                # Excel Generation
                output = BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    if df_score is not None and not df_score.empty:
                        df_score.to_excel(writer, sheet_name='Agent Scoreboard', index=False)
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
