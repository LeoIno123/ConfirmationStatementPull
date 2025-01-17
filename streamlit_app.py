import streamlit as st
import requests
import base64
from io import BytesIO, StringIO
from PyPDF2 import PdfReader
import csv
import re

# Constants
API_BASE_URL = "https://api.company-information.service.gov.uk"
PDF_DOWNLOAD_URL = "https://find-and-update.company-information.service.gov.uk"

def get_company_number(legal_name, api_key):
    """Fetch the company number using the legal name."""
    url = f"{API_BASE_URL}/search/companies?q={legal_name}"
    headers = {"Authorization": f"Basic {base64.b64encode(f'{api_key}:'.encode()).decode()}"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        st.error("Failed to fetch company information.")
        return None
    data = response.json()
    return data.get("items", [{}])[0].get("company_number")

def get_confirmation_statement_transaction_ids(company_number, api_key):
    """Fetch the transaction IDs for the latest 100 items, and filter for 'CS01' type."""
    url = f"{API_BASE_URL}/company/{company_number}/filing-history?items_per_page=100"
    headers = {"Authorization": f"Basic {base64.b64encode(f'{api_key}:'.encode()).decode()}"}
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        st.error("Failed to fetch filing history.")
        return []
    
    data = response.json()
    items = data.get("items", [])
    transaction_ids = [
        item.get("transaction_id")
        for item in items
        if item.get("type") and item["type"].lower() == "cs01"
    ]
    return transaction_ids[:3]  # Limit to the last 3 CS01 IDs

def download_pdf(company_number, transaction_id):
    """Download the confirmation statement PDF."""
    url = f"{PDF_DOWNLOAD_URL}/company/{company_number}/filing-history/{transaction_id}/document?format=pdf&download=0"
    response = requests.get(url)
    if response.status_code == 200:
        return response.content
    else:
        return None

def extract_text_from_pdf(pdf_content):
    """Extract text from a PDF file."""
    pdf_reader = PdfReader(BytesIO(pdf_content))
    text_content = "\n".join(page.extract_text() for page in pdf_reader.pages)
    return text_content

import streamlit as st
import csv
import re
from io import StringIO, BytesIO
from PyPDF2 import PdfReader
import requests
import base64

# Constants
API_BASE_URL = "https://api.company-information.service.gov.uk"
PDF_DOWNLOAD_URL = "https://find-and-update.company-information.service.gov.uk"

def extract_text_from_pdf(pdf_content):
    """Extract text from a PDF file."""
    pdf_reader = PdfReader(BytesIO(pdf_content))
    text_content = "\n".join(page.extract_text() for page in pdf_reader.pages)
    return text_content

def process_text_to_csv(text_content, legal_name, company_number, statement_number):
    """Process text content to generate a CSV for an individual statement."""
    lines = text_content.split("\n")

    # Statement info in column A
    csv_data = [
        ["Company Legal Name"], [legal_name], [],
        ["Company Number"], [company_number], [],
        ["Statement Date"], [""], []  # Placeholder for the statement date
    ]

    # Shareholder data headers in C1:F1
    shareholder_headers = ["Shareholding #", "Amount of Shares", "Type of Shares", "Shareholder Name"]
    if len(csv_data[0]) < 4:  # Add horizontal headers only if not already present
        csv_data[0].extend([""] * 1 + shareholder_headers)

    statement_date = ""
    shareholder_data = []  # To collect rows of shareholder information

    for i, line in enumerate(lines):
        line = line.strip()

        if line.startswith("Confirmation Statement date:"):
            statement_date = line.split(":")[1].strip()
            csv_data[7][0] = statement_date  # Update the placeholder for the statement date

        if line.startswith("Shareholding"):
            # Extract shareholder details
            parts = line.split(":")
            shareholding_number = parts[0].split()[-1]
            shareholding_details = parts[1].strip().split()
            amount_of_shares = shareholding_details[0]
            raw_type_of_shares = " ".join(shareholding_details[1:])
            type_of_shares_match = re.search(r"(.*?)\s+shares", raw_type_of_shares.lower())
            type_of_shares = type_of_shares_match.group(1).title() if type_of_shares_match else "Unknown"
            shareholder_name = ""

            # Look for the shareholder name
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                if next_line.startswith("Name:"):
                    shareholder_name = next_line.split(":")[1].strip()
                    break
                j += 1

            # Collect shareholder data
            shareholder_data.append([shareholding_number, amount_of_shares, type_of_shares, shareholder_name or "PENDING"])

    # Append shareholder data under B2:E2 (headers are in B1:E1)
    for row in shareholder_data:
        csv_data.append([""] + row)  # Append data starting from Column B

    # Create CSV buffer
    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerows(csv_data)
    csv_buffer.seek(0)
    return csv_buffer, statement_date




def consolidate_csvs(csv_buffers):
    """Consolidate individual CSV buffers as horizontally joined tables."""
    consolidated_rows = []
    max_rows = 0

    tables = []
    for buf in csv_buffers:
        buf.seek(0)
        rows = list(csv.reader(buf))
        tables.append(rows)
        max_rows = max(max_rows, len(rows))

    for i in range(max_rows):
        row = []
        for table in tables:
            if i < len(table):
                row.extend(table[i])
            else:
                row.extend([""] * len(table[0]))
            row.append("")  # Single-column gap
        consolidated_rows.append(row[:-1])  # Remove last gap

    # Create consolidated CSV buffer
    consolidated_buffer = StringIO()
    writer = csv.writer(consolidated_buffer)
    writer.writerows(consolidated_rows)
    consolidated_buffer.seek(0)
    return consolidated_buffer

def main():
    st.title("Company Confirmation Statement Downloader")

    # Initialize session state
    if "pdf_files" not in st.session_state:
        st.session_state.pdf_files = []
    if "text_files" not in st.session_state:
        st.session_state.text_files = []
    if "csv_files" not in st.session_state:
        st.session_state.csv_files = []
    if "consolidated_csv" not in st.session_state:
        st.session_state.consolidated_csv = ""

    # Input for company legal name
    legal_name = st.text_input("Enter Company Legal Name:", "")

    if st.button("Process"):
        if not legal_name.strip():
            st.error("Please enter a valid company name.")
            return

        # Fetch company details using API key
        api_key = st.secrets["API"]["key"]
        company_number = get_company_number(legal_name, api_key)
        if not company_number:
            st.error("Company not found.")
            return

        # Get transaction IDs for confirmation statements
        transaction_ids = get_confirmation_statement_transaction_ids(company_number, api_key)
        if not transaction_ids:
            st.error("No confirmation statements found.")
            return

        # Reset session state
        st.session_state.pdf_files = []
        st.session_state.text_files = []
        st.session_state.csv_files = []
        csv_buffers = []

        for idx, transaction_id in enumerate(transaction_ids):
            # Download PDF and extract text
            pdf_content = download_pdf(company_number, transaction_id)
            if not pdf_content:
                continue

            # File names
            pdf_name = f"{legal_name}_statement_{idx + 1}.pdf"
            txt_name = f"{legal_name}_statement_{idx + 1}.txt"
            csv_name = f"{legal_name}_statement_{idx + 1}.csv"

            # Store PDFs and text files
            st.session_state.pdf_files.append((pdf_name, pdf_content))
            text_content = extract_text_from_pdf(pdf_content)
            st.session_state.text_files.append((txt_name, text_content))

            # Process text into CSV format
            csv_buffer, _ = process_text_to_csv(
                text_content, legal_name, company_number, idx + 1
            )
            st.session_state.csv_files.append((csv_name, csv_buffer.getvalue()))
            csv_buffers.append(csv_buffer)

        # Consolidate CSVs into a single file
        st.session_state.consolidated_csv = consolidate_csvs(csv_buffers).getvalue()

    # Add download buttons
    for pdf_name, pdf_content in st.session_state.pdf_files:
        st.download_button(label=f"Download {pdf_name}", data=pdf_content, file_name=pdf_name, mime="application/pdf")

    for txt_name, txt_content in st.session_state.text_files:
        st.download_button(label=f"Download {txt_name}", data=txt_content, file_name=txt_name, mime="text/plain")

    for csv_name, csv_content in st.session_state.csv_files:
        st.download_button(label=f"Download {csv_name}", data=csv_content, file_name=csv_name, mime="text/csv")

    if st.session_state.consolidated_csv:
        st.download_button(
            label=f"Download Consolidated CSV for {legal_name}",
            data=st.session_state.consolidated_csv,
            file_name=f"{legal_name}_consolidated.csv",
            mime="text/csv"
        )

if __name__ == "__main__":
    main()



