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

def process_text_to_csv(text_content, legal_name, company_number, statement_date):
    """Process text content to generate a CSV for an individual statement."""
    # Your CSV processing logic here (unchanged from your current working copy)

    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    # Add processed rows to csv_buffer (Your logic goes here)
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

            # Extract text from PDF
            text_content = extract_text_from_pdf(pdf_content)

            # Generate statement date (dummy date for this example)
            statement_date = "2024-01-01"  # Replace this with your actual statement date extraction logic

            # Rename files using "Company Legal Name - Type of Document - Statement Date"
            pdf_name = f"{legal_name} - PDF - {statement_date}.pdf"
            csv_name = f"{legal_name} - CSV - {statement_date}.csv"

            # Store PDFs and process CSV
            st.session_state.pdf_files.append((pdf_name, pdf_content))
            csv_buffer, _ = process_text_to_csv(
                text_content, legal_name, company_number, statement_date
            )
            st.session_state.csv_files.append((csv_name, csv_buffer.getvalue()))
            csv_buffers.append(csv_buffer)

        # Consolidate CSVs into a single file
        consolidated_csv = StringIO()
        writer = csv.writer(consolidated_csv)
        for buffer in csv_buffers:
            buffer.seek(0)
            writer.writerows(csv.reader(buffer))
        consolidated_csv.seek(0)
        st.session_state.consolidated_csv = consolidated_csv.getvalue()

    # Add download buttons with unique file names and keys
    for idx, (pdf_name, pdf_content) in enumerate(st.session_state.pdf_files):
        st.download_button(
            label=f"Download {pdf_name}",
            data=pdf_content,
            file_name=pdf_name,
            mime="application/pdf",
            key=f"pdf_download_{idx}"  # Unique key
        )

    for idx, (csv_name, csv_content) in enumerate(st.session_state.csv_files):
        st.download_button(
            label=f"Download {csv_name}",
            data=csv_content,
            file_name=csv_name,
            mime="text/csv",
            key=f"csv_download_{idx}"  # Unique key
        )

    if st.session_state.consolidated_csv:
        consolidated_csv_name = f"{legal_name} - Consolidated CSV - {statement_date}.csv"
        st.download_button(
            label="Download Consolidated CSV",
            data=st.session_state.consolidated_csv,
            file_name=consolidated_csv_name,
            mime="text/csv",
            key="consolidated_csv_download"  # Unique key
        )


if __name__ == "__main__":
    main()

