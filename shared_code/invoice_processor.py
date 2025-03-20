import os
import json
import asyncio
from openai import AsyncOpenAI
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from .excel import process_excel_file, send_to_gpt, merge_or_add_invoice


# Initialize clients
document_analysis_client = DocumentAnalysisClient(
    endpoint=os.environ["AZURE_FORM_RECOGNIZER_ENDPOINT"],
    credential=AzureKeyCredential(os.environ["AZURE_FORM_RECOGNIZER_KEY"])
)

openai_client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

def clean_text(content):
    """Clean text content efficiently"""
    if not content:
        return ""
    return ''.join(char for char in content if char.isprintable() or char.isspace()).strip()

def parse_json_safely(text):
    """Parse JSON with better error handling"""
    try:
        # Remove markdown if present
        if "```" in text:
            text = text[text.find('{'):text.rfind('}')+1]
        return json.loads(text)
    except json.JSONDecodeError:
        return None

async def send_to_gpt_async(page_data, retries=3):
    """Send data to GPT with better retry handling"""
    delay = 1
    for attempt in range(retries):
        try:
            response = await openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt + page_data}
                ],
                max_tokens=16000,
                temperature=0.1
            )
            
            if response and response.choices:
                content = clean_text(response.choices[0].message.content)
                return parse_json_safely(content)
                
        except Exception as e:
            if attempt == retries - 1:
                print(f"GPT processing failed: {str(e)}")
                return None
            await asyncio.sleep(delay)
            delay *= 2
    
    return None

def process_table_cells(table):
    """Process table cells more efficiently"""
    rows = {}
    for cell in table.cells:
        row_idx = cell.row_index
        col_idx = cell.column_index
        
        if row_idx not in rows:
            rows[row_idx] = {}
        rows[row_idx][col_idx] = clean_text(cell.content)

    table_text = []
    for row_idx in sorted(rows.keys()):
        row = rows[row_idx]
        # Convert row to tab-separated string
        row_text = '\t'.join(row.get(i, '') for i in range(max(row.keys()) + 1))
        table_text.append(row_text)
    
    return '\n'.join(table_text)

def extract_document_content(file_path):
    """Extract content from document with better structure"""
    try:
        with open(file_path, "rb") as doc:
            poller = document_analysis_client.begin_analyze_document(
                "prebuilt-layout", doc
            )
            result = poller.result()

        pages = {}
        
        # Process all pages first
        for page in result.pages:
            page_num = page.page_number
            pages[page_num] = {
                'text': [],
                'tables': []
            }
            
            # Extract and sort text by position
            text_lines = []
            for line in page.lines:
                y_pos = min(p.y for p in line.polygon)
                x_pos = min(p.x for p in line.polygon)
                text_lines.append((y_pos, x_pos, clean_text(line.content)))
            
            # Sort and store text
            text_lines.sort()  # Will sort by y_pos, then x_pos
            pages[page_num]['text'] = [line[2] for line in text_lines]

        # Process tables
        for table in result.tables:
            page_num = table.bounding_regions[0].page_number
            table_content = process_table_cells(table)
            pages[page_num]['tables'].append(table_content)

        return pages

    except Exception as e:
        print(f"Document processing error: {str(e)}")
        return None

def format_content(page_data, page_num):
    """Format page content more efficiently"""
    content = [f"\n----- Page {page_num} Start -----\n"]
    
    # Add text content
    if page_data['text']:
        content.append("TEXT CONTENT:")
        content.extend(f"{i}:{line}" for i, line in enumerate(page_data['text'], 1))
    
    # Add tables
    for idx, table in enumerate(page_data['tables'], 1):
        content.extend([
            f"\n----- Table {idx} Start -----\n",
            f"Header: {table.split(chr(10))[0]}"  # Using chr(10) instead of '\n'
        ])
        
        # Add table rows
        rows = table.split(chr(10))[1:]  # Using chr(10) instead of '\n'
        content.extend(f"Row {i}: {row}" for i, row in enumerate(rows, 1))
        content.append(f"----- Table {idx} End -----\n")
    
    content.append(f"----- Page {page_num} End -----\n")
    return '\n'.join(content)

