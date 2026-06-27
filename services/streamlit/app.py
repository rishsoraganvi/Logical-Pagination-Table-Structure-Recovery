import streamlit as st
import requests
import time
import json

# Configure the page
st.set_page_config(
    page_title="Loan Document IDP Pipeline",
    page_icon="📄",
    layout="wide"
)

st.title("Loan Document IDP Pipeline")
st.markdown("""
    Upload a PDF loan document to extract logical pagination (document boundaries) and table structure.
    The processed results will be displayed below.
""")

# Backend base URL (relative to the current origin, proxied by Nginx to the API service)
BACKEND_URL = ""  # empty string means same origin

def upload_pdf(file):
    """Upload a PDF file to the backend and return the job ID."""
    files = {"file": (file.name, file.getvalue(), "application/pdf")}
    try:
        response = requests.post(f"{BACKEND_URL}/api/pipeline/run", files=files)
        response.raise_for_status()
        return response.json()["job_id"]
    except requests.exceptions.RequestException as e:
        st.error(f"Error uploading file: {e}")
        return None

def get_job_status(job_id):
    """Get the status of a job."""
    try:
        response = requests.get(f"{BACKEND_URL}/api/pipeline/status/{job_id}")
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching job status: {e}")
        return None

def get_job_result(job_id):
    """Get the result of a completed job."""
    try:
        response = requests.get(f"{BACKEND_URL}/api/pipeline/result/{job_id}")
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching job result: {e}")
        return None

# File uploader
uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")

if uploaded_file is not None:
    # Display file details
    st.write(f"Filename: {uploaded_file.name}")

    # Start processing button
    if st.button("Process Document"):
        with st.spinner("Uploading file..."):
            job_id = upload_pdf(uploaded_file)

        if job_id:
            st.success(f"Started processing with job ID: {job_id}")

            # Progress bar and status
            progress_bar = st.progress(0)
            status_text = st.empty()

            # Poll for completion
            while True:
                status = get_job_status(job_id)
                if status is None:
                    break

                stage = status.get("stage", "unknown")
                progress = status.get("progress", 0)

                # Update progress
                progress_bar.progress(progress)
                status_text.text(f"Stage: {stage} ({progress}%)")

                if stage == "done":
                    st.success("Processing completed!")
                    break
                elif stage == "error":
                    st.error(f"Processing failed: {status.get('error', 'Unknown error')}")
                    break

                # Wait before polling again
                time.sleep(2)

            # If completed, fetch and display results
            if status and status.get("stage") == "done":
                with st.spinner("Fetching results..."):
                    result = get_job_result(job_id)

                if result:
                    st.subheader("Processing Results")

                    # Display documents.json
                    with st.expander("Documents (Logical Pagination)", expanded=True):
                        st.json(result.get("documents", {}))

                    # Display tables.json
                    with st.expander("Tables", expanded=True):
                        st.json(result.get("tables", {}))

                    # Optionally display metrics
                    if "metrics" in result:
                        with st.expander("Metrics"):
                            st.json(result["metrics"])
                else:
                    st.error("Failed to retrieve results.")
else:
    st.info("Please upload a PDF file to begin.")

# Footer
st.markdown("---")
st.markdown("Built with Streamlit and FastAPI")