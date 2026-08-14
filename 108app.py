# STREAMLIT_CHUNK:Updating imports and config...
import streamlit as st
import pandas as pd
import numpy as np
import io
from datetime import datetime

# --- UI CONFIGURATION ---
st.set_page_config(
    page_title="108 Drive Lense Campaign",
    page_icon="🏆",
    layout="wide"
)

# STREAMLIT_CHUNK:Defining data cleaning helper...
# --- CORE LOGIC: DATA CLEANING ---
def clean_policy_numbers(df, col_name='POLICY NUMBER'):
    """Aggressively cleans policy numbers to fix zero-overlap issues."""
    if col_name in df.columns:
        df[col_name] = df[col_name].astype(str).str.strip().str.rstrip(':')
    return df

# STREAMLIT_CHUNK:Starting main processing function...
# --- CORE LOGIC: RULE ENGINE ---
def process_campaign_data(premium_file, motor_file=None, prev_output_file=None):
    try:
        # STREAMLIT_CHUNK:Loading and standardizing Premium Data...
        # 1. Load Premium Data
        prem_df = pd.read_csv(premium_file)
        
        # Convert all columns to uppercase and strip whitespace for robust matching
        prem_df.columns = [str(c).strip().upper() for c in prem_df.columns]
        
        # Ensure required columns exist using UPPERCASE names
        required_prem_cols = ['COLLECTION DATE', 'PREMIUM AMOUNT', 'POLICY NUMBER', 'AGENT CODE', 'AGENT NAME', 'SOURCE INDICATOR', 'ENDORSEMENT NUMBER']
        missing_cols = [col for col in required_prem_cols if col not in prem_df.columns and col.replace('PREMIUM AMOUNT', 'NET PREMIUM') not in prem_df.columns]
        
        if missing_cols:
             return None, None, f"Error: Premium CSV is missing required columns (or they are named differently): {', '.join(missing_cols)}"
             
        prem_df = clean_policy_numbers(prem_df, 'POLICY NUMBER')

        # Handle Net Premium variation
        prem_col_name = 'PREMIUM AMOUNT' if 'PREMIUM AMOUNT' in prem_df.columns else 'NET PREMIUM'
        prem_df[prem_col_name] = pd.to_numeric(prem_df[prem_col_name], errors='coerce').fillna(0)

        # STREAMLIT_CHUNK:Loading and standardizing Motor Data...
        # 2. Load Motor Data (Optional)
        mot_df = pd.DataFrame()
        if motor_file:
            mot_df = pd.read_csv(motor_file)
            mot_df.columns = [str(c).strip().upper() for c in mot_df.columns]
            mot_df = clean_policy_numbers(mot_df, 'POLICY NUMBER') # Updated to look for upper case if it was standardized
            # If the motor file specifically uses POLICY_NUMBER with an underscore, handle that:
            if 'POLICY_NUMBER' in mot_df.columns and 'POLICY NUMBER' not in mot_df.columns:
                mot_df.rename(columns={'POLICY_NUMBER': 'POLICY NUMBER'}, inplace=True)
            
        # STREAMLIT_CHUNK:Handling Previous Output File overrides...
        # 3. Handle Previous Output Override (Excel-Only or Excel+CSV)
        pre_approved = pd.DataFrame()
        pre_rejected = pd.DataFrame()
        
        if prev_output_file:
            try:
                # Note: We do NOT uppercase Excel columns because they must match our exact output format
                prev_eligible = pd.read_excel(prev_output_file, sheet_name='Eligible Policies Log')
                prev_ineligible = pd.read_excel(prev_output_file, sheet_name='Ineligible Policies Log')
                
                prev_eligible = clean_policy_numbers(prev_eligible, 'Policy Number')
                prev_ineligible = clean_policy_numbers(prev_ineligible, 'Policy Number')
                
                if 'Remarks' in prev_eligible.columns:
                    prev_eligible['Remarks'] = "Since you uploaded it as already listed eligible - " + prev_eligible['Remarks'].astype(str)
                if 'Reason for Ineligibility' in prev_ineligible.columns:
                    prev_ineligible['Reason for Ineligibility'] = "Since you uploaded it as already listed ineligible - " + prev_ineligible['Reason for Ineligibility'].astype(str)
                
                pre_approved = prev_eligible
                pre_rejected = prev_ineligible
                
                # ZERO OVERLAP WARNING CHECK
                if not prem_df.empty and not pre_approved.empty:
                    # Note: We are comparing 'POLICY NUMBER' (Premium CSV) with 'Policy Number' (Excel)
                    overlap = prem_df['POLICY NUMBER'].isin(pre_approved['Policy Number']).any()
                    if not overlap:
                        st.warning("🚨 **CRITICAL WARNING:** The previous output file you uploaded shares ZERO matching policies with the new Premium CSV data!