async def process_large_content(content, chunk_size=14000):
    """Process large content in chunks more efficiently"""
    chunks = []
    current_chunk = []
    current_size = 0
    
    for line in content.split('\n'):
        line_size = len(line) + 1  # +1 for newline
        
        if current_size + line_size > chunk_size and current_chunk:
            chunks.append('\n'.join(current_chunk))
            current_chunk = []
            current_size = 0
            
        current_chunk.append(line)
        current_size += line_size
    
    if current_chunk:
        chunks.append('\n'.join(current_chunk))
    
    # Process chunks concurrently
    tasks = [send_to_gpt_async(chunk) for chunk in chunks]
    return await asyncio.gather(*tasks)

def merge_invoice_items(current, new_items):
    """Merge invoice items more efficiently"""
    if not new_items:
        return current
    
    if not current:
        return new_items
        
    current.extend(new_items)
    return current

async def process_invoice_with_gpt(file_path,is_excel):
    """Process invoice with better error handling and efficiency"""

    try:
        if is_excel:
            # Import and use the Excel processing function
            from .excel import process_invoice_with_gpt as process_excel
            return process_excel(file_path)

        # Extract document content
        pages = extract_document_content(file_path)
        if not pages:
            return None

        all_invoices = []
        current_invoice = None
        
        # Process each page
        for page_num in sorted(pages.keys()):
            page_content = format_content(pages[page_num], page_num)
            
            # Handle large content
            if len(page_content) > 14000:
                results = await process_large_content(page_content)
                for result in results:
                    if result:
                        if current_invoice:
                            # Merge items if same invoice
                            if result.get('Invoice Number') == current_invoice.get('Invoice Number'):
                                current_invoice['List of Items'] = merge_invoice_items(
                                    current_invoice['List of Items'],
                                    result.get('List of Items', [])
                                )
                                # Update total if needed
                                if result.get('Total'):
                                    current_invoice['Total'] = result['Total']
                            else:
                                all_invoices.append(current_invoice)
                                current_invoice = result
                        else:
                            current_invoice = result
            else:
                # Process normal sized content
                result = await send_to_gpt_async(page_content)
                if result:
                    if current_invoice:
                        if result.get('Invoice Number') == current_invoice.get('Invoice Number'):
                            current_invoice['List of Items'] = merge_invoice_items(
                                current_invoice['List of Items'],
                                result.get('List of Items', [])
                            )
                            if result.get('Total'):
                                current_invoice['Total'] = result['Total']
                        else:
                            all_invoices.append(current_invoice)
                            current_invoice = result
                    else:
                        current_invoice = result
            
            await asyncio.sleep(0.1)  # Small delay between pages
        
        # Add last invoice
        if current_invoice:
            all_invoices.append(current_invoice)
        
        return all_invoices
        
    except Exception as e:
        print(f"Processing error: {str(e)}")
        return None

async def main():
    try:
        file_path = "C:/Users/rahul/Downloads/RESTAURANT DEPOT INVOICE 4.pdf"
        results = await process_invoice_with_gpt(file_path)
        
        if results:
            print(f"Successfully processed {len(results)} invoices")
            return results
        else:
            print("No invoices were processed successfully")
            return None
            
    except Exception as e:
        print(f"Error in main execution: {str(e)}")
        return None

if __name__ == "__main__":
    asyncio.run(main())
