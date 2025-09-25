import requests
from bs4 import BeautifulSoup
import json
import unicodedata

COMMON_URL = "https://mavlink.io/en/messages/common.html"
ARDUPILOT_URL = "https://mavlink.io/en/messages/ardupilotmega.html"
OUTPUT_FILE = "mavlink_reference.json"

def fetch_common():
    """Fetch MAVLink common message definitions"""
    # Fetch the page
    resp = requests.get(COMMON_URL)
    resp.encoding = "utf-8"  # force correct encoding
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    log_data = {}

    # Each message has an <h3> with the message name
    # Limit to first 10 messages for testing
    messages = soup.find_all("h3")
    
    for msg in messages:
        msg_name = msg.get("id")  # e.g. "HEARTBEAT"
        if not msg_name:
            continue
            
        # Find the first non-empty <p> that doesn't start with "DEPRECATED"
        description = ""
        p_tag = msg.find_next_sibling("p")
        while p_tag:
            desc_text = p_tag.get_text(strip=True)
            if desc_text and not desc_text.startswith("DEPRECATED"):
                description = desc_text
                break
            p_tag = p_tag.find_next_sibling("p")

        fields = {}
        table = msg.find_next_sibling("table")
        if table:
            for row in table.find_all("tr")[1:]:  # skip header
                cols = [c.get_text(strip=True) for c in row.find_all("td")]
                if not cols:
                    continue
                field_name = cols[0]
                field_type = cols[1] if len(cols) > 1 else ""
                unit = cols[2] if len(cols) > 2 else ""
                desc = cols[3] if len(cols) > 3 else ""
                # Clean encoding for unit - normalize Unicode characters
                unit = unicodedata.normalize('NFKD', unit)
                fields[field_name] = {
                    "type": field_type,
                    "unit": unit,
                    "description": desc,
                }

        log_data[msg_name] = {
            "description": description,
            "fields": fields,
        }

    return log_data

def fetch_ardupilotmega():
    """Fetch ArduPilot dialect message definitions"""
    # Fetch the page
    resp = requests.get(ARDUPILOT_URL)
    resp.encoding = "utf-8"  # force correct encoding
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    log_data = {}

    # Each message has an <h3> with the message name
    messages = soup.find_all("h3")
    
    for msg in messages:
        msg_name = msg.get("id")  # e.g. "AHRS"
        if not msg_name:
            continue
            
        # Find the first non-empty <p> that doesn't start with "DEPRECATED"
        description = ""
        p_tag = msg.find_next_sibling("p")
        while p_tag:
            desc_text = p_tag.get_text(strip=True)
            if desc_text and not desc_text.startswith("DEPRECATED"):
                description = desc_text
                break
            p_tag = p_tag.find_next_sibling("p")

        fields = {}
        table = msg.find_next_sibling("table")
        if table:
            for row in table.find_all("tr")[1:]:  # skip header
                cols = [c.get_text(strip=True) for c in row.find_all("td")]
                if not cols:
                    continue
                field_name = cols[0]
                field_type = cols[1] if len(cols) > 1 else ""
                unit = cols[2] if len(cols) > 2 else ""
                desc = cols[3] if len(cols) > 3 else ""
                # Clean encoding for unit - normalize Unicode characters
                unit = unicodedata.normalize('NFKD', unit)
                fields[field_name] = {
                    "type": field_type,
                    "unit": unit,
                    "description": desc,
                }

        log_data[msg_name] = {
            "description": description,
            "fields": fields,
        }

    return log_data

def merge_definitions(common_defs, ardupilot_defs):
    """Merge common and ArduPilot definitions, preferring ArduPilot for conflicts"""
    # ArduPilot definitions take precedence for any conflicts
    return {**common_defs, **ardupilot_defs}

if __name__ == "__main__":
    print("Fetching MAVLink common messages...")
    common_data = fetch_common()
    
    print("Fetching ArduPilot dialect messages...")
    ardupilot_data = fetch_ardupilotmega()
    
    print("Merging definitions...")
    merged_data = merge_definitions(common_data, ardupilot_data)

    # Save to JSON
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(merged_data, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(merged_data)} total message definitions to {OUTPUT_FILE}")
    print(f"  - {len(common_data)} from MAVLink common")
    print(f"  - {len(ardupilot_data)} from ArduPilot dialect")
