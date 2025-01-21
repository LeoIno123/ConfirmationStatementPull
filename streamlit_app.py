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

from collections import defaultdict

def process_text_to_csv(text_content, legal_name, company_number, statement_number):
    """Process text content to generate a CSV for an individual statement."""
    lines = text_content.split("\n")

    # Initialize CSV data with statement information
    csv_data = [
        ["Company Legal Name", legal_name],
        ["Company Number", company_number],
        ["Statement Date", ""],  # Placeholder for the statement date
        [],  # Empty row separator
    ]

    statement_date = ""
    shareholder_data = []  # To collect rows of shareholder information
    share_totals = defaultdict(int)  # To aggregate total shares by type

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Extract confirmation statement date
        if line.startswith("Statement date:"):
            statement_date = line.split(":")[1].strip()
            csv_data[2][1] = statement_date  # Update the statement date

        # Detect shareholding line
        if line.startswith("Shareholding"):
            # Initialize buffer to collect multi-line details
            buffer = line

            # Look ahead to collect additional lines
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()

                # Stop collecting if we hit a new block (e.g., Name: or Shareholding)
                if next_line.startswith("Name:") or next_line.startswith("Shareholding"):
                    break

                # Append current line to buffer
                buffer += " " + next_line
                j += 1

            # Extract shareholding number
            shareholding_number_match = re.search(r"Shareholding\s+(\d+):", buffer)
            shareholding_number = shareholding_number_match.group(1) if shareholding_number_match else "Unknown"

            # Extract the total shares and type of shares
            total_shares_match = re.search(r"(\d+)\s+([A-Za-z\s]+)\s+shares\s+held", buffer, re.IGNORECASE)
            if total_shares_match:
                amount_of_shares = int(total_shares_match.group(1))
                type_of_shares = total_shares_match.group(2).strip().title()
                # Add to share totals
                share_totals[type_of_shares] += amount_of_shares
            else:
                amount_of_shares = "Unknown"
                type_of_shares = "Unknown"

            # Extract shareholder name
            shareholder_name = ""
            if j < len(lines) and lines[j].strip().startswith("Name:"):
                shareholder_name = lines[j].strip().split(":")[1].strip()

            # Append extracted data
            shareholder_data.append([
                shareholding_number, amount_of_shares, type_of_shares, shareholder_name or "PENDING"
            ])

            # Move to the next unprocessed line
            i = j
        else:
            i += 1

    # Add calculated totals for each share type to the CSV
    csv_data.append(["Type of Shares", "Total Number of Shares"])
    for share_type, total in share_totals.items():
        csv_data.append([share_type, total])

    # Add a blank row to separate shareholding data
    csv_data.append([])

    # Append shareholder headers and data
    shareholder_headers = ["Shareholding #", "Amount of Shares", "Type of Shares", "Shareholder Name"]
    csv_data.append(shareholder_headers)
    csv_data.extend(shareholder_data)

    # Create CSV buffer
    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerows(csv_data)
    csv_buffer.seek(0)
    return csv_buffer, statement_date


def main():
    st.title("Company Confirmation Statement Downloader")

    # Initialize session state
    if "pdf_files" not in st.session_state:
        st.session_state.pdf_files = []
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
        st.session_state.csv_files = []
        csv_buffers = []

        for idx, transaction_id in enumerate(transaction_ids):
            # Download PDF and extract text
            pdf_content = download_pdf(company_number, transaction_id)
            if not pdf_content:
                continue

            # Extract statement_date and process the text
            text_content = extract_text_from_pdf(pdf_content)
            csv_buffer, statement_date = process_text_to_csv(
                text_content, legal_name, company_number, idx + 1
            )

            # Generate file names with dynamic `statement_date`
            pdf_name = f"{legal_name}_statement_{idx + 1}_{statement_date}.pdf"
            csv_name = f"{legal_name}_statement_{idx + 1}_{statement_date}.csv"

            # Store PDFs and CSVs in session state
            st.session_state.pdf_files.append((pdf_name, pdf_content))
            st.session_state.csv_files.append((csv_name, csv_buffer.getvalue()))
            csv_buffers.append(csv_buffer)

    # Add download buttons for PDF and CSV files
    for idx, (pdf_name, pdf_content) in enumerate(st.session_state.pdf_files):
        st.download_button(
            label=f"Download {pdf_name}",
            data=pdf_content,
            file_name=pdf_name,
            mime="application/pdf",
            key=f"pdf_download_{idx}"
        )

    for idx, (csv_name, csv_content) in enumerate(st.session_state.csv_files):
        st.download_button(
            label=f"Download {csv_name}",
            data=csv_content,
            file_name=csv_name,
            mime="text/csv",
            key=f"csv_download_{idx}"
        )

if __name__ == "__main__":
    main()
