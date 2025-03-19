import os
import json
import time
import logging
import sys
import re
from dotenv import load_dotenv
from openai import OpenAI
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from datetime import datetime
import csv
import pandas as pd
# Setup Logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("invoice_parser.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# Load Environment Variables
load_dotenv()

FORM_RECOGNIZER_ENDPOINT = os.getenv("AZURE_FORM_RECOGNIZER_ENDPOINT")
FORM_RECOGNIZER_KEY = os.getenv("AZURE_FORM_RECOGNIZER_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Azure Form Recognizer Setup
document_analysis_client = DocumentAnalysisClient(
    endpoint=FORM_RECOGNIZER_ENDPOINT,
    credential=AzureKeyCredential(FORM_RECOGNIZER_KEY)
)

# OpenAI Setup
client = OpenAI(api_key=OPENAI_API_KEY)

def remove_non_printable(text):
    """Remove non-printable characters from text"""
    return ''.join(char for char in text if char.isprintable() or char.isspace())

def Removingunwanted_from_Json(Jsonfile):
    """Extract JSON objects from text with improved error handling"""
    text =Jsonfile.strip()
    
    # Remove code block markers if present
    if text.startswith("") and text.endswith(""):
        text = text[3:-3].strip()
    if text.lower().startswith("json"):
        text = text[4:].strip()
    
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        json_objects = []
        start = 0
        while True:
            try:
                start = text.index('{', start)
                brace_count = 1
                pos = start + 1
                
                while brace_count > 0 and pos < len(text):
                    if text[pos] == '{':
                        brace_count += 1
                    elif text[pos] == '}':
                        brace_count -= 1
                    pos += 1
                
                if brace_count == 0:
                    json_str = text[start:pos]
                    try:
                        json_obj = json.loads(json_str)
                        json_objects.append(json_obj)
                    except json.JSONDecodeError:
                        logging.warning(f"Failed to parse JSON object: {json_str[:100]}...")
                    
                    start = pos
                else:
                    break
                    
            except ValueError:
                break
        
        return json_objects if json_objects else None

def send_to_gpt(page_data):
    """
    Enhanced GPT processing with improved prompt and error handling
    """
    json_template = {
        "Supplier Name": "",
        "Sold to Address": "",
        "Order Date": "",
        "Ship Date": "",
        "Invoice Number": "",
        "Shipping Address": "",
        "Total": 0,
        "List of Items": [
            {
                "Item Number": "",
                "Item Name": "",
                "Product Category": "",
                "Quantity Shipped": 1.0,
                "Extended Price": 1.0,
                "Quantity In a Case": 1.0,
                "Measurement Of Each Item": 1.0,
                "Measured In": "",
                "Total Units Ordered": 1.0,
                "Case Price": 0,
                "Catch Weight": "",
                "Priced By": "",
                "Splitable": "",
                "Split Price": "N/A",
                "Cost of a Unit": 1.0,
                "Currency": "",
                "Cost of Each Item":1.0
            }
        ]
    }
    system_message = """You are an expert invoice analysis AI specialized in wholesale produce invoices. Your task is to:
1. Extract structured information with 100% accuracy
2. Maintain data integrity across all fields
3. Apply standardized validation rules
4. Handle missing data according to specific rules
5. Ensure all calculations are precise and verified
6.Extract the all the items even it has duplicates and"""

    prompt = f"""
DETAILED INVOICE ANALYSIS INSTRUCTIONS:

1. HEADER INFORMATION
   Extract these specific fields:

   A. Basic Invoice Information
      • Supplier Name
        Headers to check:
        - "Vendor:", "Supplier:", "From:", "Sold By:"
        Rules:
        - Use FIRST supplier name found
        - Use EXACTLY same name throughout
        - Don't modify or formalize
      
      • Sold to Address
        Headers to check:
        - "Sold To:", "Bill To:", "Customer:"
        Format:
        - Complete address with all components
        - Include street, city, state, ZIP
      
      • Order Date
        Headers to check:
        - "Order Date:", "Date Ordered:", "PO Date:"
        Format: YYYY-MM-DD
      
      • Ship Date
        Headers to check:
        - "Ship Date:", "Delivery Date:", "Shipped:"
        Format: YYYY-MM-DD
      
      • Invoice Number
        Headers to check:
        - Search for "Invoice Numbers" in the text like "Invoice NO","Invoice No","Invoice Number","Invoice ID"
        - "Invoice #:", "Invoice Number:", "Invoice ID:"
        Rules:
        - Include all digits/characters
        - Keep leading zeros
      
      • Shipping Address
        Headers to check:
        - "Ship To:", "Deliver To:", "Destination:"
        Format:
        - Complete delivery address
        - All address components included
      
      • Total
        Headers to check:
        - "Total:", "Amount Due:", "Balance Due:"
        Rules:
        - Must match sum of line items
        - Include tax if listed
        - Round to 2 decimals

2. LINE ITEM DETAIL
    Extract the all the items even it has duplicates and
   Extract these fields for each item:

   A. Basic Item Information
      • Item Number
        Headers to check:
        -"Product Code:" -"Item Number:" -"SKU:" -"UPC:"
        Rules:
        - Keep full identifier
        - Include leading zeros
      
      • Item Name
        Headers to check:
        - "Description:", "Product:", "Item:"
        Rules:
        - Include full description with measeurement as well
        - Keep original format
      
      • Product Category
        Classify as:
        - PRODUCE: Fresh fruits/vegetables
        - DAIRY: Milk, cheese, yogurt
        - MEAT: Beef, pork, poultry
        - SEAFOOD: Fish, shellfish
        - Beverages: Sodas,juices,water
        - Dry Grocery: Chips, candy, nuts,Canned goods, spices, sauces
        - BAKERY: Bread, pastries, cakes
        - FROZEN: Ice cream, meals, desserts
        - paper goods and Disposables: Bags, napkins, plates, cups, utensils,packing materials
        - liquor: Beer, wine, spirits
        - Chemical: Soaps, detergents, supplies
        - OTHER: Anything not in above categories

B. Quantity and Measurement Details

A.Quantity In a Case
   Definition: Number of individual units contained within ONE case.

   Primary Source:
   - "Pack Size" field
   - Look for patterns like "6 64 OZ", "4 5 LB", "10 4 PK"

   Extraction Rules:
   1. Identify the first number in the "Pack Size" field; this is the "Quantity in Case".
   2. The second number is the "Measurement of Each Item".
   3. The unit following the second number is the "Measured In".

   Examples:
   - "6 64 OZ" → Quantity in Case: 6, Measurement: 64, Measured In: OZ
   - "4 5 LB" → Quantity in Case: 4, Measurement: 5, Measured In: LB
   - "10 4 PK" → Quantity in Case: 10, Measurement: 4, Measured In: PK

   Default:
   - If the "Pack Size" does not contain two numbers, use best judgment or default to Quantity in Case: 1.


B.Quantity Shipped
   Definition: Number of complete cases ordered and delivered.

   Extraction Rules:
   1. If "Quantity Shipped" is explicitly provided in the invoice (e.g., under "Quantity", "Qty", "Shipped"), use that number.
   2. If not provided, default "Quantity Shipped" to 1.

   Notes:
   - Do not confuse "Quantity in a Case" with "Quantity Shipped".
   - "Quantity Shipped" represents how many cases were ordered.

        - "Cases Ordered"

C. C. MEASUREMENT OF EACH ITEM
   Definition: Size, weight, or volume of ONE unit.

   Extraction Rules:
   - From the "Pack Size" field, the second number is the "Measurement of Each Item".
   - The unit immediately following this number is the "Measured In".
   - If not,default to 1.

   Examples:
   - "6 64 OZ" → Measurement: 64, Measured In: OZ
   - "4 5 LB" → Measurement: 5, Measured In: LB
   - "10 4 PK" → Measurement: 4, Measured In: PK

   Notes:
   - Ensure the unit is correctly identified and standardized as per the "Measurement Units" section.
  

   B. Measurement Units:
      • Measured In - Standard Units:COnvert all the units to standard units
        
        WEIGHT:
        - pounds: LB, LBS, #, POUND
        - ounces: OZ, OUNCE
        - kilos: KG, KILO
        - grams: G, GM, GRAM

        COUNT:
        - each: EA, PC, CT, COUNT, PIECE
        - case: CS, CASE, BX, BOX
        - dozen: DOZ, DZ
        - pack: PK, PACK, PKG
        - bundle: BDL, BUNDLE

        VOLUME:
        - gallons: GAL, GALLON
        - quarts: QT, QUART
        - pints: PT, PINT
        - fluid_ounces: FL OZ, FLOZ
        - liters: L, LT, LTR
        - milliliters: ML

        CONTAINERS:
        - cans: CN, CAN, #10 CAN
        - jars: JR, JAR
        - bottles: BTL, BOTTLE
        - containers: CTN, CONT
        - tubs: TB, TUB
        - bags: BG, BAG

        PRODUCE:
        - bunch: BN, BCH, BUNCH
        - head: HD, HEAD
        - basket: BSK, BASKET
        - crate: CRT, CRATE
        - carton: CRTN, CARTON
      
      • Total Units Ordered
        Calculate: Measurement of Each Item * Quantity In a Case * Quantity Shipped
        Example: 5lb * 10 per case * 2 cases = 100 pounds
        Examples:

- *Example 1:*
  - Pack Size: "6 64 OZ"
  - Quantity in Case: 6 (first number)
  - Measurement of Each Item: 64 (second number)
  - Measured In: OZ
  - Quantity Shipped: 1 (default)
  - Total Units Ordered: Quantity in Case * Measurement of Each Item * Quantity Shipped = 6 × 64 × 1 = 384

- *Example 2:*
  - Pack Size: "4 5 LB"
  - Quantity in Case: 4
  - Measurement of Each Item: 5
  - Measured In: LB
  - Quantity Shipped: 1 (default)
  - Total Units Ordered: 4 * 5 * 1 = 20 LB

- *Example 3:*
  - Pack Size: "10 4 PK"
  - Quantity in Case: 10
  - Measurement of Each Item: 4
  - Measured In: PK
  - Quantity Shipped: 1 (default)
  - Total Units Ordered: 10 * 4 * 1 = 40 PK


   C. Pricing Information
      • Extended Price
        Headers to check:
        - "Ext Price:", "Total:", "Amount:"
        Rules:
        - Must equal Case Price * Quantity Shipped
      
      • Case Price
        Headers to check:
        - "Unit Price:", 
        Rules:
        - Price for single Unit price 
      
      • Cost of a Unit
        Calculate: Extended Price ÷ Total Units Ordered
        Example: $100 ÷ 100 pounds = $1.00/lb
      
      • Currency
        Default: "USD" if not specified

      • Cost of Each Item
        Cost of Each Item is calculated by Cost of Each Item=Cost of a unit* Measurement of each item
        Verfiy by (Extended Price*Mesurement of each item)/Total Units Ordered
        Default: if not specified "N/A"
       

   D. Additional Attributes
      • Catch Weight:
        If the item number is same in the previous item and quantity shipped is different then set "YES" 
         else N/A

      
      • Priced By
        Values:
        - "per Case"
        - "per pound"
        - "per case"
        - "per each"
        - "per dozen"
        - "per Ounce"
      
      • Splitable
        -Set "YES" if:
        -if you have "YES" reference to Splitable

        Set "NO" if:
        - if you have "NO" reference to Splitable

        Set "NO" if:
        - Bulk only
        - Single unit
      
      • Split Price
        If Splitable = "YES":
        - Calculate: Case Price ÷ Quantity In Case
        If Splitable = "NO":
        - Use "N/A"

3. VALIDATION RULES
   • Numeric Checks:
     - All quantities must be positive
     - All prices must be positive
     - Total must match sum of line items
   
   • Required Fields:
     - Supplier Name
     - Invoice Number
     - Total Amount
     - Item Name
     - Extended Price
   
   • Default Values:
     - Quantity: 1.0
     - Currency: "USD"
     - Split Price: "N/A"
     - Category: "OTHER"

OUTPUT FORMAT:
Return a JSON array containing each invoice as an object matching this template:
{json.dumps(json_template, indent=2)}INVOICE TEXT TO PROCESS:
{page_data}
"""


    try:
        # Attempt to process with GPT-4
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            max_tokens=16000,
            temperature=1
        )
        
        content = response.choices[0].message.content
        content = remove_non_printable(content)
        try:
                # Remove markdown code blocks if present
                if "json" in content:
                    content = content.split("json")[1].split("")[0].strip()
                elif "" in content:
                    content = content.split("")[1].split("")[0].strip()
                
                parsed_data = json.loads(content)
                return parsed_data
        except json.JSONDecodeError as e2:
                logging.warning(f"Second JSON parse attempt failed: {str(e2)}")
                
                # Third attempt: Try to extract structured data
                try:
                    # Extract everything between first { and last }
                    content = content[content.find('{'):content.rfind('}')+1]
                    parsed_data = json.loads(content)
                    return parsed_data
                except json.JSONDecodeError as e3:
                    logging.error(f"All JSON parsing attempts failed. Final error: {str(e3)}")
                    return None
                
    except Exception as e:
        logging.error(f"Error processing with GPT: {str(e)}")
        return None
        

