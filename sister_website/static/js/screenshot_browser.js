class ScreenshotBrowser {
    constructor(config) {
        this.config = config;
        this.treePane = document.getElementById(config.treePaneId);
        this.previewPane = document.getElementById(config.previewPaneId);
        this.submissionInfoPane = document.getElementById(config.submissionInfoPaneId);
        
        // This is the specific element where previews (grid or single) will be rendered.
        this.previewContent = document.getElementById(config.previewContentId);

        // API endpoints can now be configured
        this.api = {
            logAccessToken: config.logAccessTokenUrl, // e.g., '/api/log-access-token/{log_id}'
            emailLog: config.emailLogUrl,             // e.g., '/admin/api/email_log/{log_id}'
            linkLog: config.linkLogUrl,               // e.g., '/admin/api/link_log/{log_id}'
            screenshotImage: config.screenshotImageUrl  // e.g., '/admin/screenshot/{sc_id}'
        };

        if (!this.treePane || !this.previewPane || !this.submissionInfoPane || !this.previewContent) {
            console.error("ScreenshotBrowser: One or more essential container elements are missing.");
            return;
        }
        
        this.data = null; // To store the raw data from the API
        this.screenshotDataMap = {}; // For quick lookup of screenshot details
        this.csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
    }

    async initialize(initialId = null) {
        try {
            const response = await fetch(this.config.dataUrl);
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            
            this.data = await response.json();
            
            // Allow for a custom map builder, otherwise use default
            if (this.config.mapBuilder) {
                this.screenshotDataMap = this.config.mapBuilder(this.data);
            } else {
                this.buildScreenshotMap(this.data);
            }
            
            this.renderTree();
            this.treePane.addEventListener('click', this.handleTreeClick.bind(this));
            
            if (initialId) {
                this.scrollToId(initialId);
            }
        } catch (error) {
            this.previewPane.innerHTML = `<p class="error-message">Could not load data: ${error.message}</p>`;
            console.error('Error initializing browser:', error);
        }
    }

    // Default map builder, suitable for the user submissions API structure
    buildScreenshotMap(data) {
        data.forEach(sub => {
            sub.builds.forEach(build => {
                build.screenshots.forEach(sc => {
                    this.screenshotDataMap[sc.id] = sc;
                });
            });
        });
    }

    renderTree() {
        if (!this.config.treeRenderer) {
            console.error("ScreenshotBrowser: No treeRenderer function provided in config.");
            return;
        }
        this.config.treeRenderer(this.data, this.treePane);
    }
    
    handleTreeClick(event) {
        const link = event.target.closest('a.screenshot-link');
        if (link) {
            event.preventDefault();
            this.handleScreenshotClick(link);
            return;
        }

        // The user might click the summary, the span, or the twisty.
        // We find the parent summary first, then look for the span with data inside it.
        const summary = event.target.closest('summary');
        if (summary) {
            const dataSpan = summary.querySelector('span[data-group-screenshots]');
            if (dataSpan) {
                // Let the default <details> toggle happen.
                // Pass the span with the data to the handler.
                this.handleGroupClick(dataSpan, !event.isTrusted);
            }
        }
    }

    handleScreenshotClick(link) {
        this.setActiveNode(link);
        const screenshotId = link.dataset.screenshotId;
        const screenshotInfo = this.screenshotDataMap[screenshotId];
        
        if (!screenshotInfo) {
            console.error(`Could not find data for screenshot ID ${screenshotId}`);
            return;
        }
        
        this.renderSinglePreview(screenshotId);
        this.renderSubmissionInfo(screenshotInfo.submission_details || screenshotInfo);
    }
    
    handleGroupClick(dataElement, isProgrammatic = false) {
        this.setActiveNode(dataElement);
        const idsCsv = dataElement.dataset.groupScreenshots;
        if (!idsCsv) return;

        const ids = idsCsv.split(',');
        this.renderGridPreview(ids, isProgrammatic);

        if (ids.length > 0) {
            const firstScreenshot = this.screenshotDataMap[ids[0]];
            if (firstScreenshot) {
                 this.renderSubmissionInfo(firstScreenshot.submission_details || firstScreenshot);
            }
        }
    }

    renderSinglePreview(screenshotId) {
        this.previewContent.classList.remove('has-grid');
        const imageUrl = this.api.screenshotImage.replace('{sc_id}', screenshotId);
        this.previewContent.innerHTML = `
            <img id="preview-image" alt="Screenshot Preview" src="${imageUrl}?t=${Date.now()}" />
        `;
    }

    renderGridPreview(ids, isProgrammatic) {
        this.previewContent.classList.add('has-grid');
        const grid = document.createElement('div');
        grid.id = 'preview-grid';
        grid.classList.add('preview-grid');

        ids.forEach(id => {
            const img = document.createElement('img');
            img.classList.add('preview-grid-img');
            img.dataset.screenshotId = id;
            
            // When a tile is clicked, trigger the corresponding tree link click
            img.addEventListener('click', () => {
                const link = this.treePane.querySelector(`a[data-screenshot-id="${id}"]`);
                if (link) {
                    link.scrollIntoView({behavior: 'smooth', block: 'center'});
                    link.click();
                }
            });

            const imageUrl = this.api.screenshotImage.replace('{sc_id}', id);
            if (isProgrammatic) {
                img.src = `${imageUrl}?t=${Date.now()}`;
            } else {
                img.dataset.src = `${imageUrl}?t=${Date.now()}`;
                img.loading = 'lazy';
            }
            grid.appendChild(img);
        });
        
        this.previewContent.innerHTML = '';
        this.previewContent.appendChild(grid);

        if (!isProgrammatic) {
            this.initLazyLoad(grid);
        }
    }
    
    renderSubmissionInfo(info) {
        if (!info) {
            this.submissionInfoPane.innerHTML = '';
            return;
        }

        const state = info.is_withdrawn ? 'withdrawn' : info.acceptance_state;
        const stateText = state.charAt(0).toUpperCase() + state.slice(1);
        
        let statusHtml = `<span class="status-badge status-${state}">${stateText}</span>`;
        if (info.is_withdrawn && state !== 'withdrawn') {
            statusHtml += ` <span class="status-badge status-withdrawn">Withdrawn</span>`;
        }
        
        // Add action buttons based on the submission state
        let actionButtonsHtml = '';
        if (this.config.userCanManage) { // A new config flag to enable this feature
            if (state === 'pending') {
                actionButtonsHtml = `
                    <div class="submission-actions">
                        <button class="btn btn-success btn-sm action-btn" data-action="accept" data-token="${info.acceptance_token}">Accept License</button>
                        <button class="btn btn-warning btn-sm action-btn" data-action="decline" data-token="${info.acceptance_token}">Decline License</button>
                    </div>`;
            } else if (state === 'accepted') {
                actionButtonsHtml = `
                    <div class="submission-actions">
                        <button class="btn btn-danger btn-sm action-btn" data-action="withdraw" data-token="${info.acceptance_token}">Withdraw Submission</button>
                    </div>`;
            }
        }
        
        let resendButtonHtml = '';
        if (this.config.userCanManage && info.acceptance_state === 'pending' && !info.is_withdrawn) {
            resendButtonHtml = `
                <div class="resend-section">
                    <button class="btn btn-secondary btn-sm resend-btn" data-submission-id="${info.id}">Resend Consent</button>
                    <span class="resend-status"></span>
                </div>`;
        }
        
        const timelineHtml = (info.events || []).map(event => {
            const timestamp = new Date(event.timestamp).toLocaleString();
            let detailsHtml = '';
            if (event.log_id && (event.method === 'Email' || event.details?.subject)) {
                 detailsHtml = `(<a href="#" class="view-log" data-log-type="email" data-log-id="${event.log_id}">View Email</a>)`;
            } else if (event.log_id && (event.method === 'Link' || event.details?.ip_address)) {
                 detailsHtml = `(<a href="#" class="view-log" data-log-type="link" data-log-id="${event.log_id}">Details</a>)`;
            }
            return `<li><strong>${event.type}</strong> - ${timestamp} via ${event.method || 'N/A'} ${detailsHtml}</li>`;
        }).join('');

        const container = document.createElement('div');
        container.className = 'info-card';
        container.innerHTML = `
            <p><strong>License Status:</strong> ${statusHtml}</p>
            <p><strong>Email:</strong> ${info.email}</p>
            ${actionButtonsHtml}
            ${resendButtonHtml}
            <h4>Timeline</h4>
            <ul class="timeline">${timelineHtml}</ul>
        `;

        this.submissionInfoPane.innerHTML = '';
        this.submissionInfoPane.appendChild(container);

        // Attach event listeners for any actions within the info pane
        this.submissionInfoPane.addEventListener('click', this.handleViewLog.bind(this));
        this.submissionInfoPane.addEventListener('click', this.handleLicenseAction.bind(this));
        this.submissionInfoPane.addEventListener('click', this.handleResendConsent.bind(this));
    }
    
    async handleResendConsent(e) {
        if (!e.target.matches('.resend-btn')) return;

        const button = e.target;
        const submissionId = button.dataset.submissionId;
        const statusSpan = button.parentElement.querySelector('.resend-status');

        if (!confirm('Are you sure you want to resend the consent email for this submission?')) return;

        button.disabled = true;
        statusSpan.textContent = 'Sending...';

        try {
            const response = await fetch(`/admin/api/resend-consent/${submissionId}`, {
                method: 'POST',
                headers: { 'X-CSRF-Token': this.csrfToken }
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Unknown error');
            statusSpan.textContent = 'Sent!';
        } catch (error) {
            statusSpan.textContent = `Error: ${error.message}`;
        } finally {
             setTimeout(() => {
                if(statusSpan) statusSpan.textContent = '';
                button.disabled = false;
            }, 5000);
        }
    }
    
    async handleViewLog(e) {
        if (!e.target.matches('a.view-log')) return;

        console.log('handleViewLog triggered.', e);
        const link = e.target.closest('a.view-log');
        console.log('Found link element:', link);
        if (!link) return;
        
        e.preventDefault();
        const logId = link.dataset.logId;
        const logType = link.dataset.logType; // 'email' or 'link'
        console.log(`Log type: ${logType}, Log ID: ${logId}`);
        
        try {
            if (logType === 'email') {
                console.log('Processing email log...');
                const tokenUrl = this.api.logAccessToken.replace('{log_id}', logId);
                const logUrl = this.api.emailLog.replace('{log_id}', logId);

                // Fetch the access token and log metadata in parallel for efficiency
                const [tokenRes, logRes] = await Promise.all([
                    fetch(tokenUrl),
                    fetch(logUrl)
                ]);
                console.log('Token response:', tokenRes, 'Log response:', logRes);

                if (!tokenRes.ok) throw new Error('Could not get access token.');
                if (!logRes.ok) throw new Error('Could not get log details.');
                
                const { token } = await tokenRes.json();
                const log = await logRes.json();
                console.log('Email log data:', log);
                
                const viewerUrl = `https://logviewer.sto-tools.org/log/${logId}?token=${token}`;
                const content = `
                    <p><strong>From:</strong> ${log.from_address || log.from}</p>
                    <p><strong>To:</strong> ${log.to_address || log.to}</p>
                    <p><strong>Subject:</strong> ${log.subject}</p><hr>
                    <iframe class="email-body-iframe" src="${viewerUrl}" sandbox="allow-same-origin"></iframe>`;
                
                console.log('Showing modal with email content.');
                this.showModal('Email Details', content);

            } else if (logType === 'link') {
                console.log('Processing link log...');
                const logUrl = this.api.linkLog.replace('{log_id}', logId);
                const logRes = await fetch(logUrl);
                console.log('Link log response:', logRes);

                if (!logRes.ok) throw new Error('Could not get log details.');
                const log = await logRes.json();
                console.log('Link log data:', log);
                
                const content = `
                    <p><strong>IP Address:</strong> ${log.ip_address || 'N/A'}</p>
                    <p><strong>User Agent:</strong> ${log.user_agent || 'N/A'}</p>
                    <p><strong>Clicked At:</strong> ${new Date(log.clicked_at).toLocaleString()}</p>`;
                
                console.log('Showing modal with link content.');
                this.showModal('Link Click Details', content);
            }
        } catch (error) {
            console.error('Error fetching log details:', error);
            this.showModal('Error', `<p>Could not load log details: ${error.message}</p>`);
        }
    }

    showModal(title, content) {
        const existingModal = document.getElementById('details-modal');
        if (existingModal) existingModal.remove();

        const modal = document.createElement('div');
        modal.id = 'details-modal';
        modal.className = 'modal-backdrop';
        modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h2>${title}</h2>
                    <span class="close-btn">&times;</span>
                </div>
                <div class="modal-body">${content}</div>
            </div>`;
        
        document.body.appendChild(modal);
        // Ensure modal is visible even if default CSS hides it (e.g., display: none)
        modal.style.display = 'flex';

        const closeModal = () => {
            modal.remove();
        };
        modal.querySelector('.close-btn').onclick = closeModal;
        modal.onclick = (event) => {
            if (event.target === modal) closeModal();
        };
    }

    initLazyLoad(container) {
        const lazyImages = [].slice.call(container.querySelectorAll("img[data-src]"));
        if (!lazyImages.length || !('IntersectionObserver' in window)) return;
        
        const observer = new IntersectionObserver((entries, obs) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const img = entry.target;
                    img.src = img.dataset.src;
                    img.removeAttribute('data-src');
                    obs.unobserve(img);
                }
            });
        }, { root: null, rootMargin: '200px', threshold: 0.01 });

        lazyImages.forEach(img => observer.observe(img));
    }
    
    scrollToId(id) {
        const element = this.treePane.querySelector(`[data-build-id="${id}"]`);
        if (element) {
            element.scrollIntoView({ behavior: 'smooth', block: 'start' });
            element.classList.add('highlight');
            
            const summary = element.querySelector('summary');
            if (summary) {
                element.open = true;
                summary.click();
            }
            
            setTimeout(() => element.classList.remove('highlight'), 3000);
        }
    }

    setActiveNode(element) {
        this.treePane.querySelectorAll('.active-node').forEach(node => node.classList.remove('active-node'));
        if (element) {
             const parent = element.closest('details, li');
             if(parent) parent.classList.add('active-node');
        }
    }

    forceRerender() {
        // This function will re-fetch data and completely re-render the component
        this.previewContent.innerHTML = '';
        this.submissionInfoPane.innerHTML = '';
        this.initialize();
    }

    async handleLicenseAction(e) {
        if (!e.target.matches('.action-btn')) return;

        const button = e.target;
        const action = button.dataset.action;
        const token = button.dataset.token;
        const urlMap = {
            accept: `/api/accept-license/${token}`,
            decline: `/api/decline-license/${token}`,
            withdraw: `/api/withdraw-submission/${token}`
        };

        if (!urlMap[action] || !confirm(`Are you sure you want to ${action} this submission's license?`)) {
            return;
        }

        button.disabled = true;
        button.textContent = 'Processing...';

        try {
            const response = await fetch(urlMap[action], {
                method: 'POST', // Use POST to align with API expectations for actions
                headers: { 'X-CSRF-Token': this.csrfToken, 'Content-Type': 'application/json' },
                body: JSON.stringify({ source: 'dashboard' })
            });
            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.message || `Failed to ${action}.`);
            }
            
            // Re-render the entire component to reflect the new state
            this.forceRerender();

        } catch (error) {
            alert(`An error occurred: ${error.message}`);
            button.disabled = false;
            button.textContent = action.charAt(0).toUpperCase() + action.slice(1);
        }
    }
} 