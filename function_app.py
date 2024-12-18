import os
import json
import logging
from typing import List, Dict, Any
import azure.functions as func
import azure.durable_functions as df
from azure.storage.blob.aio import BlobServiceClient
import mimetypes
import tempfile

# Import shared code modules
from shared_code.invoice_processor import process_invoice_with_gpt
from shared_code.cosmos_operations import get_cosmos_manager
from shared_code.models import Invoice

# Initialize the Durable Function App
app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Initialize BlobServiceClient
blob_service_client = BlobServiceClient.from_connection_string(os.environ["AzureWebJobsStorage"])

@app.route(route="process-invoice/{user_id}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@app.durable_client_input(client_name="client")  # Provide the required client_name parameter
async def http_trigger(req: func.HttpRequest, client):
    """
    HTTP trigger function for processing invoices.
    """
    try:
        user_id = req.route_params.get('user_id')
        if not user_id:
            return func.HttpResponse("User ID is required", status_code=400)

        # Collect files from the request and upload to Blob Storage
        blob_references = []
        try:
            for file_name in req.files:
                file = req.files[file_name]
                if not file:
                    continue

                # Upload file to Blob Storage directly from the stream
                blob_name = f"{user_id}/{file.filename}"
                container_name = "userinvoices"  # Ensure this container exists
                blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)

                # Upload directly from the file stream without reading into memory
                await blob_client.upload_blob(file.stream, overwrite=True)

                # Add blob reference to list
                blob_references.append({
                    "blob_name": blob_name,
                    "container_name": container_name
                })

        except Exception as e:
            logging.error(f"Error uploading files to Blob Storage: {str(e)}")
            return func.HttpResponse(f"Error uploading files: {str(e)}", status_code=500)

        if not blob_references:
            return func.HttpResponse("No valid files were uploaded", status_code=400)

        # Create input data for orchestration
        input_data = {
            "user_id": user_id,
            "blobs": blob_references
        }

        # Start orchestration using the injected client
        instance_id = await client.start_new("process_invoice_orchestrator", None, input_data)

        # Create status response and return it directly
        status_response = client.create_check_status_response(req, instance_id)
        return status_response

    except Exception as e:
        logging.error(f"Error in HTTP trigger: {str(e)}")
        return func.HttpResponse(f"Internal server error: {str(e)}", status_code=500)

@app.orchestration_trigger(context_name="context")
def process_invoice_orchestrator(context: df.DurableOrchestrationContext):
    """
    Orchestrator function for invoice processing workflow.
    """
    try:
        input_data = context.get_input()
        if isinstance(input_data, str):
            input_data = json.loads(input_data)
            
        blobs = input_data.get("blobs", [])
        user_id = input_data.get("user_id")

        if not blobs or not user_id:
            return {
                "status": "failed",
                "message": "Invalid input data",
                "invoice_count": 0
            }

        # Process blobs in parallel
        tasks = []
        for blob_info in blobs:
            task_input = {
                "blob_info": blob_info,
                "user_id": user_id
            }
            task = context.call_activity("process_file_activity", task_input)
            tasks.append(task)

        results = yield context.task_all(tasks)

        # Combine results
        all_invoices = []
        for result in results:
            if result and isinstance(result, list):
                all_invoices.extend(result)

        if not all_invoices:
            return {
                "status": "completed",
                "message": "No invoices were found in the processed files",
                "invoice_count": 0
            }

        # Store invoices
        store_data = {
            "user_id": user_id,
            "invoices": all_invoices
        }
        
        store_result = yield context.call_activity("store_invoices_activity", store_data)

        return {
            "status": "completed",
            "message": f"Successfully processed {len(all_invoices)} invoices",
            "invoice_count": len(all_invoices),
            "store_result": store_result
        }

    except Exception as e:
        error_msg = f"Error in orchestrator: {str(e)}"
        logging.error(error_msg)
        return {
            "status": "failed",
            "error": error_msg,
            "invoice_count": 0
        }

@app.activity_trigger(input_name="taskinput")
async def process_file_activity(taskinput: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Activity function that processes a single file.
    """
    try:
        blob_info = taskinput.get("blob_info")
        user_id = taskinput.get("user_id")

        if not blob_info:
            logging.error("No blob info provided")
            return []

        blob_name = blob_info.get("blob_name")
        container_name = blob_info.get("container_name")

        logging.info(f"Processing blob: {blob_name}")

        # Initialize BlobServiceClient
        blob_service_client = BlobServiceClient.from_connection_string(os.environ["AzureWebJobsStorage"])

        # Get Blob Client
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)

        # Download the blob content into bytes
        blob_data = await blob_client.download_blob()
        file_content = await blob_data.readall()

        # Determine the file type
        mime_type, _ = mimetypes.guess_type(blob_name)
        if mime_type is None:
            logging.warning(f"Unable to determine MIME type for blob: {blob_name}")
            return []

        # Write the file content to a temporary file
        _, file_extension = os.path.splitext(blob_name)
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
            temp_file.write(file_content)
            temp_file_path = temp_file.name

        try:
            # Process the file based on its MIME type
            if mime_type.startswith('image/'):
                logging.info(f"Processing image file: {blob_name}")
                # Ensure the function accepts the file path and file type
                results = await process_invoice_with_gpt(temp_file_path)
            elif mime_type == 'application/pdf':
                logging.info(f"Processing PDF file: {blob_name}")
                results = await process_invoice_with_gpt(temp_file_path)
            else:
                logging.warning(f"Unsupported file type: {mime_type} for blob: {blob_name}")
                return []

            if not results:
                logging.warning(f"No invoices found in blob: {blob_name}")
                return []

            logging.info(f"Successfully processed {len(results)} invoices from {blob_name}")
            return results

        finally:
            # Clean up the temporary file
            os.remove(temp_file_path)

    except Exception as e:
        logging.error(f"Error processing blob {blob_name}: {str(e)}")
        raise

@app.activity_trigger(input_name="invoicedata")
async def store_invoices_activity(invoicedata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Activity function that stores processed invoices in Cosmos DB.
    """
    try:
        user_id = invoicedata.get("user_id")
        invoices_data = invoicedata.get("invoices", [])

        if not user_id:
            raise ValueError("User ID is required")

        if not invoices_data:
            return {
                "status": "completed",
                "message": "No invoices to store",
                "stored_count": 0
            }

        # Convert raw invoice data to Invoice objects
        invoices = []
        for invoice_dict in invoices_data:
            try:
                invoice = Invoice.from_dict(invoice_dict)
                invoices.append(invoice)
            except Exception as e:
                logging.error(f"Error converting invoice: {str(e)}")
                continue

        if not invoices:
            return {
                "status": "completed",
                "message": "No valid invoices to store",
                "stored_count": 0
            }

        # Store in Cosmos DB
        cosmos_manager = await get_cosmos_manager()
        result = await cosmos_manager.store_invoices(user_id, invoices)

        return {
            "status": "completed",
            "message": f"Successfully stored {len(invoices)} invoices",
            "stored_count": len(invoices),
            "cosmos_result": result
        }

    except Exception as e:
        logging.error(f"Error storing invoices: {str(e)}")
        raise