def extract_text_and_tables_from_invoice(file_path):
    """Extract text and tables with improved table structure"""
    try:
        with open(file_path, "rb") as f:
            poller = document_analysis_client.begin_analyze_document(
                "prebuilt-layout", 
                f
            )
            result = poller.result()

        pages_content = {}
        
        # Process tables first to get their locations
        table_regions = {}
        for table in result.tables:
            page_num = table.bounding_regions[0].page_number
            if page_num not in table_regions:
                table_regions[page_num] = []
            table_regions[page_num].append(table.bounding_regions[0])
            
            if page_num not in pages_content:
                pages_content[page_num] = {'text': [], 'tables': []}
            
            # Process cells with better handling
            rows = {}
            for cell in table.cells:
                if cell.row_index not in rows:
                    rows[cell.row_index] = {}
                
                # Handle cell content and spans
                content = cell.content.strip()
                rows[cell.row_index][cell.column_index] = content
            
            # Convert to formatted string
            table_content = []
            for row_idx in sorted(rows.keys()):
                row = rows[row_idx]
                # Ensure all columns are present
                row_content = []
                for col_idx in range(table.column_count):
                    row_content.append(row.get(col_idx, ''))
                table_content.append('\t'.join(row_content))
            
            if table_content:
                pages_content[page_num]['tables'].append('\n'.join(table_content))

        # Then process text, excluding table regions
        for page in result.pages:
            page_num = page.page_number
            if page_num not in pages_content:
                pages_content[page_num] = {'text': [], 'tables': []}
            
            # Sort text by position
            lines_with_pos = []
            for line in page.lines:
                y_pos = min(p.y for p in line.polygon)
                x_pos = min(p.x for p in line.polygon)
                lines_with_pos.append((y_pos, x_pos, line.content))
            
            lines_with_pos.sort()
            pages_content[page_num]['text'] = [line[2] for line in lines_with_pos]

        logging.info(f"Extracted content from {len(pages_content)} pages"+str(pages_content))
        return pages_content

    except Exception as e:
        logging.error(f"Error in document analysis: {str(e)}")
        raise

