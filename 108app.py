import pandas as pd
import numpy as np
from datetime import datetime
import re
import os

def get_column(df, possible_names):
    """Helper to find column names regardless of exact casing/spacing."""
    for col in df.columns:
        for name in possible_names:
            # Strip non-alphanumeric and compare
            clean_col = re.sub(r'[^a-zA-Z0-9]', '', col.lower())
            clean_name = re.sub(r'[^a-zA-Z0-9]', '', name.lower())
            if clean_name in clean_col:
                return col
    return None

# Mapping LOB ID to (Category Name, Default Points)
LOB_MAPPING = {
    '612695': ('Health - Basic', 4), '612628': ('Health - Basic', 4),
    '612693': ('Health - Basic', 4), '612624': ('Health - Basic', 4), '692530': ('Health - Basic', 4),
    '612678': ('Health - Top Up', 3), '612650': ('Health - Top Up', 3),
    '612637': ('Health - Critical', 5),
    '112686': ('Property - Sookshma', 4), '112680': ('Property - Sookshma', 4),
    '112643': ('Property - Laghu', 5),
    '652601': ('PA / RAK', 2), '672601': ('PA / RAK', 2),
    '682601': ('PA / RAK', 2), '482668': ('PA / RAK', 2),
    '412601': ('WC Policy', 3),
    '462630': ('Mahila Udyam / Bima Saathi', 3),
    '462607': ('Jewellers Block', 5),
    '482605': ('Householder / Shopkeeper', 4), '482606': ('Householder / Shopkeeper', 4),
    '492607': ('Public Liability', 4),
    'TBD': ('My Cyber Policy', 1) # Added Cyber Policy with placeholder ID
}

def resolve_motor_points(row):
    """Cross-references LOB 312601 with Motor specifics to award points."""
    if row['LOB_ID'] != '312601':
        # Non-motor policies use the base mapping directly
        return row['Base_Points'], row['Base_Category']
    
    veh_class = str(row.get('CLASS_OF_VEHICLE', '')).lower()
    gvw = pd.to_numeric(row.get('GROSS_VEHICLE_WEIGHT', 0), errors='coerce')
    seating = pd.to_numeric(row.get('SEATING_CAPACITY', 0), errors='coerce')
    
    # 2 Pts: Private Car Package
    if 'private car' in veh_class:
        return 2, 'Motor - Private Car'
        
    # 3 Pts: GCV with GVW < 7500 Kgs OR Taxis seating <= 6
    if ('goods carrying' in veh_class and (pd.isna(gvw) or gvw < 7500)) or \
       ('taxi' in veh_class and (pd.isna(seating) or seating <= 6)):
        return 3, 'Motor - GCV/Taxi'
        
    # 4 Pts: School / Staff Bus
    if 'passenger carrying bus' in veh_class or 'school' in veh_class or 'staff' in veh_class:
        return 4, 'Motor - Bus'
        
    # Default fallback for Motor if criteria not strictly met
    return 0, 'Motor - Unclassified'

