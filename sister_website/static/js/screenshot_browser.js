class ScreenshotBrowser {
    constructor(config) {
        this.config = config;
        this.treePane = document.getElementById(config.treePaneId);
        this.previewPane = document.getElementById(config.previewPaneId);
        this.submissionInfoPane = document.getElementById(config.submissionInfoPaneId);
        
        // This is the specific element where previews (grid or single) will be rendered.
        this.previewContent = document.getElementById(config.previewContentId);

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
        const summary = event.target.closest('summary');
        const link = event.target.closest('a.screenshot-link');

        if (link) {
            event.preventDefault();
            this.handleScreenshotClick(link);
            return;
        }

        if (summary) {
            // Let the default <details> toggle happen.
            // Only act if it's a group summary.
            if (summary.dataset.groupScreenshots) {
                this.handleGroupClick(summary, !event.isTrusted);
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
    
    handleGroupClick(summary, isProgrammatic = false) {
        this.setActiveNode(summary);
        const idsCsv = summary.dataset.groupScreenshots;
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
        this.previewContent.innerHTML = `
            <img id="preview-image" alt="Screenshot Preview" src="/admin/screenshot/${screenshotId}?t=${Date.now()}" />
        `;
    }

    renderGridPreview(ids, isProgrammatic) {
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

            if (isProgrammatic) {
                img.src = `/admin/screenshot/${id}?t=${Date.now()}`;
            } else {
                img.dataset.src = `/admin/screenshot/${id}?t=${Date.now()}`;
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
        
        let resendButtonHtml = '';
        if (info.acceptance_state === 'pending' && !info.is_withdrawn) {
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

        this.submissionInfoPane.innerHTML = `
            <div class="info-card">
                <p><strong>License Status:</strong> ${statusHtml}</p>
                <p><strong>Email:</strong> ${info.email}</p>
                ${resendButtonHtml}
                <h4>Timeline</h4>
                <ul class="timeline">${timelineHtml}</ul>
            </div>`;
        
        this.attachInfoEventListeners();
    }
    
    attachInfoEventListeners() {
        this.submissionInfoPane.querySelectorAll('.resend-btn').forEach(btn => {
            btn.addEventListener('click', this.handleResendConsent.bind(this));
        });
        this.submissionInfoPane.querySelectorAll('.view-log').forEach(link => {
            link.addEventListener('click', this.handleViewLog.bind(this));
        });
    }
    
    async handleResendConsent(e) {
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
        e.preventDefault();
        const logId = e.target.dataset.logId;
        const logType = e.target.dataset.logType; // 'email' or 'link'
        
        try {
            const response = await fetch(`/admin/api/${logType}_log/${logId}`);
            if (!response.ok) throw new Error(`Failed to fetch ${logType} log.`);
            const log = await response.json();
            
            let content = '';
            if (logType === 'email') {
                const body = log.body_html ? `<div class="email-body-html">${log.body_html}</div>` : `<pre class="email-body-text">${log.body_text || ''}</pre>`;
                content = `
                    <p><strong>From:</strong> ${log.from_address}</p>
                    <p><strong>To:</strong> ${log.to_address}</p>
                    <p><strong>Subject:</strong> ${log.subject}</p><hr>${body}`;
            } else { // link log
                content = `<ul>
                    <li><strong>IP Address:</strong> ${log.ip_address}</li>
                    <li><strong>User Agent:</strong> ${log.user_agent}</li>
                    <li><strong>Clicked At:</strong> ${new Date(log.clicked_at).toLocaleString()}</li>
                </ul>`;
            }
            this.showModal(`${logType.charAt(0).toUpperCase() + logType.slice(1)} Details`, content);
        } catch (error) {
            this.showModal('Error', `<p class="error-message">${error.message}</p>`);
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

        const closeModal = () => modal.remove();
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
} 