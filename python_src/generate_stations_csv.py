import pandas as pd
import os

# Official MTA Static Data URL
MTA_CSV_URL = "http://web.mta.info/developers/data/nyct/subway/Stations.csv"
OUTPUT_FILENAME = "nyc_subway_stations_list.csv"

def generate_clean_csv():
    print(f"[*] Downloading latest MTA stations data from official servers...")
    print(f"[*] URL: {MTA_CSV_URL}")
    
    try:
        # Read the raw CSV directly from the URL
        raw_df = pd.read_csv(MTA_CSV_URL)
        
        # Select only the columns relevant for the OLED Tracker project
        columns_to_keep = [
            'GTFS Stop ID', 
            'Stop Name', 
            'Daytime Routes', 
            'Borough', 
            'Line'
        ]
        
        clean_df = raw_df[columns_to_keep].copy()
        
        # Rename columns for a cleaner user interface
        clean_df.rename(columns={
            'GTFS Stop ID': 'Station_ID',
            'Stop Name': 'Station_Name',
            'Daytime Routes': 'Available_Lines',
            'Borough': 'Borough',
            'Line': 'Physical_Line'
        }, inplace=True)
        
        # Fill missing values (NaN) with empty strings
        clean_df.fillna("", inplace=True)
        
        # Sort stations alphabetically by name
        clean_df.sort_values(by='Station_Name', inplace=True)
        
        # Determine the absolute directory of this script file
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Construct the absolute path for the output file
        filepath = os.path.join(script_dir, OUTPUT_FILENAME)
        
        # Export the dataframe to a CSV file in the same directory
        clean_df.to_csv(filepath, index=False, encoding='utf-8')
        
        print("\n[+] SUCCESS!")
        print(f"[+] Cleaned stations list has been saved to:")
        print(f"    -> {filepath}")
        print(f"[+] Total stations exported: {len(clean_df)}")
        print("[+] You can now use this file to look up Station IDs for the tracker.")

    except Exception as e:
        print(f"\n[!] An error occurred while generating the CSV: {e}")

if __name__ == "__main__":
    generate_clean_csv()