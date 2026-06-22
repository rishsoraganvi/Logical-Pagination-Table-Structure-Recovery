document.addEventListener('DOMContentLoaded', function() {
    const uploadForm = document.getElementById('uploadForm');
    const uploadBtn = document.getElementById('uploadBtn');
    const pdfFileInput = document.getElementById('pdfFile');
    const uploadStatus = document.getElementById('uploadStatus');
    const statusText = document.getElementById('statusText');
    const statusDetails = document.getElementById('statusDetails');
    const progressFill = document.getElementById('progressFill');
    const resultsSection = document.getElementById('resultsSection');
    const resultsContent = document.getElementById('resultsContent');

    let jobId = null;
    let statusInterval = null;

    // Handle form submission
    uploadForm.addEventListener('submit', async function(e) {
        e.preventDefault();

        const file = pdfFileInput.files[0];
        if (!file) {
            alert('Please select a PDF file to upload');
            return;
        }

        // Validate file type
        if (file.type !== 'application/pdf') {
            alert('Please select a valid PDF file');
            return;
        }

        // Disable form during upload
        uploadBtn.disabled = true;
        pdfFileInput.disabled = true;
        uploadStatus.classList.remove('hidden');
        resultsSection.classList.add('hidden');
        resultsContent.innerHTML = '';

        statusText.textContent = 'Uploading file...';
        statusDetails.textContent = '';
        progressFill.style.width = '0%';

        try {
            // Create FormData for file upload
            const formData = new FormData();
            formData.append('file', file, file.name);

            // Upload file to API
            const uploadResponse = await fetch('/pipeline/run', {
                method: 'POST',
                body: formData
            });

            if (!uploadResponse.ok) {
                throw new Error(`Upload failed: ${uploadResponse.statusText}`);
            }

            const uploadData = await uploadResponse.json();
            jobId = uploadData.job_id;

            // Start polling for status
            startStatusPolling();
        } catch (error) {
            console.error('Upload error:', error);
            statusText.textContent = 'Upload failed';
            statusDetails.textContent = error.message;
            progressFill.style.background = '#e74c3c';
            uploadBtn.disabled = false;
            pdfFileInput.disabled = false;
        }
    });

    // Function to start polling for job status
    function startStatusPolling() {
        statusInterval = setInterval(async () => {
            try {
                const statusResponse = await fetch(`/pipeline/status/${jobId}`);
                if (!statusResponse.ok) {
                    throw new Error(`Status check failed: ${statusResponse.statusText}`);
                }

                const statusData = await statusResponse.json();

                // Update status display
                updateStatusDisplay(statusData);

                // Check if job is complete
                if (statusData.status === 'done' || statusData.status === 'failed') {
                    clearInterval(statusInterval);
                    if (statusData.status === 'done') {
                        // Fetch and display results
                        await fetchAndDisplayResults();
                    } else {
                        statusText.textContent = 'Processing failed';
                        statusDetails.textContent = statusData.error_message || 'Unknown error occurred';
                        progressFill.style.background = '#e74c3c';
                    }
                    uploadBtn.disabled = false;
                    pdfFileInput.disabled = false;
                }
            } catch (error) {
                console.error('Status polling error:', error);
                clearInterval(statusInterval);
                statusText.textContent = 'Error checking status';
                statusDetails.textContent = error.message;
                progressFill.style.background = '#e74c3c';
                uploadBtn.disabled = false;
                pdfFileInput.disabled = false;
            }
        }, 3000); // Poll every 3 seconds
    }

    // Function to update status display
    function updateStatusDisplay(statusData) {
        const statusMessages = {
            'queued': 'Job is queued for processing',
            'running': 'Processing document...',
            'done': 'Processing completed!',
            'failed': 'Processing failed'
        };

        statusText.textContent = statusMessages[statusData.status] || `Status: ${statusData.stage}`;

        if (statusData.stage) {
            const stageNames = {
                'ingestion': 'Ingestion & Triage',
                'ocr': 'OCR Processing',
                'fingerprint': 'Page Fingerprinting',
                'boundary': 'Boundary Detection',
                'label': 'Segment Labeling',
                'table': 'Table Extraction',
                'validate': 'Validation & Assembly'
            };
            const stageName = stageNames[statusData.stage] || statusData.stage;
            statusDetails.textContent = `Current stage: ${stageName}`;
        }

        // Update progress bar based on stage
        const stages = ['ingestion', 'ocr', 'fingerprint', 'boundary', 'label', 'table', 'validate'];
        const currentStageIndex = stages.indexOf(statusData.stage);
        let progressPercent = 0;

        if (currentStageIndex >= 0) {
            progressPercent = ((currentStageIndex + 1) / stages.length) * 100;
        } else if (statusData.status === 'done') {
            progressPercent = 100;
        }

        progressFill.style.width = progressPercent + '%';

        // Show additional details
        if (statusData.pages_total > 0) {
            statusDetails.textContent += ` | Pages: ${statusData.pages_processed}/${statusData.pages_total}`;
        }

        if (statusData.elapsed_seconds) {
            statusDetails.textContent += ` | Elapsed: ${Math.round(statusData.elapsed_seconds)}s`;
        }
    }

    // Function to fetch and display results
    async function fetchAndDisplayResults() {
        try {
            const resultsResponse = await fetch(`/pipeline/result/${jobId}`);
            if (!resultsResponse.ok) {
                throw new Error(`Failed to fetch results: ${resultsResponse.statusText}`);
            }

            const resultsData = await resultsResponse.json();

            statusText.textContent = 'Processing completed!';
            statusDetails.textContent = `Processed ${resultsData.documents.length} documents and ${resultsData.tables.length} tables`;
            progressFill.style.width = '100%';
            progressFill.style.background = '#27ae60';

            // Display results
            displayResults(resultsData);
            resultsSection.classList.remove('hidden');
        } catch (error) {
            console.error('Results fetch error:', error);
            statusText.textContent = 'Error fetching results';
            statusDetails.textContent = error.message;
            progressFill.style.background = '#e74c3c';
        }
    }

    // Function to display results in the UI
    function displayResults(resultsData) {
        let html = '';

        // Documents section
        if (resultsData.documents.length > 0) {
            html += '<h3>📄 Document Boundaries</h3>';
            html += '<table class="results-table">';
            html += '<thead><tr><th>Document ID</th><th>Type</th><th>Pages</th><th>Confidence</th></tr></thead>';
            html += '<tbody>';

            resultsData.documents.forEach(doc => {
                html += `<tr>
                    <td>${doc.doc_id}</td>
                    <td>${doc.doc_type}</td>
                    <td>${doc.start_page} - ${doc.end_page}</td>
                    <td>${(doc.confidence * 100).toFixed(1)}%</td>
                </tr>`;
            });

            html += '</tbody></table>';
        }

        // Tables section
        if (resultsData.tables.length > 0) {
            html += '<h3>📊 Extracted Tables</h3>';
            resultsData.tables.forEach((table, index) => {
                html += `<div class="table-result">
                    <h4>Table ${index + 1} (${table.table_id})</h4>
                    <p><strong>Document:</strong> ${table.doc_id}</p>
                    <p><strong>Type:</strong> ${table.schema_type}</p>
                    <p><strong>Pages:</strong> ${table.page_span[0]} - ${table.page_span[1]}</p>
                    <p><strong>Extraction Method:</strong> ${table.extraction_method}</p>
                    <p><strong>Confidence:</strong> ${(table.confidence * 100).toFixed(1)}%</p>`;

                if (table.reconciliation && table.reconciliation.reconciled !== null) {
                    html += `<p><strong>Reconciliation:</strong> ${table.reconciliation.reconciled ? '✓ Passed' : '✗ Failed'}</p>`;
                }

                if (table.rows && table.rows.length > 0) {
                    html += '<table class="results-table"><thead><tr>';
                    table.columns.forEach(col => {
                        html += `<th>${col}</th>`;
                    });
                    html += '</tr></thead><tbody>';

                    // Show first 10 rows as preview
                    const displayRows = table.rows.slice(0, 10);
                    displayRows.forEach(row => {
                        html += '<tr>';
                        table.columns.forEach((col, colIndex) => {
                            const cell = row.cells.find(c => c.col_idx === colIndex);
                            const text = cell ? cell.text : '';
                            html += `<td>${text}</td>`;
                        });
                        html += '</tr>';
                    });

                    if (table.rows.length > 10) {
                        html += `<tr><td colspan="${table.columns.length}" style="text-align: center; font-style: italic;">... and ${table.rows.length - 10} more rows</td></tr>`;
                    }

                    html += '</tbody></table>';
                }

                html += '</div>';
            });
        }

        // Metrics section
        if (resultsData.metrics) {
            html += '<h3>⚡ Processing Metrics</h3>';
            html += '<table class="results-table">';
            html += '<thead><tr><th>Metric</th><th>Value</th></tr></thead>';
            html += '<tbody>';
            const metrics = resultsData.metrics;
            html += `<tr><td>Wall Clock Time</td><td>${metrics.wall_clock_seconds?.toFixed(2) || 'N/A'} seconds</td></tr>`;
            html += `<tr><td>GPU Minutes</td><td>${metrics.gpu_minutes?.toFixed(2) || 'N/A'} minutes</td></tr>`;
            html += `<tr><td>LLM Calls</td><td>${metrics.llm_calls || 0}</td></tr>`;
            html += `<tr><td>VLM Escalations</td><td>${metrics.vlm_escalations || 0}</td></tr>`;
            html += `<tr><td>Low Confidence Segments</td><td>${metrics.segments_low_confidence || 0}</td></tr>`;
            html += `<tr><td>Unreconciled Tables</td><td>${metrics.tables_unreconciled || 0}</td></tr>`;
            html += '</tbody></table>';
        }

        if (!html.trim()) {
            html = '<p>No results to display.</p>';
        }

        resultsContent.innerHTML = html;
    }
});