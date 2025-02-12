import streamlit as st
import pandas as pd
import requests
import base64
from io import BytesIO, StringIO
from PyPDF2 import PdfReader
import csv
import re
from collections import defaultdict

# Constants
API_BASE_URL = "https://api.company-information.service.gov.uk"
PDF_DOWNLOAD_URL = "https://find-and-update.company-information.service.gov.uk"

# Initialize session state
if "company_data" not in st.session_state:
    st.session_state.company_data = pd.DataFrame(columns=["Company Legal Name", "Company Number", "Uploaded Statement Date"])
if "pulled_data" not in st.session_state:
    st.session_state.pulled_data = pd.DataFrame(columns=["Company Legal Name", "Company Number", "Pulled Statement Date"])
if "updates_found" not in st.session_state:
    st.session_state.updates_found = pd.DataFrame()

# Helper functions
def get_company_number(legal_name, api_key):
    """Fetch the company number using the legal name."""
    try:
        url = f"{API_BASE_URL}/search/companies?q={legal_name}"
        headers = {"Authorization": f"Basic {base64.b64encode(f'{api_key}:'.encode()).decode()}"}
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return None
        data = response.json()
        items = data.get("items", [])
        for item in items:
            if item.get("title", "").lower() == legal_name.lower():
                return item.get("company_number")
        return None
    except Exception as e:
        st.error(f"Error fetching company number for '{legal_name}': {e}")
        return None

def fetch_latest_cs01(company_number, api_key):
    """Fetch the latest CS01 filing details including the PDF content."""
    try:
        url = f"{API_BASE_URL}/company/{company_number}/filing-history"
        headers = {"Authorization": f"Basic {base64.b64encode(f'{api_key}:'.encode()).decode()}"}
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return None, None
        filings = response.json().get("items", [])
        for filing in filings:
            if filing.get("type") == "CS01":
                pdf_url = f"{PDF_DOWNLOAD_URL}/company/{company_number}/filing-history/{filing.get('transaction_id')}/document?format=pdf&download=0"
                pdf_response = requests.get(pdf_url)
                if pdf_response.status_code == 200:
                    return filing.get("date"), pdf_response.content
        return None, None
    except Exception as e:
        st.error(f"Error fetching CS01 data for company number '{company_number}': {e}")
        return None, None

def extract_text_from_pdf(pdf_content):
    """Extract text from a PDF file."""
    try:
        pdf_reader = PdfReader(BytesIO(pdf_content))
        return "\n".join(page.extract_text() for page in pdf_reader.pages if page.extract_text())
    except Exception as e:
        st.error(f"Error extracting text from PDF: {e}")
        return ""

def process_text_to_csv(text_content, legal_name, company_number):
    """Process extracted PDF text and convert it into a CSV format."""
    lines = text_content.split("\n")
    csv_data = [
        ["Company Legal Name", legal_name],
        ["Company Number", company_number],
        ["Statement Date", ""],  # Placeholder
        [],  # Separator
    ]
    statement_date = ""
    shareholder_data = []  # Collect shareholder details
    share_totals = defaultdict(int)

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Extract confirmation statement date
        if line.startswith("Statement date:"):
            statement_date = line.split(":")[1].strip()
            csv_data[2][1] = statement_date

        # Detect shareholding line
        if line.startswith("Shareholding"):
            buffer = line
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                if next_line.startswith("Name:") or next_line.startswith("Shareholding"):
                    break
                buffer += " " + next_line
                j += 1

            # Extract shareholding details
            shareholding_number = re.search(r"Shareholding\s+(\d+):", buffer)
            shareholding_number = shareholding_number.group(1) if shareholding_number else "Unknown"

            total_shares_match = re.search(r"(\d+)\s+([A-Za-z\s]+)\s+shares\s+held", buffer, re.IGNORECASE)
            if total_shares_match:
                amount_of_shares = int(total_shares_match.group(1))
                type_of_shares = total_shares_match.group(2).strip().title()
                share_totals[type_of_shares] += amount_of_shares
            else:
                amount_of_shares = "Unknown"
                type_of_shares = "Unknown"

            shareholder_name = ""
            if j < len(lines) and lines[j].strip().startswith("Name:"):
                shareholder_name = lines[j].strip().split(":")[1].strip()

            shareholder_data.append([shareholding_number, amount_of_shares, type_of_shares, shareholder_name])
            i = j
        else:
            i += 1

    # Add calculated totals and shareholder data
    csv_data.append(["Type of Shares", "Total Number of Shares"])
    for share_type, total in share_totals.items():
        csv_data.append([share_type, total])

    csv_data.append([])  # Separator
    csv_data.append(["Shareholding #", "Amount of Shares", "Type of Shares", "Shareholder Name"])
    csv_data.extend(shareholder_data)

    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerows(csv_data)
    csv_buffer.seek(0)
    return csv_buffer.getvalue(), statement_date

def process_data(api_key):
    updates = []
    pulled_data = []

    for _, row in st.session_state.company_data.iterrows():
        company_number = row.get("Company Number")
        legal_name = row.get("Company Legal Name")
        uploaded_date = row.get("Uploaded Statement Date")

        # Fetch company number if missing
        if pd.isna(company_number):
            company_number = get_company_number(legal_name, api_key)

        # Fetch latest CS01 filing
        pulled_date = None
        pdf_content = None
        csv_content = None
        if company_number:
            pulled_date, pdf_content = fetch_latest_cs01(company_number, api_key)
            if pdf_content:
                text_content = extract_text_from_pdf(pdf_content)
                csv_content, extracted_date = process_text_to_csv(text_content, legal_name, company_number)

        pulled_data.append({
            "Company Legal Name": legal_name,
            "Company Number": company_number,
            "Pulled Statement Date": pulled_date,
            "PDF Content": pdf_content,
            "CSV Content": csv_content,
        })

    # Convert to DataFrame
    pulled_df = pd.DataFrame(pulled_data)
    st.session_state.pulled_data = pulled_df

    # Flag discrepancies
    updates_df = pulled_df.merge(st.session_state.company_data, on="Company Legal Name", how="left")
    updates_df = updates_df[(updates_df["Uploaded Statement Date"] != updates_df["Pulled Statement Date"]) | 
                            (updates_df["Company Number_x"] != updates_df["Company Number_y"])]
    
    st.session_state.updates_found = updates_df

# App interface
st.title("CS01 Filing Tracker")

if st.button("Clear All"):
    st.session_state.company_data = pd.DataFrame(columns=["Company Legal Name", "Company Number", "Uploaded Statement Date"])
    st.session_state.pulled_data = pd.DataFrame()
    st.session_state.updates_found = pd.DataFrame()

uploaded_file = st.file_uploader("Upload CSV:", type="csv")
if uploaded_file:
    st.session_state.company_data = pd.read_csv(uploaded_file)

if st.button("Process"):
    api_key = st.secrets["API"]["key"]
    process_data(api_key)

st.subheader("Download Updated List")
if not st.session_state.pulled_data.empty:
    csv_buffer = StringIO()
    st.session_state.pulled_data.to_csv(csv_buffer, index=False)
    st.download_button("Download Updated List", csv_buffer.getvalue(), "updated_list.csv", "text/csv")
