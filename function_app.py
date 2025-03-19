import os
import json
import logging
import tempfile
import mimetypes
from typing import List, Dict, Any

import azure.functions as func
import azure.durable_functions as df
from azure.storage.blob.aio import BlobServiceClient

# Import shared code modules (ensure these are implemented in your shared_code folder)
from shared_code.invoice_processor import process_invoice_with_gpt
from shared_code.cosmos_operations import get_cosmos_manager
from shared_code.models import Invoice

# Import SendGrid modules for sending emails
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# Initialize the Durable Function App
app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Initialize BlobServiceClient using the connection string from environment variables
blob_service_client = BlobServiceClient.from_connection_string(os.environ["AzureWebJobsStorage"])

###############################################################################
# HTTP Trigger Function
###############################################################################
@app.route(route="process-invoice/{user_id}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@app.durable_client_input(client_name="client")
async def http_trigger(req: func.HttpRequest, client: df.DurableOrchestrationClient):
    """
    HTTP trigger function for processing invoices.
    - The URL parameter "user_id" is treated as the user's email address.
    - Files are uploaded to Blob Storage.
    - The Durable Functions orchestration is started and runs in the background.
      (This means that even if the user closes their browser, the processing continues.)
    """
    try:
        # Get the user ID, which is also the user's email address
        user_id = req.route_params.get('user_id')
        user_email = user_id  # In this design, the user_id IS the email

        if not user_id:
            return func.HttpResponse("User ID is required", status_code=400)

        # Upload files from the request to Blob Storage
        blob_references = []
        try:
            for file_name in req.files:
                file = req.files[file_name]
                if not file:
                    continue

                # Construct a blob name using the user's email and the original filename
                blob_name = f"{user_id}/{file.filename}"
                container_name = "userinvoices"  # Ensure this container exists in your storage account
                blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)

                # Upload file directly from the stream
                await blob_client.upload_blob(file.stream, overwrite=True)

                blob_references.append({
                    "blob_name": blob_name,
                    "container_name": container_name
                })
        except Exception as e:
            logging.error(f"Error uploading files to Blob Storage: {str(e)}")
            return func.HttpResponse(f"Error uploading files: {str(e)}", status_code=500)

        if not blob_references:
            return func.HttpResponse("No valid files were uploaded", status_code=400)

        # Prepare input data for the orchestration
        input_data = {
            "user_id": user_id,
            "user_email": user_email,
            "blobs": blob_references
        }

        # Start the orchestration (the process will continue in the background)
        instance_id = await client.start_new("process_invoice_orchestrator", None, input_data)

        # Return a status endpoint so that the client can later check the progress
        status_response = client.create_check_status_response(req, instance_id)
        return status_response

    except Exception as e:
        logging.error(f"Error in HTTP trigger: {str(e)}")
        return func.HttpResponse(f"Internal server error: {str(e)}", status_code=500)

###############################################################################
# Orchestrator Function
###############################################################################
@app.orchestration_trigger(context_name="context")
def process_invoice_orchestrator(context: df.DurableOrchestrationContext):
    """
    Orchestrator function for the invoice processing workflow.
    This orchestration:
      1. Processes each uploaded file in parallel.
      2. Stores the processed invoices in Cosmos DB.
      3. Sends an email notification via SendGrid.
    """
    try:
        input_data = context.get_input()
        if isinstance(input_data, str):
            input_data = json.loads(input_data)

        blobs = input_data.get("blobs", [])
        user_id = input_data.get("user_id")
        user_email = input_data.get("user_email")

        if not blobs or not user_id:
            return {
                "status": "failed",
                "message": "Invalid input data",
                "invoice_count": 0
            }

        # Process each file in parallel via an activity function
        tasks = []
        for blob_info in blobs:
            task_input = {
                "blob_info": blob_info,
                "user_id": user_id
            }
            task = context.call_activity("process_file_activity", task_input)
            tasks.append(task)

        results = yield context.task_all(tasks)

        # Combine all invoice results from the processed files
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

        # Store invoices in Cosmos DB using an activity function
        store_data = {
            "user_id": user_id,
            "invoices": all_invoices
        }
        store_result = yield context.call_activity("store_invoices_activity", store_data)

        # Prepare email notification data
        notification_message = (
            f"Dear {user_id},\n\n"
            "Your invoices have been processed and stored successfully in Cosmos DB.\n\n"
            "Thank you for using our service."
        )
        notification_data = {
            "user_email": user_email,
            "subject": "Invoice Processing Complete",
            "message": notification_message
        }

        # Send the email notification via an activity function
        notification_result = yield context.call_activity("send_email_activity", notification_data)

        return {
            "status": "completed",
            "message": f"Successfully processed {len(all_invoices)} invoices.",
            "invoice_count": len(all_invoices),
            "store_result": store_result,
            "notification_result": notification_result
        }

    except Exception as e:
        error_msg = f"Error in orchestrator: {str(e)}"
        logging.error(error_msg)
        return {
            "status": "failed",
            "error": error_msg,
            "invoice_count": 0
        }

