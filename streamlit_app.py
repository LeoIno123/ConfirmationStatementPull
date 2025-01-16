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

def process_text_to_csv(text_content, statement_number, legal_name, company_number):
    """Process text content to generate a CSV for a single statement."""
    csv_data = []
    statement_date = ""

    if not text_content.strip():
        return StringIO(), None  # Return an empty CSV if no text content

    # Combine lines intelligently
    lines = text_content.split("\n")
    combined_text = "\n".join(lines)

    # Look for the Statement Date pattern
    statement_date_match = re.search(r"Confirmation\s+Statement\s+date:\s*(\d{2}/\d{2}/\d{4})", combined_text, re.IGNORECASE)
    if statement_date_match:
        statement_date = statement_date_match.group(1)

    # Add company details to the top of the CSV
    csv_data.append(["Company Legal Name", legal_name])
    csv_data.append(["Company Number", company_number])
    csv_data.append(["Statement Date", statement_date])
    csv_data.append([])  # Blank row
    csv_data.append(["Shareholding #", "Amount of Shares", "Type of Shares", "Shareholder Name"])

    # Extract shareholding details
    for i, line in enumerate(lines):
        line = line.strip()

        if line.startswith("Shareholding"):
            parts = line.split(":")
            shareholding_number = parts[0].split()[-1]
            raw_details = parts[1].strip()

            # Extract the number of shares and type of shares separately
            amount_of_shares = re.search(r"\d+", raw_details).group() if re.search(r"\d+", raw_details) else "Unknown"
            type_of_shares_match = re.search(r"\d+\s+(.*)", raw_details)  # Match only the type after the number
            type_of_shares = type_of_shares_match.group(1).title() if type_of_shares_match else "Unknown"

            # Extract shareholder name
            shareholder_name = ""
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                if next_line.startswith("Name:"):
                    shareholder_name = next_line.split(":")[1].strip()
                    break
                j += 1

            csv_data.append([
                shareholding_number, amount_of_shares, type_of_shares, shareholder_name or "PENDING"
            ])

    # Create CSV buffer
    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerows(csv_data)
    csv_buffer.seek(0)
    return csv_buffer, statement_date

def consolidate_csvs(csv_buffers):
    """Consolidate multiple CSV buffers horizontally with proper header alignment."""
    consolidated_rows = []
    headers = []
    max_rows = 0

    # Collect headers and calculate maximum number of rows in shareholding data
    for buf in csv_buffers:
        buf.seek(0)
        rows = list(csv.reader(buf))
        if len(rows) >= 5:  # Ensure there are at least 5 rows for valid CSV content
            headers.append(rows[:5])  # First 5 rows are the headers
        else:
            headers.append([[""] * 4] * 5)  # Add empty headers if the CSV is invalid
        max_rows = max(max_rows, len(rows) - 5)  # Exclude header rows

    # Consolidate headers horizontally, aligned with shareholding data
    for i in range(5):  # Process the first 5 rows (headers)
        row = []
        for header in headers:
            if i < len(header):
                row.extend(header[i])  # Add the current header row
            else:
                row.extend([""] * len(header[0]))  # Add empty cells if header row is missing
            row.append("")  # Add column break
        consolidated_rows.append(row)

    # Add column headers for shareholding data (aligned under statement headers)
    consolidated_column_headers = []
    for header in headers:
        consolidated_column_headers.extend(header[4])  # Add "Shareholding #" headers
        consolidated_column_headers.append("")  # Add column break
    consolidated_rows.append(consolidated_column_headers)

    # Consolidate shareholding data horizontally
    for i in range(max_rows):
        row = []
        for buf in csv_buffers:
            buf.seek(0)
            rows = list(csv.reader(buf))
            if i + 5 < len(rows):  # Start at the 6th row (shareholding data)
                row.extend(rows[i + 5])  # Add shareholding data row
            else:
                row.extend([""] * len(rows[4]))  # Add empty cells for missing data
            row.append("")  # Add column break
        consolidated_rows.append(row)

    # Create a consolidated CSV buffer
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

    legal_name = st.text_input("Enter Company Legal Name:", "")

    if st.button("Process"):
        if not legal_name.strip():
            st.error("Please enter a valid company name.")
            return

        api_key = st.secrets["API"]["key"]
        company_number = get_company_number(legal_name, api_key)
        if not company_number:
            st.error("Company not found.")
            return

        transaction_ids = get_confirmation_statement_transaction_ids(company_number, api_key)
        if not transaction_ids:
            st.error("No confirmation statements found.")
            return

        st.session_state.pdf_files = []
        st.session_state.text_files = []
        st.session_state.csv_files = []
        csv_buffers = []

        for idx, transaction_id in enumerate(transaction_ids):
            pdf_content = download_pdf(company_number, transaction_id)
            if pdf_content:
                st.session_state.pdf_files.append((f"{legal_name}_statement_{idx + 1}.pdf", pdf_content))
                text_content = extract_text_from_pdf(pdf_content)
                st.session_state.text_files.append((f"{legal_name}_statement_{idx + 1}.txt", text_content))
                csv_buffer, _ = process_text_to_csv(text_content, legal_name, company_number)
                st.session_state.csv_files.append((f"{legal_name}_statement_{idx + 1}.csv", csv_buffer.getvalue()))
                csv_buffers.append(csv_buffer)

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
            label="Download Consolidated CSV",
            data=st.session_state.consolidated_csv,
            file_name=f"{legal_name}_consolidated.csv",
            mime="text/csv"
        )

if __name__ == "__main__":
    main()
