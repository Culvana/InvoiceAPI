from typing import List, Dict, Any
from dataclasses import dataclass, field
import re
import random
import uuid

@dataclass
class InvoiceItem:
    Item_Number: str
    Item_Name: str
    Product_Category: str
    Quantity_In_a_Case: float
    Measurement_Of_Each_Item: float
    Measured_In: str
    Quantity_Shipped: float
    Extended_Price: float
    Total_Units_Ordered: float
    Case_Price: float
    Catch_Weight: str
    Priced_By: str
    Splitable: str
    Split_Price: str
    Cost_of_a_Unit: float
    Cost_of_Each_Item: float
    Currency: str
    Inventoryitem: bool
    page_number: int = field(default=1)
    item_index: int = field(default=0)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InvoiceItem':
        return cls(
            Item_Number=str(data.get('Item Number', '')),
            Item_Name=str(data.get('Item Name', '')),
            Product_Category=str(data.get('Product Category', '')),
            Quantity_In_a_Case=float(data.get('Quantity In a Case', 0.0)),
            Measurement_Of_Each_Item=float(data.get('Measurement Of Each Item', 0.0)),
            Measured_In=str(data.get('Measured In', '')),
            Quantity_Shipped=float(data.get('Quantity Shipped', 0.0)),
            Extended_Price=float(data.get('Extended Price', 0.0)),
            Total_Units_Ordered=float(data.get('Total Units Ordered', 0.0)),
            Case_Price=float(data.get('Case Price', 0.0)),
            Catch_Weight=str(data.get('Catch Weight', '')),
            Priced_By=str(data.get('Priced By', '')),
            Splitable=str(data.get('Splitable', '')),
            Split_Price=str(data.get('Split Price', '')),
            Cost_of_a_Unit=float(data.get('Cost of a Unit', 0.0)),
            Cost_of_Each_Item=float(data.get('Cost of Each Item', 0.0)),
            Currency=str(data.get('Currency', '')),
            page_number=int(data.get('page_number', 1)),
            item_index=int(data.get('item_index', 0)),
            Inventoryitem=bool(data.get('Inventoryitem',False))
        )

    def to_dict(self) -> Dict[str, Any]:
        base_dict = {
            'Item Number': self.Item_Number,
            'Item Name': self.Item_Name,
            'Product Category': self.Product_Category,
            'Quantity In a Case': self.Quantity_In_a_Case,
            'Measurement Of Each Item': self.Measurement_Of_Each_Item,
            'Measured In': self.Measured_In,
            'Quantity Shipped': self.Quantity_Shipped,
            'Extended Price': self.Extended_Price,
            'Total Units Ordered': self.Total_Units_Ordered,
            'Case Price': self.Case_Price,
            'Catch Weight': self.Catch_Weight,
            'Priced By': self.Priced_By,
            'Splitable': self.Splitable,
            'Split Price': self.Split_Price,
            'Cost of a Unit': self.Cost_of_a_Unit,
            'Cost of Each Item': self.Cost_of_Each_Item,
            'Currency': self.Currency,
            'page_number': self.page_number,
            'item_index': self.item_index,
            'Inventoryitem': self.Inventoryitem
        }
        return base_dict

@dataclass
class Invoice:
    Supplier_Name: str
    Sold_to_Address: str
    Order_Date: str
    Ship_Date: str
    Invoice_Number: str
    Shipping_Address: str
    Total: float
    PO_NUMBER: int  # Random 5-digit number
    location: str = field(default="")  # Default to N/A
    status: str = field(default="")
    Items: List[InvoiceItem] = field(default_factory=list)
    page: int = field(default=1)
    total_pages: int = field(default=1)
    items_per_page: int = field(default=10)
    total_items: int = field(default=0)

    @staticmethod
    def extract_location_from_address(address: str) -> str:
        """Extract city and state from address."""
        try:
            if not address:
                return "N/A"

            # Split address by commas and clean each part
            parts = [part.strip() for part in address.split(',')]
            
            # Look for state pattern (2 uppercase letters, optionally followed by zip)
            for i in range(len(parts) - 1, -1, -1):
                state_match = re.search(r'\b([A-Z]{2})\b', parts[i])
                if state_match and i > 0:
                    state = state_match.group(1)
                    city = parts[i-1].strip()
                    # Clean city name (remove any numbers or extra spaces)
                    city = re.sub(r'\d+', '', city).strip()
                    return f"{city}, {state}"

            return "N/A"
        except Exception:
            return "N/A"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Invoice':
        # Extract location from addresses
        shipping_addr = data.get('Shipping Address', '')
        sold_to_addr = data.get('Sold to Address', '')
        
        # Try shipping address first, then sold-to address
        location = cls.extract_location_from_address(shipping_addr)
        if location == "N/A":
            location = cls.extract_location_from_address(sold_to_addr)

        # Process items with pagination
        items_data = data.get('List of Items', [])
        items_per_page = 10
        total_items = len(items_data)
        total_pages = max(
            (total_items + items_per_page - 1) // items_per_page,
            max((item.get('page_number', 1) for item in items_data), default=1)
        )
        current_page = data.get('page', 1)
        current_page = max(1, min(current_page, total_pages))

        # Create items with pagination information
        items = []
        for idx, item_data in enumerate(items_data):
            page_number = (idx // items_per_page) + 1
            item_index = idx % items_per_page
            item_data.update({
                'page_number': page_number,
                'item_index': item_index
            })
            items.append(InvoiceItem.from_dict(item_data))

        return cls(
            Supplier_Name=str(data.get('Supplier Name', '')),
            Sold_to_Address=str(data.get('Sold to Address', '')),
            Order_Date=str(data.get('Order Date', '')),
            Ship_Date=str(data.get('Ship Date', '')),
            Invoice_Number=str(data.get('Invoice Number', '')),
            Shipping_Address=str(data.get('Shipping Address', '')),
            Total=float(data.get('Total', 0.0)),
            PO_NUMBER=random.randint(10000, 99999),
            location=location,  # Use extracted location
            status=str(data.get('status', '')),
            Items=items,
            page=current_page,
            total_pages=total_pages,
            items_per_page=items_per_page,
            total_items=total_items
        )

    def to_dict(self) -> Dict[str, Any]:
        # Recalculate pagination info
        max_page_in_items = max((item.page_number for item in self.Items), default=1)
        self.total_pages = max(
            self.total_pages,
            max_page_in_items,
            (len(self.Items) + self.items_per_page - 1) // self.items_per_page
        )
        self.total_items = len(self.Items)
        
        base_dict = {
            'Supplier Name': self.Supplier_Name,
            'Sold to Address': self.Sold_to_Address,
            'Order Date': self.Order_Date,
            'Ship Date': self.Ship_Date,
            'Invoice Number': self.Invoice_Number,
            'Shipping Address': self.Shipping_Address,
            'Total': self.Total,
            'PO_NUMBER': self.PO_NUMBER,
            'location': self.location,
            'status': self.status,
            'Items': [item.to_dict() for item in self.Items],
            'pagination_info': {
                'current_page': self.page,
                'total_pages': self.total_pages,
                'items_per_page': self.items_per_page,
                'total_items': self.total_items
            }
        }
        return base_dict

    def get_items_for_page(self, page_number: int) -> List[InvoiceItem]:
        """Returns items for a specific page number."""
        start_idx = (page_number - 1) * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.Items))
        return self.Items[start_idx:end_idx]