###############################################################################
# Activity Function: Process a File
###############################################################################
@app.activity_trigger(input_name="taskinput")
async def process_file_activity(taskinput: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Activity function that processes a single file.
    Depending on the MIME type (image, PDF, Excel), it calls the appropriate helper function.
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

        # Create a BlobServiceClient instance (if needed)
        blob_service = BlobServiceClient.from_connection_string(os.environ["AzureWebJobsStorage"])
        blob_client = blob_service.get_blob_client(container=container_name, blob=blob_name)

        # Download the blob content as bytes
        blob_data = await blob_client.download_blob()
        file_content = await blob_data.readall()

        # Determine the MIME type of the file
        mime_type, _ = mimetypes.guess_type(blob_name)
        if mime_type is None:
            logging.warning(f"Unable to determine MIME type for blob: {blob_name}")
            return []

        # Write the content to a temporary file
        _, file_extension = os.path.splitext(blob_name)
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
            temp_file.write(file_content)
            temp_file_path = temp_file.name

        try:
            # Process file based on its MIME type
            if mime_type.startswith('image/'):
                logging.info(f"Processing image file: {blob_name}")
                results = await process_invoice_with_gpt(temp_file_path)
            elif mime_type == 'application/pdf':
                logging.info(f"Processing PDF file: {blob_name}")
                results = await process_invoice_with_gpt(temp_file_path)
            elif mime_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
                result=await process_invoice_with_gpt(temp_file_path)    
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

###############################################################################
# Activity Function: Store Invoices in Cosmos DB
###############################################################################
@app.activity_trigger(input_name="invoicedata")
async def store_invoices_activity(invoicedata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Activity function that stores processed invoices in Cosmos DB with pagination.
    Each page contains 10 items.
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
                "stored_count": 0,
                "total_pages": 0,
                "current_page": 0
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
                "stored_count": 0,
                "total_pages": 0,
                "current_page": 0
            }

        # Calculate pagination information
        items_per_page = 10
        total_invoices = len(invoices)
        total_pages = (total_invoices + items_per_page - 1) // items_per_page

        cosmos_manager = await get_cosmos_manager()
        stored_count = 0
        page_results = []

        for page in range(1, total_pages + 1):
            start_idx = (page - 1) * items_per_page
            end_idx = min(start_idx + items_per_page, total_invoices)
            page_invoices = invoices[start_idx:end_idx]

            # Add page information to each invoice
            for invoice in page_invoices:
                invoice.page = page
                invoice.total_pages = total_pages

            page_result = await cosmos_manager.store_invoices(user_id, page_invoices)
            stored_count += len(page_invoices)
            page_results.append({
                "page": page,
                "items_stored": len(page_invoices),
                "cosmos_result": page_result
            })

        return {
            "status": "completed",
            "message": f"Successfully stored {stored_count} invoices across {total_pages} pages",
            "stored_count": stored_count,
            "total_pages": total_pages,
            "page_results": page_results,
            "items_per_page": items_per_page
        }

    except Exception as e:
        logging.error(f"Error storing invoices: {str(e)}")
        raise

###############################################################################
# Activity Function: Send Email Notification via SendGrid
###############################################################################
@app.activity_trigger(input_name="notificationdata")
async def send_email_activity(notificationdata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Activity function that sends an email notification to the user once invoice
    storage is complete.
    """
    try:
        user_email = notificationdata.get("user_email")
        subject = notificationdata.get("subject", "Invoice Processing Notification")
        message = notificationdata.get("message", "")

        if not user_email:
            raise ValueError("User email is required for sending the notification email.")

        email_message = Mail(
            from_email=os.environ["SENDER_EMAIL"],
            to_emails=[user_email],
            subject=subject,
            plain_text_content=message
        )

        sg = SendGridAPIClient(api_key=os.environ["SENDGRID_API_KEY"])
        response = sg.send(email_message)

        logging.info(f"Email sent to {user_email} with status code {response.status_code}.")
        return {
            "status": "sent",
            "response_code": response.status_code
        }

    except Exception as e:
        logging.error(f"Error sending email: {str(e)}")
        raise
