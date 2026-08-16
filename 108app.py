# STREAMLIT_CHUNK:Updating imports and config...
import streamlit as st
import pandas as pd
import numpy as np
import io
import re
from datetime import datetime

# --- UI CONFIGURATION ---
st.set_page_config(
    page_title="108 Drive Lense Campaign",
    page_icon="🏆",
    layout="wide"
)

# STREAMLIT_CHUNK:Defining data cleaning helper...
# --- CORE LOGIC: DATA CLEANING ---
def clean_policy_numbers(df, col_name):
    """Aggressively cleans unique IDs to fix zero-overlap issues."""
    if col_name in df.columns:
        # Convert to string and strip outer whitespace
        df[col_name] = df[col_name].astype(str).str.strip()
        # Remove ALL special characters (keep only alphanumeric) using regex
        df[col_name] = df[col_name].str.replace(r'[^a-zA-Z0-9]', '', regex=True)
    return df

# STREAMLIT_CHUNK:Starting main processing function...
# --- CORE LOGIC: RULE ENGINE ---
def process_campaign_data(premium_file, motor_file=None, prev_output_file=None):
    try:
        # STREAMLIT_CHUNK:Loading and standardizing Premium Data...
        # 1. Load Premium Data
        prem_df = pd.read_csv(premium_file)
        
        # Convert all columns to uppercase and strip whitespace for robust matching
        prem_df.columns = [' '.join(str(c).upper().split()) for c in prem_df.columns]
        
        # Exact schema mapping based on user input
        prem_col_map = {
            'POLICY NUMBER': 'POLICY NUMBER',
            'ENDORSEMENT NUMBER': 'ENDORSEMENT NUMBER',
            'AGENT CODE': 'AGENT CODE',
            'PREMIUM AMOUNT': 'PREMIUM AMOUNT',
            'LOB ID': 'LOB ID',
            'SOURCE INDICATOR': 'SOURCE INDICATOR',
            'COLLECTION DATE': 'COLLECTION DATE',
            'AGENT NAME': 'AGENT NAME'
        }
        
        # Rename available columns based on the map (handles potential variations gracefully)
        prem_df.rename(columns=lambda c: prem_col_map.get(c, c), inplace=True)
        
        required_prem_cols = ['COLLECTION DATE', 'PREMIUM AMOUNT', 'POLICY NUMBER', 'SOURCE INDICATOR', 'ENDORSEMENT NUMBER']
        missing_cols = [col for col in required_prem_cols if col not in prem_df.columns]
        
        if missing_cols:
             return None, None, f"Error: Premium CSV is missing required columns (or they are named differently): {', '.join(missing_cols)}"
             
        # Clean unique identifiers
        prem_df = clean_policy_numbers(prem_df, 'POLICY NUMBER')
        prem_df = clean_policy_numbers(prem_df, 'AGENT CODE')

        # Ensure Premium Amount is numeric
        prem_df['PREMIUM AMOUNT'] = pd.to_numeric(prem_df['PREMIUM AMOUNT'], errors='coerce').fillna(0)

        # STREAMLIT_CHUNK:Loading and standardizing Motor Data...
        # 2. Load Motor Data (Optional)
        mot_df = pd.DataFrame()
        if motor_file:
            mot_df = pd.read_csv(motor_file)
            mot_df.columns = [' '.join(str(c).upper().split()) for c in mot_df.columns]
            
            # Exact schema mapping based on user input
            mot_col_map = {
                'POLICY_NUMBER': 'POLICY NUMBER', # Standardize to match premium data
                'PRODUCT_NAME': 'PRODUCT NAME',
                'CLASS_OF_VEHICLE': 'CLASS OF VEHICLE',
                'BODY_TYPE': 'BODY TYPE',
                'GROSS_VEHICLE_WEIGHT': 'GROSS VEHICLE WEIGHT',
                'PREVIOUS_INSURER_NAME': 'PREVIOUS INSURER NAME',
                'PREVIOUS_POLICY_NO': 'PREVIOUS POLICY NO'
            }
            mot_df.rename(columns=lambda c: mot_col_map.get(c, c), inplace=True)
            
            if 'POLICY NUMBER' not in mot_df.columns:
                 return None, None, "Error: Could not identify a Policy Number column in the Motor Details CSV. Expected 'POLICY_NUMBER'."
                 
            # Clean unique identifiers in motor data
            mot_df = clean_policy_numbers(mot_df, 'POLICY NUMBER') 
            mot_df = clean_policy_numbers(mot_df, 'PREVIOUS POLICY NO')
            
        # STREAMLIT_CHUNK:Handling Previous Output File overrides...
        # 3. Handle Previous Output Override (Excel-Only or Excel+CSV)
        pre_approved = pd.DataFrame()
        pre_rejected = pd.DataFrame()
        
        if prev_output_file:
            try:
                # Load exactly as specified by user
                prev_eligible = pd.read_excel(prev_output_file, sheet_name='Eligible Policies Log')
                prev_ineligible = pd.read_excel(prev_output_file, sheet_name='Ineligible Policies Log')
                
                # Ensure correct types and handle missing values before cleaning
                for df in [prev_eligible, prev_ineligible]:
                    if 'Policy Number' in df.columns:
                         df['Policy Number'] = df['Policy Number'].astype(str)
                    if 'Agent Code' in df.columns:
                         df['Agent Code'] = df['Agent Code'].astype(str)
                
                if 'Agent Name' in prev_eligible.columns:
                     prev_eligible['Agent Name'] = prev_eligible['Agent Name'].astype(str).replace(['nan', 'NaN', 'None', ''], "Unknown")
                else:
                     prev_eligible['Agent Name'] = "Unknown"
                
                prev_eligible = clean_policy_numbers(prev_eligible, 'Policy Number')
                prev_ineligible = clean_policy_numbers(prev_ineligible, 'Policy Number')
                
                prev_eligible = clean_policy_numbers(prev_eligible, 'Agent Code')
                prev_ineligible = clean_policy_numbers(prev_ineligible, 'Agent Code')
                
                if 'Remarks' in prev_eligible.columns:
                    prev_eligible['Remarks'] = "Since you uploaded it as already listed eligible - " + prev_eligible['Remarks'].astype(str)
                    
                if 'Reason for Ineligibility' in prev_ineligible.columns:
                    prev_ineligible['Reason for Ineligibility'] = "Since you uploaded it as already listed ineligible - " + prev_ineligible['Reason for Ineligibility'].astype(str)
                
                pre_approved = prev_eligible
                pre_rejected = prev_ineligible
                
                # ZERO OVERLAP WARNING CHECK
                if not prem_df.empty and not pre_approved.empty:
                    overlap = prem_df['POLICY NUMBER'].isin(pre_approved['Policy Number']).any()
                    if not overlap:
                        st.warning("🚨 **CRITICAL WARNING:** The previous output file you uploaded shares ZERO matching policies with the new Premium CSV data! Please double-check if you uploaded the correct previous version or used the right date range for your new CSV extracts. 🚨")
                        
            except Exception as e:
                st.warning(f"Could not read override sheets from the uploaded Excel file. Ensure the sheet names match exactly. Error: {e}")

        # STREAMLIT_CHUNK:Deduplicating policies based on overrides...
        # 4. INITIALIZE LOGS
        eligible_log = pd.DataFrame()
        ineligible_log = pd.DataFrame()

        # Deduplicate: Remove pre-approved/rejected from the new pool
        if not pre_approved.empty or not pre_rejected.empty:
            override_policies = pd.concat([pre_approved['Policy Number'], pre_rejected['Policy Number']])
            prem_df = prem_df[~prem_df['POLICY NUMBER'].isin(override_policies)]

        # STREAMLIT_CHUNK:Beginning row-by-row rule evaluations...
        # --- BEGIN RULE EVALUATIONS ---
        
        results_eligible = []
        results_ineligible = []
        
        def get_valid_value(row_data, target_keywords, default='Unknown'):
            """Searches all column names for specific keywords and returns the first valid string."""
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
            
            # Robust Agent Code extraction
            agent_code = get_valid_value(row, ['AGENT', 'CODE'], 'Unknown')
                 
            # Robust Agent Name extraction
            agent_name = get_valid_value(row, ['AGENT', 'NAME'], 'Unknown')
            
            premium = row.get('PREMIUM AMOUNT', 0)
            
            # LOB ID Extraction from Policy Number
            lob = str(pol_num)[6:12] if len(str(pol_num)) >= 12 else "Unknown"
            
            # STREAMLIT_CHUNK:Evaluating Line 1 & Line 2 constraints...
            # Line 1: Campaign Period 
            try:
                col_date = pd.to_datetime(row['COLLECTION DATE'], dayfirst=True)
                start_date = pd.to_datetime('2026-07-23')
                end_date = pd.to_datetime('2026-08-22')
                if not (start_date <= col_date <= end_date):
                    results_ineligible.append({'Policy Number': pol_num, 'Agent Code': agent_code, 'Premium': premium, 'Reason for Ineligibility': 'Date out of Campaign Period (Line 1)'})
                    continue
            except:
                 pass

            # Line 2: Endorsement Check
            if str(row.get('ENDORSEMENT NUMBER', '')).strip() != ':':
                results_ineligible.append({'Policy Number': pol_num, 'Agent Code': agent_code, 'Premium': premium, 'Reason for Ineligibility': 'Endorsement Record (Line 2)'})
                continue
                
            # STREAMLIT_CHUNK:Evaluating Line 3 & Line 4 constraints...
            # Line 3: Minimum Premium
            if premium < 500:
                results_ineligible.append({'Policy Number': pol_num, 'Agent Code': agent_code, 'Premium': premium, 'Reason for Ineligibility': 'Premium < 500 (Line 3)'})
                continue

            # Line 4: Fresh/Old Business Validation
            review_flag = ""
            is_eligible_line4 = True
            is_motor = lob in ['312601', '312602', '312603']
            
            if not is_motor:
                # Path A (Non-Motor)
                src_ind = str(row.get('SOURCE INDICATOR', '')).upper()
                if 'POLICY RENEWAL' in src_ind:
                    is_eligible_line4 = False
                    reason = "Policy Renewal (Line 4A)"
                elif 'FRESH POLICY' not in src_ind:
                    review_flag = "Confirm it is fresh business as Source Indicator does not explicitly say Fresh Policy (Line 4A)."
            else:
                # Path B (Motor)
                if mot_df.empty:
                    review_flag = "Motor details missing. Cannot validate Previous Insurer (Line 4B)."
                else:
                    mot_row = mot_df[mot_df['POLICY NUMBER'] == pol_num]
                    if not mot_row.empty:
                        prev_ins = str(mot_row['PREVIOUS INSURER NAME'].iloc[0]).strip().upper() if 'PREVIOUS INSURER NAME' in mot_df.columns else ''
                        if prev_ins == 'THE NEW INDIA ASSURANCE COMPANY LTD':
                            prev_pol = str(mot_row['PREVIOUS POLICY NO'].iloc[0]) if 'PREVIOUS POLICY NO' in mot_df.columns else ''
                            try:
                                chars = prev_pol[8:10]
                                val = int(chars)
                                if val >= 25:
                                    is_eligible_line4 = False
                                    reason = f"Previous Policy digits >= 25 ({val}) (Line 4B)"
                            except:
                                review_flag = "Could not parse 9th/10th digits of Previous Policy (Line 4B)."
                    else:
                        review_flag = "Policy missing in Motor Details CSV (Line 4B)."

            if not is_eligible_line4:
                results_ineligible.append({'Policy Number': pol_num, 'Agent Code': agent_code, 'Premium': premium, 'Reason for Ineligibility': reason})
                continue

            # STREAMLIT_CHUNK:Evaluating Line 5 & Line 6 product mappings...
            # Line 5 & 6: LOB Categorization & Scoring
            pts = 0
            cat_num = 0
            prod_name = "Unmapped LOB"
            
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
                        
                        if m_prod == 'PRIVATE CAR':
                            if lob in ['312601', '312603']:
                                cat_num, pts, prod_name = 4, 2, 'Private Car'
                            else:
                                results_ineligible.append({'Policy Number': pol_num, 'Agent Code': agent_code, 'Premium': premium, 'Reason for Ineligibility': 'Liability Only (312602) not eligible for Private Car (Line 6)'})
                                continue
                        elif m_prod == 'COMMERCIAL VEHICLE':
                            if m_class == 'A - GOODS CARRYING' and pd.notna(m_gvw) and m_gvw <= 7500:
                                cat_num, pts, prod_name = 5, 3, 'Goods Carrying'
                            elif m_class == 'C - PASSENGER CARRYING':
                                taxi_bodies = ['SALOON', 'SEDAN', 'HATCH-BACK', 'STATION WAGON/WAGON', 'SUV', 'SPORTS CAR/SUPER CAR']
                                if m_body in taxi_bodies:
                                    cat_num, pts, prod_name = 5, 3, 'Taxis'
                                    review_flag += " Verify Seating Capacity <= 6 (Line 6)."
                                elif m_body == 'STAFF BUS':
                                    cat_num, pts, prod_name = 6, 4, 'Staff Bus'
                                else:
                                    results_ineligible.append({'Policy Number': pol_num, 'Agent Code': agent_code, 'Premium': premium, 'Reason for Ineligibility': 'Unrecognized Body Type for Passenger Carrying', 'Review Needed': 'Check manual records to verify if actual usage is Taxi (<=6) or Staff Bus (Line 6)'})
                                    continue
                            elif m_class == 'C2-SCHOOL BUS(CARRYING>6)':
                                cat_num, pts, prod_name = 6, 4, 'School Bus'
                            
                    else:
                        review_flag += " Missing in Motor Data to evaluate Cat rules."

            # STREAMLIT_CHUNK:Appending eligible record to results...
            results_eligible.append({
                'Policy Number': pol_num, 'Agent Code': agent_code, 'Agent Name': agent_name, 
                'Premium': premium, 'Product Category & Name': f"Cat {cat_num} - {prod_name}", 
                'Points': pts, 'Remarks': f"Meets criteria (Rule Line 5/6). mapped to {prod_name}", 'Review Needed': review_flag
            })

        # STREAMLIT_CHUNK:Consolidating final dataframes and generating summary...
        # --- END ITERATION ---
        
        new_eligible = pd.DataFrame(results_eligible)
        new_ineligible = pd.DataFrame(results_ineligible)
        
        # Concatenate and deduplicate ensuring 'first' keeps manual overrides
        final_eligible = pd.concat([pre_approved, new_eligible]).drop_duplicates(subset=['Policy Number'], keep='first')
        final_ineligible = pd.concat([pre_rejected, new_ineligible]).drop_duplicates(subset=['Policy Number'], keep='first')

        # Ensure core columns exist before grouping to prevent KeyErrors
        for col in ['Agent Code', 'Agent Name', 'Premium', 'Points']:
             if col not in final_eligible.columns:
                 final_eligible[col] = "Unknown" if 'Agent' in col else 0
                 
        final_eligible['Agent Code'] = final_eligible['Agent Code'].astype(str)
        final_eligible['Agent Name'] = final_eligible['Agent Name'].astype(str).replace(['nan', 'NaN', 'None', ''], "Unknown")

        summary_data = []
        if not final_eligible.empty:
            # Group strictly by unique identifier (Agent Code)
            grouped = final_eligible.groupby('Agent Code')
            
            for agent_code, group in grouped:
                # Resolve the best Agent Name for this Agent Code
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
            # Sort descending by Total Points
            summary_df = summary_df.sort_values(by='Total Points', ascending=False)

        return summary_df, final_eligible, final_ineligible

    except Exception as e:
        import traceback
        return None, None, f"A critical error occurred: {str(e)}\nTraceback: {traceback.format_exc()}"

