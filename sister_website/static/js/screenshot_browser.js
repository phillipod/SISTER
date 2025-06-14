class ScreenshotBrowser {
    constructor(config) {
        this.config = config;
        this.treePane = document.getElementById(config.treePaneId);
        this.previewPane = document.getElementById(config.previewPaneId);
        this.previewImage = document.getElementById(config.previewImageId);
        this.previewPlaceholder = document.getElementById(config.previewPlaceholderId);
        this.submissionInfoPane = document.getElementById(config.submissionInfoPaneId);
        
        this.data = [];
        this.screenshotDataMap = {};

        if (!this.treePane || !this.previewPane || !this.submissionInfoPane) {
            console.error("ScreenshotBrowser: One or more essential container elements are missing.");
            return;
        }

        this.initialize();
    }

    async initialize() {
        try {
            const response = await fetch(this.config.dataUrl);
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            
            this.data = await response.json();
            this.buildScreenshotMap(this.data);
            this.renderTree(this.data);
            
            this.treePane.addEventListener('click', this.handleScreenshotClick.bind(this));
        } catch (error) {
            this.treePane.innerHTML = `<p class="error-message">Could not load data: ${error.message}</p>`;
            console.error('Error initializing browser:', error);
        }
    }

    buildScreenshotMap(data) {
        this.screenshotDataMap = {};
        data.forEach(sub => {
            sub.builds.forEach(build => {
                build.screenshots.forEach(sc => {
                    this.screenshotDataMap[sc.id] = sc;
                });
            });
        });
    }

    renderTree(data) {
        // This method will be slightly different between user and admin,
        // so we can allow for a custom renderer.
        if (this.config.treeRenderer) {
            this.config.treeRenderer(data, this.treePane);
        } else {
            this.defaultTreeRenderer(data);
        }
    }

    defaultTreeRenderer(data) {
        if (data.length === 0) {
            this.treePane.innerHTML = '<p>No submissions found.</p>';
            return;
        }
        // Generic tree rendering logic can be placed here if needed
        // For now, we assume a custom renderer is provided.
    }

    handleScreenshotClick(event) {
        if (!event.target.classList.contains('screenshot-link')) return;
        event.preventDefault();

        const screenshotId = event.target.dataset.screenshotId;
        const screenshotInfo = this.screenshotDataMap[screenshotId];

        if (!screenshotInfo) return;

        document.querySelectorAll('.screenshot-link.active').forEach(link => link.classList.remove('active'));
        event.target.classList.add('active');

        this.showScreenshotPreview(screenshotId);
        this.renderSubmissionInfo(screenshotInfo.submission_details);
    }

    showScreenshotPreview(screenshotId) {
        if(this.previewPlaceholder) this.previewPlaceholder.classList.add('hidden');
        if(this.previewImage) {
            this.previewImage.src = `/admin/screenshot/${screenshotId}`;
            this.previewImage.classList.remove('hidden');
        }
        if(this.previewPane) this.previewPane.classList.add('active');
    }

    renderSubmissionInfo(info) {
        if (!info) {
            this.submissionInfoPane.innerHTML = '';
            return;
        }

        const state = info.is_withdrawn ? 'withdrawn' : info.acceptance_state;
        const stateText = state.charAt(0).toUpperCase() + state.slice(1);

        let actionButtons = '';
        // Action buttons logic can be customized via config if needed
        if (state === 'pending') {
            actionButtons = `
                <a href="/api/accept-license/${info.acceptance_token}" class="btn btn-success">Accept License</a>
                <a href="/api/decline-license/${info.acceptance_token}" class="btn btn-warning">Decline License</a>`;
        } else if (state === 'accepted') {
            actionButtons = `<a href="/api/withdraw-submission/${info.acceptance_token}" class="btn btn-danger">Withdraw Submission</a>`;
        }

        const timelineHtml = info.events.map(event => {
            const timestamp = new Date(event.timestamp).toLocaleString();
            let detailsHtml = '';
            if (event.details) {
                if (event.log_id && event.method === 'Email') {
                    detailsHtml = `(<a href="#" class="view-email-log" data-log-id="${event.log_id}">View Email</a>)`;
                } else if (event.details.ip_address) {
                    detailsHtml = `(IP: ${event.details.ip_address})`;
                }
            }
            return `<li><strong>${event.type}</strong> - ${timestamp} via ${event.method} ${detailsHtml}</li>`;
        }).join('');

        this.submissionInfoPane.innerHTML = `
            <div class="submission-card">
                <div class="submission-header">
                    <h3>Submission Details</h3>
                    <span class="status-badge status-${state}">${stateText}</span>
                </div>
                <div class="submission-body">
                    <p><strong>Email:</strong> ${info.email}</p>
                    <p><strong>Submission ID:</strong> ${info.id}</p>
                    <div class="submission-actions">${actionButtons}</div>
                    <h4>Timeline</h4>
                    <ul class="timeline">${timelineHtml}</ul>
                </div>
            </div>`;
        
        this.attachTimelineEventListeners();
    }

    attachTimelineEventListeners() {
        this.submissionInfoPane.querySelectorAll('.view-email-log').forEach(link => {
            link.addEventListener('click', async (e) => {
                e.preventDefault();
                const logId = e.target.dataset.logId;
                try {
                    // The user browser needs access to the admin log endpoint, which is fine
                    // as the endpoint itself is protected.
                    const response = await fetch(`/admin/api/email_log/${logId}`);
                    if (!response.ok) throw new Error('Failed to fetch email log.');
                    const log = await response.json();
                    const body = log.body_html ? `<div class="email-body-html">${log.body_html}</div>` : `<pre class="email-body-text">${log.body_text}</pre>`;
                    const content = `
                        <p><strong>From:</strong> ${log.from}</p>
                        <p><strong>To:</strong> ${log.to}</p>
                        <p><strong>Subject:</strong> ${log.subject}</p>
                        <hr>
                        ${body}
                    `;
                    this.showModal(`Email Log - ${new Date(log.received_at).toLocaleString()}`, content);
                } catch (error) {
                    this.showModal('Error', `<p class="error-message">${error.message}</p>`);
                }
            });
        });
    }

    showModal(title, content) {
        const modal = document.getElementById(this.config.modalId);
        const modalTitle = modal.querySelector('.modal-title');
        const modalBody = modal.querySelector('.modal-body');
        const modalClose = modal.querySelector('.close-btn');

        if (!modal || !modalTitle || !modalBody || !modalClose) return;

        modalTitle.textContent = title;
        modalBody.innerHTML = content;
        modal.style.display = 'block';

        const closeModal = () => modal.style.display = 'none';
        modalClose.onclick = closeModal;
        window.onclick = (event) => {
            if (event.target == modal) closeModal();
        };
    }
} 