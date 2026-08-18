<!-- ... existing code ... -->
        # STREAMLIT_CHUNK:Handling Previous Output File overrides...
        # 3. Load Master Policy List (Optional for Fresh Tracking)
        master_df = pd.DataFrame()
        if prev_output_file:
            try:
                master_raw = pd.read_excel(prev_output_file, sheet_name='Total')
                master_raw.columns = [str(c).strip().upper() for c in master_raw.columns]
                
                # Map potential column names
                if 'POLICY_NUMBER' in master_raw.columns and 'POLICY NUMBER' not in master_raw.columns:
                    master_raw.rename(columns={'POLICY_NUMBER': 'POLICY NUMBER'}, inplace=True)
                    
                if 'POLICY NUMBER' in master_raw.columns and 'TYPE_OF_POLICIES' in master_raw.columns:
                    master_df = clean_policy_numbers(master_raw, 'POLICY NUMBER')
                else:
                    st.warning("Master List uploaded, but could not find 'Policy Number' or 'TYPE_OF_POLICIES' columns in the 'Total' sheet.")
            except Exception as e:
                st.warning(f"Could not read 'Total' sheet from Master File. Error: {e}")

        # STREAMLIT_CHUNK:Beginning row-by-row rule evaluations...
        # 4. INITIALIZE LOGS
        eligible_log = pd.DataFrame()
        ineligible_log = pd.DataFrame()

        # --- BEGIN RULE EVALUATIONS ---
<!-- ... existing code ... -->
            # Check Master Sheet override for Fresh Status
            master_override_fresh = False
            if not master_df.empty:
                master_match = master_df[master_df['POLICY NUMBER'] == pol_num]
                if not master_match.empty:
                    type_val = str(master_match['TYPE_OF_POLICIES'].iloc[0]).strip().upper()
                    if type_val == 'NEW POLICY':
                        master_override_fresh = True

            # Line 4: Fresh/Old Business Validation
            review_flag = ""
            is_eligible_line4 = True
            is_motor = lob in ['312601', '312602', '312603']
<!-- ... existing code ... -->
        new_ineligible = pd.DataFrame(results_ineligible)
        
        final_eligible = new_eligible.drop_duplicates(subset=['Policy Number'], keep='first') if not new_eligible.empty else pd.DataFrame()
        final_ineligible = new_ineligible.drop_duplicates(subset=['Policy Number'], keep='first') if not new_ineligible.empty else pd.DataFrame()

        # Ensure core columns exist before grouping to prevent KeyErrors
        for col in ['Agent Code', 'Agent Name', 'Premium', 'Points']:
<!-- ... existing code ... -->
            if isinstance(in_log, str) and summary is None:
                st.error(in_log)
            else:
                st.success("Analysis Complete!")
<!-- ... existing code ... -->
        with st.spinner("Executing rule engine..."):
            # Note: We pass prev_file into the 3rd argument (previously prev_output_file, now repurposed for master list)
            # The 4th argument (master_file) is no longer needed and can be passed as None
            summary, el_log, in_log = process_campaign_data(prem_file, mot_file, prev_file, None)
            
            if isinstance(in_log, str) and summary is None:
<!-- ... existing code ... -->
st.title("🏆 108 Drive Lense: Campaign Analyzer 🤖 Ver 3.1")
st.markdown("""
Welcome to the offline, secure data processor. 
Upload your exact CSV files from the core system. No data leaves your browser.
""")

col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Premium Register")
    st.info("**Download Path:**\n`Dashboard -> Core reports -> Premium -> Premium Register`")
    prem_file = st.file_uploader("Upload Premium CSV", type=['csv'])

with col2:
    st.subheader("2. Motor Details")
    st.info("**Download Path:**\n`Dashboard -> Core reports -> Motor(Premium) -> Motor Business Details`")
    mot_file = st.file_uploader("Upload Motor CSV (Optional)", type=['csv'])

col3 = st.columns(1)[0]

with col3:
    st.markdown("<div style='opacity: 0.6;'>", unsafe_allow_html=True)
    st.subheader("3. HO Master Policy List up to 11th (Optional for tracking Fresh/Renewal Only)")
    st.info("**Fresh Overrides:**\nUpload the 'Total' sheet to auto-verify Fresh Policies.")
    prev_file = st.file_uploader("Upload Master List (.xlsx)", type=['xlsx'])
    st.markdown("</div>", unsafe_allow_html=True)

if st.button("Process Campaign Data", type="primary"):
    if prem_file is None:
        st.error("Please upload the Premium Register CSV to begin.")
<!-- ... existing code ... -->