def format_page_content(page_data, page_num):
    """Format page content with improved structure"""
    content = []
    
    # Add page marker
    content.append(f"\n----- Page {page_num} Start -----\n")
    
    # Add text content with line numbers for better tracking
    content.append("TEXT CONTENT:")
    for line_num, line in enumerate(page_data['text'], 1):
        content.append(f"{line_num}:{line}")
    
    # Add tables with clear structure
    for table_idx, table in enumerate(page_data['tables']):
        content.append(f"\n----- Table {table_idx + 1} Start -----\n")
        
        # Split table into rows for better processing
        rows = table.split('\n')
        if rows:
            # Process header
            content.append(f"Header: {rows[0]}")
            
            # Process data rows with row numbers
            for row_idx, row in enumerate(rows[1:], 1):
                content.append(f"Row {row_idx}: {row}")
        
        content.append(f"----- Table {table_idx + 1} End -----\n")
    
    content.append(f"----- Page {page_num} End -----\n")
    
    return '\n'.join(content)

def handle_large_page(page_text, current_invoice, all_invoices):
    """Handle pages that are too large for single processing"""
    # Split at table boundaries
    parts = re.split(r'(----- Table \d+ Start -----)', page_text)
    current_part = []
    
    for part in parts:
        if part.startswith('----- Table'):
            # Process accumulated content
            if current_part:
                result = send_to_gpt('\n'.join(current_part))
                if result:
                    current_invoice = process_page_result(result, current_invoice, all_invoices)
                current_part = []
        
        current_part.append(part)
    
    # Process last part
    if current_part:
        result = send_to_gpt('\n'.join(current_part))
        if result:
            current_invoice = process_page_result(result, current_invoice, all_invoices)
    
    return current_invoice

