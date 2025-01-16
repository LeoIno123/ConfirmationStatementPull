import streamlit as st
import requests
import base64
from io import BytesIO, StringIO
from PyPDF2 import PdfReader
import csv

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

def get_confirmation_statement_transaction_id(company_number, api_key):
    """Fetch the transaction ID for the confirmation statement."""
    url = f"{API_BASE_URL}/company/{company_number}/filing-history"
    headers = {"Authorization": f"Basic {base64.b64encode(f'{api_key}:'.encode()).decode()}"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        st.error("Failed to fetch filing history.")
        return None
    data = response.json()
    for item in data.get("items", []):
        if "confirmation statement" in item.get("description", "").lower() or item.get("type") == "CS01":
            return item.get("transaction_id")
    return None

def download_pdf(company_number, transaction_id):
    """Download the confirmation statement PDF."""
    url = f"{PDF_DOWNLOAD_URL}/company/{company_number}/filing-history/{transaction_id}/document?format=pdf&download=0"
    response = requests.get(url)
    if response.status_code == 200:
        return response.content
    else:
        st.error("Failed to download the confirmation statement PDF.")
        return None

def extract_text_from_pdf(pdf_content):
    """Extract text from a PDF file."""
    pdf_reader = PdfReader(BytesIO(pdf_content))
    text_content = "\n".join(page.extract_text() for page in pdf_reader.pages)
    return text_content

def save_text_as_file(text_content, legal_name):
    """Save extracted text as a .txt file."""
    txt_filename = f"{legal_name}_confirmation_statement.txt"
    return txt_filename, text_content

def process_text_to_csv(text_content):
    """Process text content to generate a CSV."""
    lines = text_content.split("\n")
    csv_data = [
        ["Company Legal Name", "Company Number", "Statement Date", "Shareholding #", "Amount of Shares", "Type of Shares", "Shareholder Name"]
    ]

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
            shareholding_details = parts[1].strip().split()
            amount_of_shares, raw_type_of_shares = shareholding_details[0], " ".join(shareholding_details[1:])

            # Extract only the portion before "shares"
            type_of_shares_match = re.search(r"(.*?)\s+shares", raw_type_of_shares.lower())
            type_of_shares = type_of_shares_match.group(1).title() if type_of_shares_match else "Unknown Type"

            shareholder_name = ""
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                if next_line.startswith("Name:"):
                    shareholder_name = next_line.split(":")[1].strip()
                    break
                j += 1

            csv_data.append([company_name, company_number, statement_date, shareholding_number, amount_of_shares, type_of_shares, shareholder_name or "PENDING"])

    # Use StringIO for text-based CSV creation
    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerows(csv_data)
    csv_buffer.seek(0)
    return csv_buffer



def main():
    st.title("Company Confirmation Statement Downloader")

    # Initialize session state
    if "pdf_content" not in st.session_state:
        st.session_state.pdf_content = None
    if "txt_content" not in st.session_state:
        st.session_state.txt_content = None
    if "csv_content" not in st.session_state:
        st.session_state.csv_content = None
    if "legal_name" not in st.session_state:
        st.session_state.legal_name = ""

    # Input for Company Name
    legal_name = st.text_input("Enter Company Legal Name:", st.session_state.legal_name)

    if st.button("Process"):
        if not legal_name.strip():
            st.error("Please enter a valid company name.")
            return

        # Store the entered legal name in session state
        st.session_state.legal_name = legal_name

        # Fetch the Company Number
        api_key = st.secrets["API"]["key"]
        st.info(f"Fetching company number for: {legal_name}")
        company_number = get_company_number(legal_name, api_key)
        if not company_number:
            return

        # Fetch the Transaction ID
        st.info("Fetching confirmation statement transaction ID...")
        transaction_id = get_confirmation_statement_transaction_id(company_number, api_key)
        if not transaction_id:
            return

        # Download PDF
        st.info("Downloading confirmation statement PDF...")
        pdf_content = download_pdf(company_number, transaction_id)
        if not pdf_content:
            return

        # Save the downloaded PDF content in session state
        st.session_state.pdf_content = pdf_content

        # Extract text and save as .txt
        st.info("Extracting text from PDF...")
        text_content = extract_text_from_pdf(pdf_content)
        st.session_state.txt_content = text_content

        # Process text to CSV
        st.info("Generating CSV from text...")
        csv_buffer = process_text_to_csv(text_content)
        st.session_state.csv_content = csv_buffer.getvalue()

        st.success("Processing complete! You can download the files below.")

    # Display download buttons if files are available
    if st.session_state.pdf_content:
        st.download_button(
            label=f"Download {st.session_state.legal_name} PDF File",
            data=st.session_state.pdf_content,
            file_name=f"{st.session_state.legal_name}_confirmation_statement.pdf",
            mime="application/pdf"
        )

    if st.session_state.txt_content:
        st.download_button(
            label=f"Download {st.session_state.legal_name} TXT File",
            data=st.session_state.txt_content,
            file_name=f"{st.session_state.legal_name}_confirmation_statement.txt",
            mime="text/plain"
        )

    if st.session_state.csv_content:
        st.download_button(
            label=f"Download {st.session_state.legal_name} CSV File",
            data=st.session_state.csv_content,
            file_name=f"{st.session_state.legal_name}_confirmation_statement.csv",
            mime="text/csv"
        )



if __name__ == "__main__":
    main()