# STREAMLIT_CHUNK:Rendering Streamlit UI...
# --- STREAMLIT UI LAYOUT ---
st.title("108 Drive Lense: Campaign Analyzer")
st.markdown("""
Welcome to the offline, secure data processor. 
Upload your exact CSV files from the core system. No data leaves your browser.
""")

col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("1. Premium Register")
    prem_file = st.file_uploader("Upload Premium CSV", type=['csv'])

with col2:
    st.subheader("2. Motor Details")
    mot_file = st.file_uploader("Upload Motor CSV (Optional)", type=['csv'])
    
with col3:
    st.subheader("3. Previous Work")
    prev_file = st.file_uploader("Upload Previous Output (.xlsx)", type=['xlsx'])
    st.caption("Upload a previously generated Excel file to keep your manual changes.")

if st.button("Process Campaign Data", type="primary"):
    if prem_file is None and prev_file is None:
        st.error("Please upload at least the Premium Register CSV or a Previous Output Excel file to begin.")
    else:
        with st.spinner("Executing rule engine..."):
            summary, el_log, in_log = process_campaign_data(prem_file, mot_file, prev_file)
            
            # If function returned an error string instead of dataframes
            if isinstance(in_log, str) and summary is None:
                st.error(in_log)
            else:
                st.success("Analysis Complete!")
                st.markdown("**Note:** Please manually include Overseas Mediclaim, Criti Protect, and CGL Policies in your Eligible sheet if applicable, as their exact LOB codes are currently unidentified. Report LOB codes via WhatsApp to wa.me/919656077625.")
                
                st.subheader("Category Reference Guide")
                with st.expander("View Category Numbers & Products", expanded=False):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown("""
                        * **Cat 1:** New India Mediclaim, Floater, Arogya Sanjeevani, Yuva Bharat, Overseas Travel Ease
                        * **Cat 2:** Top Up, Arogya Pragati Plus
                        * **Cat 3:** Cancer Guard
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
                        * **Cat 14:** Public Liability
                        * **Cat 15:** My Cyber Policy
                        """)

                st.subheader("Leaderboard Preview (Descending)")
                st.dataframe(summary)
                
                # --- ROBUST EXCEL GENERATION ---
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    # Write DataFrames to Excel
                    if summary is not None and not summary.empty:
                         summary.to_excel(writer, sheet_name='Agent Summary Scoreboard', index=False)
                    if el_log is not None and not el_log.empty:
                         el_log.to_excel(writer, sheet_name='Eligible Policies Log', index=False)
                    if in_log is not None and not in_log.empty:
                         in_log.to_excel(writer, sheet_name='Ineligible Policies Log', index=False)
                    
                    # Auto-adjust column widths
                    workbook = writer.book
                    for sheet_name in writer.sheets:
                        worksheet = writer.sheets[sheet_name]
                        # Set default width 
                        worksheet.set_default_row(15)
                        # We use a generic width assignment to avoid complex iteration logic here
                        worksheet.set_column('A:Z', 20) 
                
                # Create dynamic filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                file_name = f"108th_Campaign_Report_{timestamp}.xlsx"
                
                st.download_button(
                    label="📥 Download Secure Excel Report",
                    data=buffer.getvalue(),
                    file_name=file_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
