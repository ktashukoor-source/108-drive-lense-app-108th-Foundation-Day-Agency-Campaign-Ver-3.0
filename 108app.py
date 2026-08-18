import streamlit as st
import pandas as pd
import numpy as np
import io
import re
from datetime import datetime

# --- UI CONFIGURATION ---
st.set_page_config(
    page_title="🏆 108 Drive Lense: 108th Foundation Day Agency Campaign 🤖 Ver 3.1",
    page_icon="🏆",
    layout="wide"
)

# --- CORE LOGIC: DATA CLEANING ---
def clean_policy_numbers(df, col_name):
    """Aggressively cleans unique IDs (removes spaces, colons, hyphens, periods) to fix zero-overlap issues."""
    if col_name in df.columns:
        # Convert to string and explicitly replace Pandas 'nan' string representation with empty string before cleaning
        df[col_name] = df[col_name].astype(str).replace(['nan', 'NaN'], '')
        # Remove ALL special characters (keep only alphanumeric) using regex
        df[col_name] = df[col_name].apply(lambda x: re.sub(r'[^a-zA-Z0-9]', '', str(x)) if pd.notna(x) else x)
    return df

# --- CORE LOGIC: RULE ENGINE ---
def process_campaign_data(premium_file, motor_file=None, cw_file=None, ho_master_file=None):
    try:
        # 1. Load Premium Data
        prem_df = pd.read_csv(premium_file)

        # EXACT SCHEMA MAPPING: Convert all columns to uppercase and replace underscores with spaces
        prem_df.columns = [str(c).replace('_', ' ').strip().upper() for c in prem_df.columns]

        # --- STRICT SCHEMA VALIDATION (PREMIUM) ---
        required_prem_identifiers = ['POLICY NUMBER', 'ENDORSEMENT NUMBER', 'COLLECTION DATE', 'LOB ID', 'SOURCE INDICATOR', 'AGENT CODE']
        missing_prem = [col for col in required_prem_identifiers if col not in prem_df.columns]

        if missing_prem:
            error_msg = (
                f"❌ **Invalid Premium Register File Uploaded.**\n\n"
                f"The system did not recognize this file as the correct Premium Register. "
                f"Missing expected columns like: {', '.join(missing_prem)}.\n\n"
                f"**Please generate and download the correct report from:**\n"
                f"`Dashboard -> Core reports -> Premium -> Premium Register`"
            )
            return None, None, error_msg

        # We explicitly map the known variations to the exact internal keys we need
        prem_col_map = {
            'POLICY NUMBER': 'POLICY NUMBER',
            'ENDORSEMENT NUMBER': 'ENDORSEMENT NUMBER',
            'AGENT CODE': 'AGENT CODE',
            'PREMIUM AMOUNT': 'PREMIUM AMOUNT',
            'NET PREMIUM': 'PREMIUM AMOUNT',
            'LOB ID': 'LOB ID',
            'SOURCE INDICATOR': 'SOURCE INDICATOR',
            'COLLECTION DATE': 'COLLECTION DATE',
            'AGENT NAME': 'AGENT NAME',
            'DEV OFFICER CODE': 'DEV OFFICER CODE',
            'POLICY INCEPTION DATE': 'POLICY INCEPTION DATE',
            'POLICY EXPIRY DATE': 'POLICY EXPIRY DATE'
        }

        # Rename available columns based on the explicit map
        prem_df.rename(columns=lambda c: prem_col_map.get(c, c), inplace=True)

        # Robust Source Indicator identification if exact match failed
        if 'SOURCE INDICATOR' not in prem_df.columns:
            potential_source_cols = [c for c in prem_df.columns if 'SOURCE' in c and 'INDICATOR' in c]
            if potential_source_cols:
                 prem_df.rename(columns={potential_source_cols[0]: 'SOURCE INDICATOR'}, inplace=True)

        required_prem_cols = ['COLLECTION DATE', 'PREMIUM AMOUNT', 'POLICY NUMBER', 'SOURCE INDICATOR', 'ENDORSEMENT NUMBER']
        missing_cols = [col for col in required_prem_cols if col not in prem_df.columns]

        if missing_cols:
             return None, None, f"Error: Premium CSV is missing required columns (or they are named differently): {', '.join(missing_cols)}"

        # Clean unique identifiers using the aggressive regex function
        prem_df = clean_policy_numbers(prem_df, 'POLICY NUMBER')
        prem_df = clean_policy_numbers(prem_df, 'AGENT CODE')
        if 'DEV OFFICER CODE' in prem_df.columns:
            prem_df = clean_policy_numbers(prem_df, 'DEV OFFICER CODE')

        # Ensure Premium Amount is numeric
        prem_df['PREMIUM AMOUNT'] = pd.to_numeric(prem_df['PREMIUM AMOUNT'], errors='coerce').fillna(0)
        
        # 2. Load Motor Data (Optional)
        mot_df = pd.DataFrame()
        if motor_file:
            mot_df = pd.read_csv(motor_file)

            # EXACT SCHEMA MAPPING
            mot_df.columns = [str(c).replace('_', ' ').strip().upper() for c in mot_df.columns]

            # --- STRICT SCHEMA VALIDATION (MOTOR) ---
            required_mot_identifiers = ['POLICY NUMBER', 'CLASS OF VEHICLE', 'GROSS VEHICLE WEIGHT', 'PREVIOUS INSURER NAME']
            missing_mot = [col for col in required_mot_identifiers if col not in mot_df.columns]

            if missing_mot:
                error_msg = (
                    f"❌ **Invalid Motor Details File Uploaded.**\n\n"
                    f"The system did not recognize this file as the correct Motor Business Details report. "
                    f"Missing expected columns like: {', '.join(missing_mot)}.\n\n"
                    f"**Please generate and download the correct report from:**\n"
                    f"`Dashboard -> Core reports -> Motor(Premium) -> Motor Business Details`"
                )
                return None, None, error_msg

            if 'POLICY NUMBER' not in mot_df.columns:
                potential_policy_cols = [c for c in mot_df.columns if 'POLICY' in c and ('NO' in c or 'NUM' in c)]
                if potential_policy_cols:
                    mot_df.rename(columns={potential_policy_cols[0]: 'POLICY NUMBER'}, inplace=True)
                else:
                    return None, None, "Error: Could not identify a Policy Number column in the Motor Details CSV."

            mot_df = clean_policy_numbers(mot_df, 'POLICY NUMBER') 
            if 'PREVIOUS POLICY NO' in mot_df.columns:
                mot_df = clean_policy_numbers(mot_df, 'PREVIOUS POLICY NO')

        # 3. Load Motor Class wise Premium Register (Optional)
        cw_dict = {}
        if cw_file:
            cw_df = pd.read_csv(cw_file, dtype=str)
            cw_df.columns = [str(c).replace('_', ' ').strip().upper() for c in cw_df.columns]
            
            if 'POLICY NUMBER' not in cw_df.columns or 'VEHICAL TYPE' not in cw_df.columns:
                return None, None, "❌ **Invalid Class wise Premium Register.** Missing 'Policy Number' or 'Vehical Type' columns."
            
            # Clean Policy Numbers (Remove trailing colons specifically, then clean)
            cw_df['POLICY NUMBER'] = cw_df['POLICY NUMBER'].astype(str).str.replace(':', '', regex=False)
            cw_df = clean_policy_numbers(cw_df, 'POLICY NUMBER')
            
            # Create rapid lookup dictionary mapping Policy Number -> Vehical Type
            cw_dict = dict(zip(cw_df['POLICY NUMBER'], cw_df['VEHICAL TYPE'].astype(str).str.strip().str.upper()))

        # 4. Handle HO Master List (Optional)
        ho_fresh_policies = set()
        if ho_master_file:
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
                    return None, None, "Error: HO Master List does not contain 'POLICY_NUMBER' and 'TYPE_OF_POLICIES' columns in the 'Total' sheet."
            except Exception as e:
                return None, None, f"Could not read HO Master List. Ensure it's a valid Excel file with a 'Total' sheet. Error: {e}"

        # 5. INITIALIZE LOGS
        results_eligible = []
        results_ineligible = []

        # --- BEGIN RULE EVALUATIONS ---
        def get_valid_value(row_data, target_keywords, default='Unknown'):
            """Robust extractor: Searches all column names for specific keywords."""
            possible_values = []
            for col in row_data.index:
                col_str = str(col).upper()
                if all(keyword in col_str for keyword in target_keywords):
                    val = row_data[col]
                    v_str = str(val).strip()
                    if v_str.lower() not in ['nan', 'none', '', 'na']:
                        possible_values.append(v_str)
            if possible_values:
                return possible_values[-1]
            return default

        for index, row in prem_df.iterrows():
            pol_num = str(row.get('POLICY NUMBER', '')).strip()

            agent_code = get_valid_value(row, ['AGENT', 'CODE'], 'Unknown')
            agent_name = get_valid_value(row, ['AGENT', 'NAME'], 'Unknown')

            if agent_code == 'Unknown' or not str(agent_code).strip():
                dev_code = get_valid_value(row, ['DEV', 'OFFICER', 'CODE'], 'Unknown')
                if dev_code != 'Unknown' and str(dev_code).strip():
                    agent_code = str(dev_code).strip()
                    agent_name = "DIRECT"

            premium = row.get('PREMIUM AMOUNT', 0)
            lob = str(pol_num)[6:12] if len(str(pol_num)) >= 12 else "Unknown"
            is_motor = lob in ['312601', '312602', '312603']

            # --- LONG TERM POLICY PREMIUM ADJUSTMENT ---
            premium_remark = ""
            if not is_motor:
                try:
                    inc_val = row.get('POLICY INCEPTION DATE', row.get('COLLECTION DATE'))
                    exp_val = row.get('POLICY EXPIRY DATE')

                    if pd.notna(inc_val) and pd.notna(exp_val):
                        inc_date = pd.to_datetime(inc_val, errors='coerce')
                        exp_date = pd.to_datetime(exp_val, errors='coerce')

                        if pd.notna(inc_date) and pd.notna(exp_date):
                            days_diff = (exp_date - inc_date).days
                            years = round(days_diff / 365.25)

                            if years > 1:
                                original_premium = premium
                                premium = original_premium * years
                                premium_remark = f" [Long-Term: Premium {original_premium} * {years} yrs = {premium}]"
                except Exception:
                    pass

            # Line 1: Campaign Period
            try:
                col_date = pd.to_datetime(row['COLLECTION DATE'], errors='coerce')
                start_date = pd.to_datetime('2026-07-23')
                end_date = pd.to_datetime('2026-08-22')

                if pd.isna(col_date) or not (start_date <= col_date <= end_date):
                    results_ineligible.append({'Policy Number': pol_num, 'Agent Code': agent_code, 'Premium': premium, 'Reason for Ineligibility': f'Date out of Campaign Period (Line 1){premium_remark}'})
                    continue
            except:
                 pass

            # Line 2: Endorsement Check
            if str(row.get('ENDORSEMENT NUMBER', '')).strip() != ':':
                results_ineligible.append({'Policy Number': pol_num, 'Agent Code': agent_code, 'Premium': premium, 'Reason for Ineligibility': f'Endorsement Record (Line 2){premium_remark}'})
                continue

            # Line 3: Minimum Premium
            if premium < 500:
                results_ineligible.append({'Policy Number': pol_num, 'Agent Code': agent_code, 'Premium': premium, 'Reason for Ineligibility': f'Premium < 500 (Line 3){premium_remark}'})
                continue

            # Line 4: Fresh/Old Business Validation
            review_flag = ""
            is_eligible_line4 = True

            if pol_num in ho_fresh_policies:
                pass # Master List says it is NEW POLICY
            else:
                if not is_motor:
                    src_ind = str(row.get('SOURCE INDICATOR', '')).upper()
                    if 'RENEWAL' in src_ind:
                        is_eligible_line4 = False
                        reason = f"Policy Renewal. Source Indicator: '{src_ind}' (Line 4A)"
                    elif 'FRESH POLICY' not in src_ind:
                        review_flag = f"Confirm if fresh business. Source Indicator is '{src_ind}' (Line 4A)."
                else:
                    if mot_df.empty:
                        review_flag = "Motor details missing. Cannot validate Previous Insurer (Line 4B)."
                    else:
                        mot_row = mot_df[mot_df['POLICY NUMBER'] == pol_num]
                        if not mot_row.empty:
                            prev_ins = str(mot_row['PREVIOUS INSURER NAME'].iloc[0]).strip(" .,-").upper() if 'PREVIOUS INSURER NAME' in mot_df.columns else ''
                            if prev_ins == 'THE NEW INDIA ASSURANCE COMPANY LTD':
                                prev_pol = str(mot_row['PREVIOUS POLICY NO'].iloc[0]) if 'PREVIOUS POLICY NO' in mot_df.columns else ''
                                try:
                                    chars = prev_pol[8:10]
                                    val = int(chars)
                                    if val >= 25:
                                        is_eligible_line4 = False
                                        reason = f"Previous Insurer: New India Assurance & Previous Policy digits >= 25 ({val}) (Line 4B)"
                                except:
                                    review_flag = "Could not parse 9th/10th digits of Previous Policy (Line 4B)."
                        else:
                            review_flag = "Policy missing in Motor Details CSV (Line 4B)."

            if not is_eligible_line4:
                results_ineligible.append({'Policy Number': pol_num, 'Agent Code': agent_code, 'Premium': premium, 'Reason for Ineligibility': reason, 'Review Needed': review_flag})
                continue

            # Line 5 & 6: LOB Categorization & Scoring
            pts = 0
            cat_num = 0
            prod_name = "Unmapped LOB"

            cat_map = {
                '612695': (1, 4, 'New India Mediclaim'), '612628': (1, 4, 'Floater Mediclaim'), 
                '612693': (1, 4, 'Arogya Sanjeevani'), '612624': (1, 4, 'Yuva Bharat'), 
                '692609': (1, 4, 'Overseas Mediclaim'), '692630': (1, 4, 'Overseas Mediclaim'), 
                '612678': (2, 3, 'Top Up Policy'), '612650': (2, 3, 'Arogya Pragati Plus'),
                '612637': (3, 5, 'Cancer Guard Policy'), '612631': (3, 5, 'Criti Protect'),
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

            if not is_motor:
                if lob in cat_map:
                    cat_num, pts, prod_name = cat_map[lob]
                else:
                    review_flag += " Unrecognized Non-Motor LOB code."
            else:
                if not mot_df.empty:
                    mot_row = mot_df[mot_df['POLICY NUMBER'] == pol_num]
                    if not mot_row.empty:
                        m_prod = str(mot_row['PRODUCT NAME'].iloc[0]).upper() if 'PRODUCT NAME' in mot_df.columns else ''
                        m_class = str(mot_row['CLASS OF VEHICLE'].iloc[0]).upper() if 'CLASS OF VEHICLE' in mot_df.columns else ''
                        m_body = str(mot_row['BODY TYPE'].iloc[0]).upper() if 'BODY TYPE' in mot_df.columns else ''
                        m_gvw = pd.to_numeric(mot_row['GROSS VEHICLE WEIGHT'].iloc[0] if 'GROSS VEHICLE WEIGHT' in mot_df.columns else 0, errors='coerce')

                        if 'PRIVATE CAR' in m_prod:
                            if lob in ['312601', '312603']:
                                cat_num, pts, prod_name = 4, 2, 'Private Car'
                            else:
                                results_ineligible.append({'Policy Number': pol_num, 'Agent Code': agent_code, 'Premium': premium, 'Reason for Ineligibility': 'Liability Only (312602) not eligible for Private Car (Line 6)'})
                                continue
                        elif 'COMMERCIAL VEH' in m_prod:
                            if 'GOODS CARRYING' in m_class and pd.notna(m_gvw) and m_gvw <= 7500:
                                cat_num, pts, prod_name = 5, 3, 'Goods Carrying'
                            elif 'PASSENGER CARRYING' in m_class:
                                taxi_bodies = ['SALOON', 'SEDAN', 'HATCH-BACK', 'STATION WAGON/WAGON', 'SUV', 'SPORTS CAR/SUPER CAR']
                                is_taxi_body = any(tb in m_body for tb in taxi_bodies)
                                
                                def is_cw_taxi_match(cw_v_type):
                                    # Standardize spacing to robustly match 'C - Passenger Carrying : C1-Four Wheeler(Carrying <=6)'
                                    v = cw_v_type.replace(" ", "")
                                    return 'C1-FOURWHEELER' in v and '<=6' in v

                                if is_taxi_body:
                                    # Tentatively Eligible
                                    cat_num, pts, prod_name = 5, 3, 'Taxis'
                                    review_flag += " Verify Seating Capacity <= 6 (Line 6)."
                                    
                                    # DEMOTION LOGIC: Check Class-Wise override
                                    if cw_dict and pol_num in cw_dict:
                                        cw_veh_type = cw_dict[pol_num]
                                        if not is_cw_taxi_match(cw_veh_type):
                                            results_ineligible.append({'Policy Number': pol_num, 'Agent Code': agent_code, 'Premium': premium, 'Reason for Ineligibility': f'Class-wise Check Failed: Vehical Type is "{cw_veh_type}" (Line 6)', 'Review Needed': 'Demoted from Taxi based on Class Wise Premium Register.'})
                                            continue # Fails and skips addition to eligible log
                                            
                                elif 'STAFF BUS' in m_body:
                                    cat_num, pts, prod_name = 6, 4, 'Staff Bus'
                                else:
                                    # Tentatively Ineligible
                                    promoted = False
                                    
                                    # PROMOTION LOGIC: Check Class-Wise override
                                    if cw_dict and pol_num in cw_dict:
                                        cw_veh_type = cw_dict[pol_num]
                                        if is_cw_taxi_match(cw_veh_type):
                                            cat_num, pts, prod_name = 5, 3, 'Taxis'
                                            review_flag += " Promoted to Taxi based on Class Wise Premium Register."
                                            promoted = True
                                            
                                    if not promoted:
                                        results_ineligible.append({'Policy Number': pol_num, 'Agent Code': agent_code, 'Premium': premium, 'Reason for Ineligibility': 'Unrecognized Body Type for Passenger Carrying', 'Review Needed': 'Check manual records to verify if actual usage is Taxi (<=6) or Staff Bus (Line 6)'})
                                        continue
                        elif 'SCHOOL BUS' in m_class:
                            cat_num, pts, prod_name = 6, 4, 'School Bus'

                else:
                    review_flag += " Missing in Motor Data to evaluate Cat rules."

            # Divest Cat 0 into Ineligible Log so it doesn't inflate Eligible Premium sums
            if cat_num == 0:
                results_ineligible.append({
                    'Policy Number': pol_num, 'Agent Code': agent_code, 'Premium': premium, 
                    'Reason for Ineligibility': f"Unmapped LOB / Missing Categorization Data (Line 5/6){premium_remark}",
                    'Review Needed': review_flag.strip()
                })
            else:
                results_eligible.append({
                    'Policy Number': pol_num, 'Agent Code': agent_code, 'Agent Name': agent_name, 
                    'Premium': premium, 'Product Category & Name': f"Cat {cat_num} - {prod_name}", 
                    'Points': pts, 'Remarks': f"Meets criteria (Rule Line 5/6). mapped to {prod_name}{premium_remark}", 'Review Needed': review_flag.strip()
                })

        # --- END ITERATION ---
        final_eligible = pd.DataFrame(results_eligible).drop_duplicates(subset=['Policy Number'])
        final_ineligible = pd.DataFrame(results_ineligible).drop_duplicates(subset=['Policy Number'])

        for col in ['Agent Code', 'Agent Name', 'Premium', 'Points']:
             if col not in final_eligible.columns:
                 final_eligible[col] = "Unknown" if 'Agent' in col else 0

        final_eligible['Agent Code'] = final_eligible['Agent Code'].astype(str)
        final_eligible['Agent Name'] = final_eligible['Agent Name'].astype(str).replace(['nan', 'NaN', 'None', ''], "Unknown")

        summary_data = []
        if not final_eligible.empty:
            grouped = final_eligible.groupby('Agent Code')

            for agent_code, group in grouped:
                names = group['Agent Name'].dropna().unique()
                valid_names = [n for n in names if str(n).strip().lower() not in ['unknown', 'nan', '']]
                agent_name = valid_names[0] if valid_names else "Unknown"

                total_prem = group['Premium'].sum()
                pol_count = group['Policy Number'].nunique() 
                total_pts = group['Points'].sum()

                cat_strings = group['Product Category & Name'].dropna().astype(str).tolist() if 'Product Category & Name' in group.columns else []
                categories = set()

                for c in cat_strings:
                    match = re.search(r'(?i)cat(?:egory)?\s*(\d+)', c)
                    if match:
                        cat_num = int(match.group(1))
                        if cat_num > 0: categories.add(cat_num)

                achieved_cats = list(categories)

                is_eligible = 'Y' if (total_pts >= 108 and len(achieved_cats) >= 5) else 'N'
                remark = "Eligible" if is_eligible == 'Y' else f"Missed target. Pts: {total_pts}/108, Cats: {len(achieved_cats)}/5"

                summary_data.append({
                    'Agent Code': agent_code, 'Agent Name': agent_name, 
                    'Eligible Total Premium': total_prem, 'Eligible Policy Count': pol_count,
                    'Total Points': total_pts, 'Achieved Product Categories': str(achieved_cats),
                    'Eligible(Y/N)': is_eligible, 'Remark': remark
                })

        summary_df = pd.DataFrame(summary_data)
        if not summary_df.empty:
            summary_df = summary_df.sort_values(by='Total Points', ascending=False)

        return summary_df, final_eligible, final_ineligible

    except Exception as e:
        import traceback
        return None, None, f"A critical error occurred: {str(e)}\nTraceback: {traceback.format_exc()}"

# --- STREAMLIT UI LAYOUT ---
st.title("🏆 108 Drive Lense: Campaign Analyzer 🤖 Ver 3.1")
st.markdown("""
Welcome to the offline, secure data processor. 
Upload your exact CSV files from the core system. No data leaves your browser.
""")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.subheader("1. Premium Register")
    st.info("**Path:**\n`Dashboard -> Core reports -> Premium -> Premium Register`")
    prem_file = st.file_uploader("Upload Premium CSV", type=['csv'])

with col2:
    st.subheader("2. Motor Details")
    st.info("**Path:**\n`Dashboard -> Core reports -> Motor(Premium) -> Motor Business Details`")
    mot_file = st.file_uploader("Upload Motor CSV", type=['csv'])

with col3:
    st.markdown("<div style='opacity: 0.8;'>", unsafe_allow_html=True)
    st.subheader("3. Class wise Premium (Optional)")
    st.info("**Path:**\n`Dashboard -> Core reports -> Motor(Premium) -> Class wise Premium Register`\n*(Enhances CV-Taxi accuracy)*")
    cw_file = st.file_uploader("Upload Class wise CSV", type=['csv'])
    st.markdown("</div>", unsafe_allow_html=True)

with col4:
    st.markdown("<div style='opacity: 0.8;'>", unsafe_allow_html=True)
    st.subheader("4. HO Master List (Optional)")
    st.info("**Master List Tracking:**\nUpload HO list up to 11th to bypass Fresh/Renewal rules for 'NEW POLICY'.")
    ho_master_file = st.file_uploader("Upload HO Master List", type=['xlsx'])
    st.markdown("</div>", unsafe_allow_html=True)

if st.button("Process Campaign Data", type="primary"):
    if prem_file is None:
        st.error("Please upload at least the Premium Register CSV to begin.")
    else:
        with st.spinner("Executing rule engine..."):
            summary, el_log, in_log = process_campaign_data(prem_file, mot_file, cw_file, ho_master_file)

            if isinstance(in_log, str) and summary is None:
                st.error(in_log)
            else:
                st.success("Analysis Complete!")

                st.subheader("Category Reference Guide")
                with st.expander("View Category Numbers & Products", expanded=False):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown("""
                        * **Cat 1:** New India Mediclaim, Floater, Arogya Sanjeevani, Yuva Bharat, Overseas Mediclaim
                        * **Cat 2:** Top Up, Arogya Pragati Plus
                        * **Cat 3:** Cancer Guard, Criti Protect
                        * **Cat 4:** Private Car Package
                        * **Cat 5:** Goods Carrying (GVW <= 7500), Taxis (<= 6 Seating)
                        * **Cat 6:** School Bus, Staff Bus
                        * **Cat 7:** Bharat Griha Raksha, Bharat Sookshma Udyam Suraksha
                        """)
                    with col_b:
                        st.markdown("""
                        * **Cat 8:** Bharat Laghu Udyam Suraksha, Flexi Laghu
                        * **Cat 9:** Personal Accident, Rasta Apatti Kavach (RAK)
                        * **Cat 10:** Employee Compensation (WC)
                        * **Cat 11:** Mahila Udyam, Bima Saathi
                        * **Cat 12:** Jewellers Block
                        * **Cat 13:** Householder, Griha Suvidha, Shopkeepers, Office Protection Shield
                        * **Cat 14:** Public Liability, CGL Policy
                        * **Cat 15:** My Cyber Policy
                        """)

                st.subheader("Leaderboard Preview (Descending)")
                st.dataframe(summary)

                # --- ROBUST EXCEL GENERATION ---
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    if summary is not None and not summary.empty:
                         summary.to_excel(writer, sheet_name='Agent Summary Scoreboard', index=False)
                    if el_log is not None and not el_log.empty:
                         el_log.to_excel(writer, sheet_name='Eligible Policies Log', index=False)
                    if in_log is not None and not in_log.empty:
                         in_log.to_excel(writer, sheet_name='Ineligible Policies Log', index=False)

                    workbook = writer.book
                    for sheet_name in writer.sheets:
                        worksheet = writer.sheets[sheet_name]
                        worksheet.set_default_row(15)
                        worksheet.set_column('A:Z', 20) 

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                file_name = f"108th_Campaign_Report_{timestamp}.xlsx"

                st.download_button(
                    label="📥 Download Secure Excel Report",
                    data=buffer.getvalue(),
                    file_name=file_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
