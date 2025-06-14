document.addEventListener('DOMContentLoaded', () => {
    const treePane = document.getElementById('tree-pane');
    const previewPane = document.getElementById('preview-pane');
    const previewImage = document.getElementById('preview-image');
    const previewPlaceholder = document.getElementById('preview-placeholder');
    const submissionInfoPane = document.getElementById('submission-info');
    let submissionsData = [];

    // Fetches submission data and initializes the browser
    async function initializeBrowser() {
        try {
            const response = await fetch('/api/me/submissions_data');
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            submissionsData = await response.json();
            renderTree();
        } catch (error) {
            treePane.innerHTML = '<p class="error-message">Could not load your submissions. Please try again later.</p>';
            console.error('Error fetching submissions:', error);
        }
    }

    // Renders the entire submission tree
    function renderTree() {
        if (submissionsData.length === 0) {
            treePane.innerHTML = '<p>You have no submissions.</p>';
            return;
        }

        const treeHtml = submissionsData.map(sub => `
            <details class="submission-node" open>
                <summary>
                    Submission (${new Date(sub.created_at).toLocaleDateString()})
                    <span class="status-badge status-${sub.acceptance_state}">${sub.acceptance_state}</span>
                </summary>
                <ul>
                    ${sub.builds.map(build => `
                        <li>
                            <details class="build-node">
                                <summary>${build.platform} - ${build.type}</summary>
                                <ul>
                                    ${build.screenshots.map(sc => `
                                        <li>
                                            <a href="#" class="screenshot-link" data-screenshot-id="${sc.id}" data-submission-id="${sub.id}">
                                                ${sc.filename}
                                            </a>
                                        </li>
                                    `).join('')}
                                </ul>
                            </details>
                        </li>
                    `).join('')}
                </ul>
            </details>
        `).join('');

        treePane.innerHTML = treeHtml;
    }

    // Handles clicks on screenshot links
    function handleScreenshotClick(event) {
        if (!event.target.classList.contains('screenshot-link')) return;
        event.preventDefault();

        const screenshotId = event.target.dataset.screenshotId;
        const submissionId = event.target.dataset.submissionId;
        
        // Highlight selected screenshot
        document.querySelectorAll('.screenshot-link.active').forEach(link => link.classList.remove('active'));
        event.target.classList.add('active');

        // Show preview and details
        showScreenshotPreview(screenshotId);
        showSubmissionDetails(submissionId);
    }

    // Displays the selected screenshot image
    function showScreenshotPreview(screenshotId) {
        previewPlaceholder.classList.add('hidden');
        previewImage.src = `/admin/screenshot/${screenshotId}`; // Reuses the admin image endpoint
        previewImage.classList.remove('hidden');
        previewPane.classList.add('active');
    }

    // Displays the details for the submission associated with the screenshot
    function showSubmissionDetails(submissionId) {
        const submission = submissionsData.find(sub => sub.id === submissionId);
        if (!submission) return;
        
        let actionButtons = '';
        if (submission.acceptance_state === 'pending') {
            actionButtons = `
                <a href="/api/accept-license/${submission.acceptance_token}" class="btn btn-success">Accept License</a>
                <a href="/api/decline-license/${submission.acceptance_token}" class="btn btn-warning">Decline License</a>
            `;
        } else if (submission.acceptance_state === 'accepted' && !submission.is_withdrawn) {
            actionButtons = `<a href="/api/withdraw-submission/${submission.acceptance_token}" class="btn btn-danger">Withdraw Submission</a>`;
        }

        const emailLogsHtml = submission.email_logs.length > 0
            ? `<ul>${submission.email_logs.map(log => `<li>${new Date(log.received_at).toLocaleString()} - ${log.subject}</li>`).join('')}</ul>`
            : '<p>No email logs found.</p>';

        const linkLogsHtml = submission.link_logs.length > 0
            ? `<ul>${submission.link_logs.map(log => `<li>${new Date(log.clicked_at).toLocaleString()} - From IP: ${log.ip_address}</li>`).join('')}</ul>`
            : '<p>No link logs found.</p>';

        submissionInfoPane.innerHTML = `
            <div class="submission-card">
                <div class="submission-header">
                    <h3>Submission Details</h3>
                    <span class="status-badge status-${submission.acceptance_state}">${submission.acceptance_state}</span>
                </div>
                <div class="submission-body">
                    <p><strong>Submitted:</strong> ${new Date(submission.created_at).toLocaleString()}</p>
                    ${submission.is_withdrawn ? '<p><strong>Status:</strong> Withdrawn</p>' : ''}
                    
                    <div class="submission-actions">
                        ${actionButtons}
                    </div>
                    
                    <div class="submission-logs">
                        <h4>Email Logs</h4>
                        ${emailLogsHtml}
                        <h4>Link Click Logs</h4>
                        ${linkLogsHtml}
                    </div>
                </div>
            </div>
        `;
    }

    // Initialize the browser
    initializeBrowser();

    // Add event listener for clicks on the tree
    treePane.addEventListener('click', handleScreenshotClick);
}); 