def generate_campaign_report(premium_csv, motor_csv, output_excel="108_Foundation_Day_Rankings.xlsx"):
    print("Initializing Data Ingestion...")
    try:
        df_prem = pd.read_csv(premium_csv)
        df_motor = pd.read_csv(motor_csv)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Please ensure both CSV files are in the same directory as this script.")
        return

    # Identify essential columns flexibly
    col_pol_prem = get_column(df_prem, ['policynumber', 'policyno', 'polno'])
    col_pol_motor = get_column(df_motor, ['policynumber', 'policyno', 'polno'])
    col_date = get_column(df_prem, ['issuedate', 'inceptiondate', 'startdate'])
    col_premium = get_column(df_prem, ['premiumamount', 'basepremium', 'netpremium'])
    col_agent_name = get_column(df_prem, ['agentname', 'intermediaryname'])
    col_agent_code = get_column(df_prem, ['agentcode', 'intermediarycode'])
    
    # Check if necessary columns were found
    if not all([col_pol_prem, col_date, col_premium, col_agent_code]):
        raise ValueError("Critical columns missing in Premium Register. Please check file formatting.")

    print("Filtering Timeframe & Premium Threshold...")
    # Convert dates and filter (23-Jul-2026 to 31-Aug-2026)
    df_prem[col_date] = pd.to_datetime(df_prem[col_date], errors='coerce', dayfirst=True)
    mask_date = (df_prem[col_date] >= '2026-07-23') & (df_prem[col_date] <= '2026-08-31')
    
    # Filter Premium Amount (>= 500)
    df_prem[col_premium] = pd.to_numeric(df_prem[col_premium], errors='coerce')
    mask_premium = df_prem[col_premium] >= 500
    
    # Apply Filters
    df_valid = df_prem[mask_date & mask_premium].copy()
    
    print("Extracting LOB & Applying Knowledge Base Mapping...")
    # Extract LOB ID (Characters 7 to 12)
    df_valid['LOB_ID'] = df_valid[col_pol_prem].astype(str).str[6:12]
    
    # Map basic points
    df_valid['Base_Category'] = df_valid['LOB_ID'].map(lambda x: LOB_MAPPING.get(x, ('Uncategorized', 0))[0])
    df_valid['Base_Points'] = df_valid['LOB_ID'].map(lambda x: LOB_MAPPING.get(x, ('Uncategorized', 0))[1])
    
    # Merge with Motor data for cross-referencing
    print("Cross-referencing Motor Business Policies...")
    # Normalize policy numbers for clean merging
    df_valid['Join_Key'] = df_valid[col_pol_prem].astype(str).str.strip().str.upper()
    df_motor['Join_Key'] = df_motor[col_pol_motor].astype(str).str.strip().str.upper()
    
    df_merged = pd.merge(df_valid, df_motor, on='Join_Key', how='left')
    
    # Apply Motor Specific Rules
    points_and_cats = df_merged.apply(resolve_motor_points, axis=1)
    df_merged['Points_Awarded'] = [x[0] for x in points_and_cats]
    df_merged['Product_Category'] = [x[1] for x in points_and_cats]
    
    # Filter out policies that didn't earn points (unmapped LOBs)
    df_scored = df_merged[df_merged['Points_Awarded'] > 0].copy()

    print("Calculating Agent Rankings & Diversification...")
    
    # Create Policy Log Sheet Data
    policy_log = df_scored[[
        col_agent_code, col_pol_prem, 'LOB_ID', 'Product_Category', col_premium, 'Points_Awarded'
    ]].copy()
    
    # Rename for output clarity
    policy_log.columns = [
        'Agent Code', 'Policy Number', 'LOB ID', 'Product Category', 'Base Premium', 'Points Awarded'
    ]
    
    # Aggregate to Summary Ranking
    summary = df_scored.groupby([col_agent_name, col_agent_code]).agg(
        Total_Points=('Points_Awarded', 'sum'),
        Unique_Categories_Sold=('Product_Category', 'nunique')
    ).reset_index()
    
    summary.columns = ['Agent Name', 'Agent Code', 'Total Points', 'Unique Categories Sold']
    
    # Determine Reward Eligibility: >= 108 points AND >= 5 unique categories
    summary['Eligible for Reward'] = np.where(
        (summary['Total Points'] >= 108) & (summary['Unique Categories Sold'] >= 5),
        'Yes',
        'No'
    )
    
    # Sort by Top Performing Agents
    summary = summary.sort_values(by=['Total Points', 'Unique Categories Sold'], ascending=[False, False])

    print(f"Exporting Report to {output_excel}...")
    with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
        summary.to_excel(writer, sheet_name='Summary Ranking', index=False)
        policy_log.to_excel(writer, sheet_name='Policy Log', index=False)
        
    print(f"Success! The campaign analysis is complete. File saved as {output_excel}")

if __name__ == "__main__":
    # Ensure correct file names from user input are used
    PREMIUM_FILE = "Premium Register New Tables.csv"
    MOTOR_FILE = "Motor Business Details (1).csv"
    OUTPUT_FILE = "108_Foundation_Day_Rankings.xlsx"
    
    if os.path.exists(PREMIUM_FILE) and os.path.exists(MOTOR_FILE):
        generate_campaign_report(PREMIUM_FILE, MOTOR_FILE, OUTPUT_FILE)
    else:
        print("Waiting for files to be present in the directory. Please ensure 'Premium Register New Tables.csv' and 'Motor Business Details (1).csv' are available.")