json_template = {
        "Supplier Name": "",
        "Sold to Address": "",
        "Order Date": "",
        "Ship Date": "",
        "Invoice Number": "",
        "Shipping Address": "",
        "Total": 0,
        "Location":"",
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
                "Cost of Each Item":1.0,
                "Status": ""
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
      • Location:
        - Looking for the reference to location,look for shipping address,Delivered Address
        - If you have any reference to location then set the location else "N/A"

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
            1.PRODUCE: Fresh Fruits/Vegetables
                Examples:
                Fruits: Apples, Bananas, Oranges
                Vegetables: Spinach, Carrots, Tomatoes
                Herbs: Basil, Cilantro

            2.DAIRY: Milk, Cheese, Yogurt
                Examples:
                Milk: Whole Milk, Skim Milk
                Cheese: Cheddar, Mozzarella
                Yogurt: Greek Yogurt, Regular Yogurt

            3.MEAT: Beef, Pork, Poultry
                Examples:
                Beef: Ground Beef, Ribeye Steaks
                Pork: Bacon, Pork Chops
                Poultry: Chicken Breasts, Whole Turkeys

            4.SEAFOOD: Fish, Shellfish
                Examples:
                Fish: Salmon, Tuna
                Shellfish: Shrimp, Crab

            5.BEVERAGES: Sodas, Juices, Water
                Examples:
                Sodas: Cola, Lemon-Lime
                Juices: Orange Juice, Apple Juice
                Water: Bottled Water

            6.DRY GROCERY: Chips, Candy, Nuts, Canned Goods, Spices, Sauces
                Examples:
                Snacks: Potato Chips, Candy Bars
                Nuts: Almonds, Peanuts
                Canned Goods: Canned Beans, Canned Vegetables
                Spices & Sauces: Salt, Soy Sauce
            7.BAKERY: Bread, Pastries, Cakes
                Examples:
                Bread: Whole Wheat Bread, Sourdough Baguettes
                Pastries: Croissants, Muffins
                Cakes: Chocolate Cake, Cupcakes
                FROZEN: Ice Cream, Meals, Desserts
                Ice Cream: Vanilla, Chocolate
                Meals: Frozen Pizza, TV Dinners
                Desserts: Sorbet, Frozen Yogurt
            8.PAPER GOODS AND DISPOSABLES: Bags, Napkins, Plates, Cups, Utensils, Packing Materials
                Examples:
                Bags: Grocery Bags, Trash Bags
                Napkins: Paper Napkins
                Serveware: Plastic Plates, Cups, Utensils
                Packing Materials: Bubble Wrap, Cardboard Boxes

            9.LIQUOR: Beer, Wine, Spirits
                Examples:
                Beer: Lager, Ale
                Wine: Red Wine, White Wine
                Spirits: Vodka, Whiskey
            10.CHEMICAL: Soaps, Detergents, Supplies
                Examples:
                Soaps: Hand Soap, Dish Soap
                Detergents: Laundry Detergent
                Supplies: Cleaning Sprays
            11.OTHER: Anything Not in Above Categories

            Examples: Office Furniture, Tools, Toys, Electronics

   B. Quantity and Measurement Details
      • Quantity Shipped
        Headers to check:
        - "Qty:", "Quantity:", "Shipped:"
        Rules:
        - Must be positive number
        - Default to 1 if missing
      
      • Quantity In a Case
        Headers to check:
        - "Units/Case:", "Pack Size:", "Case Pack:"
        Patterns to check:
        -  24= "24 units"
        - "24/12oz" = 24 units
        - "2/12ct" = 24 units
        Default: 1 if not found
      
      • Measurement Of Each Item
        Headers to check:
        - "Size:", "Weight:", "Volume:"
        Extract from description:
        - "5 LB BAG" → 5
        - "32 OZ PKG" → 32
      

   B. Measurement Units:
      • Measured In - Standard Units:
        
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
        Calculate: Measurement of Each Item * Quantity In Case * Quantity Shipped
        Example: 5lb * 10 per case * 2 cases = 100 pounds

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
       Look for the reference "Measured in" 
        Values:
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

       • Status

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
"""    
