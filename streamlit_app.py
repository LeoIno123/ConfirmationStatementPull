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
    st.write("Filing history items:", items)  # Debugging: Display all items

    transaction_ids = [
        item.get("transaction_id")
        for item in items
        if item.get("type") and item["type"].lower() == "cs01"
    ]
    st.write("Transaction IDs found:", transaction_ids)  # Debugging
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

def process_text_to_csv(text_content, statement_number):
    """Process text content to generate a CSV for a single statement."""
    csv_data = [
        [
            f"Statement {statement_number} - Company Legal Name", 
            f"Statement {statement_number} - Company Number", 
            f"Statement {statement_number} - Statement Date",
            f"Statement {statement_number} - Shareholding #", 
            f"Statement {statement_number} - Amount of Shares", 
            f"Statement {statement_number} - Type of Shares", 
            f"Statement {statement_number} - Shareholder Name"
        ]
    ]

    if not text_content.strip():
        return StringIO()  # Return an empty CSV if no text content

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
            amount_of_shares = re.search(r"\d+", raw_details).group() if re.search(r"\d+", raw_details) else "Unknown"
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
        if not transaction_ids:
            st.error("No confirmation statements found.")
            return

        pdf_files = []
        text_files = []
        csv_files = []
        consolidated_data = []

        st.info("Downloading confirmation statement PDFs...")
        for idx, transaction_id in enumerate(transaction_ids):
            pdf_content = download_pdf(company_number, transaction_id)
            pdf_name = f"{legal_name}_statement_{idx + 1}.pdf"
            txt_name = f"{legal_name}_statement_{idx + 1}.txt"
            csv_name = f"{legal_name}_statement_{idx + 1}.csv"

            if pdf_content:
                pdf_files.append((pdf_name, pdf_content))
                text_content = extract_text_from_pdf(pdf_content)
                text_files.append((txt_name, text_content))
                csv_buffer = process_text_to_csv(text_content, idx + 1)
                csv_files.append((csv_name, csv_buffer.getvalue()))
                consolidated_data.append(csv_buffer.getvalue())

        # Combine CSVs
        consolidated_csv = "\n".join(consolidated_data)

        # Display buttons
        for pdf_name, pdf_content in pdf_files:
            st.download_button(
                label=f"Download {pdf_name}",
                data=pdf_content,
                file_name=pdf_name,
                mime="application/pdf"
            )

        for txt_name, txt_content in text_files:
            st.download_button(
                label=f"Download {txt_name}",
                data=txt_content,
                file_name=txt_name,
                mime="text/plain"
            )

        for csv_name, csv_content in csv_files:
            st.download_button(
                label=f"Download {csv_name}",
                data=csv_content,
                file_name=csv_name,
                mime="text/csv"
            )

        st.download_button(
            label=f"Download Consolidated CSV for {legal_name}",
            data=consolidated_csv,
            file_name=f"{legal_name}_consolidated.csv",
            mime="text/csv"
        )

if __name__ == "__main__":
    main()