def process_page_result(page_result, current_invoice, all_invoices):
    """Process a single page result"""
    if isinstance(page_result, list):
        for invoice in page_result:
            current_invoice = merge_or_add_invoice(invoice, current_invoice, all_invoices)
    else:
        current_invoice = merge_or_add_invoice(page_result, current_invoice, all_invoices)
    
    return current_invoice

def merge_or_add_invoice(new_invoice, current_invoice, all_invoices):
    """Merge or add new invoice data - keeping all items including duplicates"""
    if not new_invoice:
        return current_invoice
        
    if current_invoice and new_invoice.get('Invoice Number') == current_invoice.get('Invoice Number'):
        # Simply append all items from new invoice
        current_invoice['List of Items'].extend(new_invoice.get('List of Items', []))
        
        # Update total if needed
        if new_invoice.get('Total', 0):
            current_invoice['Total'] = new_invoice.get('Total')
    else:
        if current_invoice:
            # Add current invoice to list before starting new one
            all_invoices.append(current_invoice)
        current_invoice = new_invoice
    
    return current_invoice
    
        
def save_to_csv(parsed_invoices, output_file):
    """
    Save parsed invoices to CSV
    """
    headers = [
        "Supplier Name", "Sold to Address", "Order Date", "Ship Date", "Invoice Number",
        "Shipping Address", "Total", "Item Number", "Item Name", "Quantity In a Case",
        "Measurement Of Each Item", "Measured In", "Quantity Shipped", "Extended Price",
        "Total Units Ordered", "Case Price", "Catch Weight", "Priced By",
        "Splitable", "Split Price", "Cost of a Unit", "Cost of Each Item","Currency", "Product Category"
    ]

    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        writer.writeheader()

        for invoice in parsed_invoices:
            for item in invoice.get('List of Items', []):
                row = {
                    "Supplier Name": invoice.get('Supplier Name', 'N/A'),
                    "Sold to Address": invoice.get('Sold to Address', 'N/A'),
                    "Order Date": invoice.get('Order Date', 'N/A'),
                    "Ship Date": invoice.get('Ship Date', 'N/A'),
                    "Invoice Number": invoice.get('Invoice Number', 'N/A'),
                    "Shipping Address": invoice.get('Shipping Address', 'N/A'),
                    "Total": invoice.get('Total', 'N/A'),
                }
                row.update({key: item.get(key, 'N/A') for key in headers if key not in row})
                writer.writerow(row)

