from typing import List, Dict, Any
from dataclasses import dataclass, field

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
            Currency=str(data.get('Currency', ''))
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
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
            'Currency': self.Currency
        }

@dataclass
class Invoice:
    Supplier_Name: str
    Sold_to_Address: str
    Order_Date: str
    Ship_Date: str
    Invoice_Number: str
    Shipping_Address: str
    Total: float
    Items: List[InvoiceItem] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Invoice':
        items_data = data.get('List of Items', [])
        items = [InvoiceItem.from_dict(item) for item in items_data]
        return cls(
            Supplier_Name=str(data.get('Supplier Name', '')),
            Sold_to_Address=str(data.get('Sold to Address', '')),
            Order_Date=str(data.get('Order Date', '')),
            Ship_Date=str(data.get('Ship Date', '')),
            Invoice_Number=str(data.get('Invoice Number', '')),
            Shipping_Address=str(data.get('Shipping Address', '')),
            Total=float(data.get('Total', 0.0)),
            Items=items
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'Supplier Name': self.Supplier_Name,
            'Sold to Address': self.Sold_to_Address,
            'Order Date': self.Order_Date,
            'Ship Date': self.Ship_Date,
            'Invoice Number': self.Invoice_Number,
            'Shipping Address': self.Shipping_Address,
            'Total': self.Total,
            'Items': [item.to_dict() for item in self.Items]
        }
