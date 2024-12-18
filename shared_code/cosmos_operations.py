import logging
import os
import asyncio
from azure.cosmos import CosmosClient, PartitionKey, exceptions
from typing import Optional, List, Dict, Any
from .models import Invoice

class CosmosDBManager:
    def __init__(self):
        self.client = None
        self.database = None
        self.container = None
        self.max_retries = 3
        self.base_delay = 1  # seconds

    async def initialize(self):
        """Initialize Cosmos DB connection"""
        try:
            self.client = CosmosClient(
                url=os.environ["COSMOS_ENDPOINT"],
                credential=os.environ["COSMOS_KEY"]
            )

            # Create database
            self.database = await asyncio.to_thread(
                self.client.create_database_if_not_exists,
                id=os.environ["COSMOS_DATABASE"]
            )

            # Create container
            self.container = await asyncio.to_thread(
                self.database.create_container_if_not_exists,
                id=os.environ["COSMOS_CONTAINER"],
                partition_key=PartitionKey(path="/userId"),
                offer_throughput=400
            )

            return self

        except Exception as e:
            logging.error(f"Failed to initialize Cosmos DB: {str(e)}")
            raise

    async def store_invoices(self, user_id: str, invoices: List[Invoice]) -> Dict[str, Any]:
        """Store multiple invoices under the same user_id"""
        for attempt in range(self.max_retries):
            try:
                # Check if user document exists
                user_doc = await self.get_user_document(user_id)

                # Convert invoices to dictionaries
                invoices_dicts = [invoice.to_dict() for invoice in invoices]

                if user_doc:
                    # Append new invoices to existing invoices
                    existing_invoices = user_doc.get('invoices', [])
                    existing_invoices.extend(invoices_dicts)
                    user_doc['invoices'] = existing_invoices

                    # Update the user document
                    response = await asyncio.to_thread(
                        self.container.replace_item,
                        item=user_doc,
                        body=user_doc
                    )
                    logging.info(f"Updated invoices for user_id: {user_id}")
                else:
                    # Create new user document
                    user_doc = {
                        'id': user_id,
                        'userId': user_id,
                        'invoices': invoices_dicts
                    }

                    response = await asyncio.to_thread(
                        self.container.create_item,
                        body=user_doc
                    )
                    logging.info(f"Created new user document for user_id: {user_id}")

                return response

            except exceptions.CosmosHttpResponseError as e:
                if e.status_code == 429 and attempt < self.max_retries - 1:
                    wait_time = self.base_delay * (2 ** attempt)
                    logging.warning(f"Rate limited, waiting {wait_time}s before retry {attempt + 1}")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logging.error(f"Cosmos DB error: {str(e)}")
                    raise
            except Exception as e:
                logging.error(f"Error storing invoices: {str(e)}")
                raise

    async def get_user_document(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the user document by user_id"""
        try:
            # Read the document by id and partition key
            response = await asyncio.to_thread(
                self.container.read_item,
                item=user_id,
                partition_key=user_id
            )
            return response
        except exceptions.CosmosResourceNotFoundError:
            return None
        except Exception as e:
            logging.error(f"Error retrieving user document: {str(e)}")
            raise

# Singleton instance
_cosmos_manager: Optional[CosmosDBManager] = None

async def get_cosmos_manager() -> CosmosDBManager:
    """Get or create CosmosDBManager instance"""
    global _cosmos_manager
    if _cosmos_manager is None:
        _cosmos_manager = await CosmosDBManager().initialize()
    return _cosmos_manager