def process_excel_file(file_path):
    """
    Process Excel/CSV files by splitting into pages while preserving header context
    """
    try:
        # Read the file
        if file_path.lower().endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)
        
        # Calculate number of rows per page
        ROWS_PER_PAGE = 10
        total_rows = len(df)
        num_pages = (total_rows + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE
        
        # Get all headers
        headers = df.columns.tolist()
        
        # Initialize pages_content dictionary
        pages_content = {}
        
        # Process each page
        for page_num in range(num_pages):
            start_idx = page_num * ROWS_PER_PAGE
            end_idx = min((page_num + 1) * ROWS_PER_PAGE, total_rows)
            
            # Get page data
            page_df = df.iloc[start_idx:end_idx]
            
            # Convert to table format with headers
            table_rows = ['\t'.join(str(x) for x in headers)]
            
            for _, row in page_df.iterrows():
                row_data = [str(x) if pd.notna(x) else '' for x in row]
                table_rows.append('\t'.join(row_data))
            
            # Create page content with header context
            pages_content[page_num + 1] = {
                'text': [
                    f"Page {page_num + 1} of file: {os.path.basename(file_path)}",
                    "Header Information:",
                    *[f"{header}: Column {idx + 1}" for idx, header in enumerate(headers)],
                    "",
                    "Data Format:",
                    f"Total Columns: {len(headers)}",
                    f"Rows in this chunk: {len(page_df)}",
                    f"Row range: {start_idx + 1} to {end_idx}"
                ],
                'tables': ['\n'.join(table_rows)],
                'metadata': {
                    'headers': headers,
                    'chunk_info': {
                        'start_row': start_idx + 1,
                        'end_row': end_idx,
                        'total_rows': total_rows,
                        'page_number': page_num + 1,
                        'total_pages': num_pages
                    }
                }
            }
            
            logging.info(f"Processed page {page_num + 1} of {num_pages} with {len(headers)} columns")
        
        return pages_content
        
    except Exception as e:
        logging.error(f"Error processing file: {str(e)}")
        raise

def process_invoice_with_gpt(file_path):
    try:
        # Check file extension
        file_extension = os.path.splitext(file_path)[1].lower()
        
        # Process based on file type
        if file_extension in ['.xlsx', '.xls', '.csv']:
            logging.info(f"Processing spreadsheet file: {file_path}")
            pages_content = process_excel_file(file_path)
        else:
            logging.info(f"Processing document file: {file_path}")
            pages_content = extract_text_and_tables_from_invoice(file_path)
            
        if not pages_content:
            logging.error("No content extracted from file")
            return []
            
        all_invoices = []
        current_invoice = None
        
        # Process each page
        for page_num in sorted(pages_content.keys()):
            logging.info(f"Processing page {page_num} with {len(pages_content[page_num]['tables'])} tables")
            try:
                page_data = pages_content[page_num]
                page_text = format_page_content(page_data, page_num)
                
                if len(page_text) > 16000:
                    current_invoice = handle_large_page(page_text, current_invoice, all_invoices)
                else:
                    page_result = send_to_gpt(page_text)
                    if page_result:
                        current_invoice = process_page_result(page_result, current_invoice, all_invoices)
                
                time.sleep(1)
                
            except Exception as e:
                logging.error(f"Error processing page {page_num}: {str(e)}")
                continue
        
        if current_invoice:
            all_invoices.append(current_invoice)
        
        return all_invoices
        
    except Exception as e:
        logging.error(f"Error in invoice processing: {str(e)}")
        return []

def main(invoice_file_path):
    try:
        logging.info(f"Starting processing of {invoice_file_path}")
        
        # Validate file exists
        if not os.path.exists(invoice_file_path):
            raise FileNotFoundError(f"File not found: {invoice_file_path}")
            
        # Validate file extension
        file_extension = os.path.splitext(invoice_file_path)[1].lower()
        supported_extensions = ['.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.xlsx', '.xls', '.csv']
        
        if file_extension not in supported_extensions:
            raise ValueError(f"Unsupported file type. Supported types are: {', '.join(supported_extensions)}")
        
        parsed_invoices = process_invoice_with_gpt(invoice_file_path)
        
        if not parsed_invoices:
            logging.warning("No invoices were successfully parsed")
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        invoice_name = os.path.basename(invoice_file_path)
        csv_filename = f"{invoice_name}_{timestamp}.csv"
        save_to_csv(parsed_invoices, csv_filename)
        
        logging.info(f"Successfully processed {len(parsed_invoices)} invoices")
        logging.info(f"Results saved to: {csv_filename}")
        
        return parsed_invoices
        
    except Exception as e:
        logging.error(f"Error in main execution: {str(e)}")
        raise

if __name__ == "_main_":
    # Setup Logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("invoice_parser.log", encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    try:
        ##"C:\Users\rahul\Downloads\SalesInvoice-RO--NOV19-8181-1.pdf"
        ##"C:\Users\rahul\Downloads\SalesInvoice-RO--NOV19-7538-1.pdf"
        ##"C:\Users\rahul\Downloads\SalesInvoice-RO--NOV19-5058-1.pdf"
        ##"C:\Users\rahul\Downloads\SalesInvoice-RO--NOV06-7099-1.pdf"
        ##"C:\Users\rahul\Downloads\Charlie's Produce 2.png"
        ##"C:\Users\rahul\Downloads\Charlie's Produce 1.png"
       ### "C:\Users\rahul\Downloads\Dru Bru List.csv"
       ###v"C:\Users\rahul\Downloads\SalesInvoice-RO--NOV19-7538-1.pdf"
        invoice_file_path = "C:/Users/rahul/OneDrive/Desktop/New folder (2)/Book1.xlsx"
        results = main(invoice_file_path)
    except Exception as e:
        logging.error(f"Fatal error in main execution: {str(e)}")
        sys.exit(1)