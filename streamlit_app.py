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
    """Fetch the transaction IDs for the last three confirmation statements."""
    url = f"{API_BASE_URL}/company/{company_number}/filing-history"
    headers = {"Authorization": f"Basic {base64.b64encode(f'{api_key}:'.encode()).decode()}"}
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        st.error("Failed to fetch filing history.")
        return []
    
    data = response.json()
    items = data.get("items", [])
    st.write("Filing history items:", items)  # Debugging: Display all items

    transaction_ids = [
        item.get("transaction_id")
        for item in items
        if item.get("description") and "confirmation statement" in item["description"].lower()
    ]
    st.write("Transaction IDs found:", transaction_ids)  # Debugging
    return transaction_ids[:3]  # Limit to 3 IDs

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

def process_text_to_csv(text_contents, legal_name):
    """Process text content from multiple PDFs to generate a consolidated CSV."""
    csv_data = [
        [
            "Company Legal Name", "Company Number", "Statement Date",
            "Shareholding #", "Amount of Shares", "Type of Shares", "Shareholder Name"
        ]
    ]

    for text_content in text_contents:
        if not text_content.strip():
            continue

        lines = text_content.split("\n")
        company_name, company_number, statement_date = "", "", ""

        for i, line in enumerate(lines):
            line = line.strip()

            if line.startswith("Company Name:"):
                company_name = line.split(":")[1].strip()

            if line.startswith("Company Number:"):
                company_number = line.split(":")[1].strip()
                next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
                if next_line.startswith("Confirmation"):
                    date_match = next_line.split()[-1]
                    statement_date = date_match if "/" in date_match else ""

            if line.startswith("Shareholding"):
                parts = line.split(":")
                shareholding_number = parts[0].split()[-1]
                raw_details = parts[1].strip()
                amount_of_shares = re.search(r"\d+", raw_details).group()
                type_of_shares_match = re.search(r"(.*?)\s+shares", raw_details.lower())
                type_of_shares = type_of_shares_match.group(1).title() if type_of_shares_match else "Unknown"

                shareholder_name = ""
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].strip()
                    if next_line.startswith("Name:"):
                        shareholder_name = next_line.split(":")[1].strip()
                        break
                    j += 1

                csv_data.append([
                    company_name, company_number, statement_date,
                    shareholding_number, amount_of_shares, type_of_shares, shareholder_name or "PENDING"
                ])

    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerows(csv_data)
    csv_buffer.seek(0)
    return csv_buffer

def main():
    st.title("Company Confirmation Statement Downloader")

    # Initialize session state variables
    if "transaction_ids" not in st.session_state:
        st.session_state.transaction_ids = []
    if "pdf_files" not in st.session_state:
        st.session_state.pdf_files = []
    if "text_files" not in st.session_state:
        st.session_state.text_files = []
    if "csv_file" not in st.session_state:
        st.session_state.csv_file = None

    legal_name = st.text_input("Enter Company Legal Name:", "")

    if st.button("Process"):
        if not legal_name.strip():
            st.error("Please enter a valid company name.")
            return

        api_key = st.secrets["API"]["key"]
        st.info(f"Fetching company number for: {legal_name}")
        company_number = get_company_number(legal_name, api_key)
        if not company_number:
            st.error("Company not found.")
            return

        st.info("Fetching confirmation statement transaction IDs...")
        transaction_ids = get_confirmation_statement_transaction_ids(company_number, api_key)
        st.session_state.transaction_ids = transaction_ids

        if not transaction_ids:
            st.error("No confirmation statements found.")
            return

        pdf_files = []
        text_files = []
        text_contents = []

        st.info("Downloading confirmation statement PDFs...")
        for idx, transaction_id in enumerate(transaction_ids):
            pdf_content = download_pdf(company_number, transaction_id)
            if pdf_content:
                pdf_files.append((f"{legal_name}_statement_{idx + 1}.pdf", pdf_content))
                text_content = extract_text_from_pdf(pdf_content)
                text_files.append((f"{legal_name}_statement_{idx + 1}.txt", text_content))
                text_contents.append(text_content)

        st.session_state.pdf_files = pdf_files
        st.session_state.text_files = text_files

        st.info("Generating consolidated CSV...")
        csv_buffer = process_text_to_csv(text_contents, legal_name)
        st.session_state.csv_file = csv_buffer.getvalue()

    # Display transaction IDs for debugging
    st.write("Transaction IDs:", st.session_state.transaction_ids)

    # Display buttons for downloads
    for pdf_name, pdf_content in st.session_state.pdf_files:
        st.download_button(
            label=f"Download {pdf_name}",
            data=pdf_content,
            file_name=pdf_name,
            mime="application/pdf"
        )

    for txt_name, txt_content in st.session_state.text_files:
        st.download_button(
            label=f"Download {txt_name}",
            data=txt_content,
            file_name=txt_name,
            mime="text/plain"
        )

    if st.session_state.csv_file:
        st.download_button(
            label=f"Download Consolidated CSV for {legal_name}",
            data=st.session_state.csv_file,
            file_name=f"{legal_name}_confirmation_statements.csv",
            mime="text/csv"
        )

if __name__ == "__main__":
    main()
