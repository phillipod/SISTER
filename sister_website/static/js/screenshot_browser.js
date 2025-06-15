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
        
        // Set up common UI elements if enabled
        if (config.setupUI !== false) {
            this.setupCommonUI();
        }
    }

    setupCommonUI() {
        // Set up filters, popup, and drag-and-drop
        this.filters = {
            platform: document.getElementById('platform-filter'),
            type: document.getElementById('type-filter'),
            accepted: document.getElementById('accepted-filter')
        };

        this.popup = document.getElementById('tree-options-popup');
        this.openPopupBtn = document.getElementById('tree-options-btn');
        this.toggleFiltersBtn = document.getElementById('toggle-filters-btn');
        this.filtersContainer = document.querySelector('.screenshot-filters');
        this.groupByFieldset = document.getElementById('group-by-fieldset');

        // Set up event listeners
        this.setupEventListeners();
    }

    setupEventListeners() {
        // Filter change listeners
        if (this.filters) {
            Object.values(this.filters).forEach(filter => {
                if (filter) {
                    filter.addEventListener('change', () => this.renderTree());
                }
            });
        }

        // Toggle filters button
        if (this.toggleFiltersBtn && this.filtersContainer) {
            this.toggleFiltersBtn.addEventListener('click', () => {
                this.filtersContainer.classList.toggle('hidden');
            });
        }

        // Popup handling
        if (this.openPopupBtn && this.popup) {
            this.openPopupBtn.addEventListener('click', (event) => {
                event.stopPropagation();
                this.popup.classList.toggle('active');
            });

            document.addEventListener('click', (event) => {
                if (!this.popup.contains(event.target) && !this.openPopupBtn.contains(event.target)) {
                    this.popup.classList.remove('active');
                }
            });

            this.popup.addEventListener('click', (event) => {
                event.stopPropagation();
            });
        }

        // Set up drag-and-drop for grouping if SortableJS is available
        if (typeof Sortable !== 'undefined' && this.groupByFieldset) {
            new Sortable(this.groupByFieldset, {
                animation: 150,
                ghostClass: 'sortable-ghost',
                onEnd: () => this.renderTree()
            });

            // Add listeners to checkboxes to re-render on check/uncheck
            this.groupByFieldset.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
                checkbox.addEventListener('change', () => this.renderTree());
            });
        }
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

    // Default map builder, suitable for flat screenshot data structure
    buildScreenshotMap(data) {
        if (this.config.mapBuilder) {
            this.screenshotDataMap = this.config.mapBuilder(data);
        } else {
            const map = {};
            if (Array.isArray(data) && data.length > 0) {
                // Check if this is flat data (screenshots) or nested data (submissions)
                if (data[0].builds) {
                    // Nested structure (legacy support)
                    data.forEach(sub => {
                        sub.builds.forEach(build => {
                            build.screenshots.forEach(sc => {
                                map[sc.id] = sc;
                            });
                        });
                    });
                } else {
                    // Flat structure (current)
                    data.forEach(sc => {
                        map[sc.id] = sc;
                    });
                }
            }
            this.screenshotDataMap = map;
        }
    }

    renderTree() {
        const renderer = this.config.treeRenderer || this.defaultTreeRenderer.bind(this);
        renderer(this.data, this.treePane);
    }

    defaultTreeRenderer(data, treePane) {
        if (!this.filters) {
            console.error("ScreenshotBrowser: Cannot use default tree renderer without filters setup.");
            return;
        }

        const platformFilter = this.filters.platform.value;
        const typeFilter = this.filters.type.value;
        const acceptedFilter = this.filters.accepted.value;

        // Capture current open/closed state before clearing
        const openStates = {};
        const captureOpenStates = (element, path = []) => {
            const details = element.querySelectorAll('details');
            details.forEach(detail => {
                const summary = detail.querySelector('summary > span');
                if (summary) {
                    const text = summary.textContent.trim();
                    const currentPath = [...path, text];
                    const pathKey = currentPath.join('|');
                    openStates[pathKey] = detail.open;
                    captureOpenStates(detail, currentPath);
                }
            });
        };
        captureOpenStates(treePane);

        treePane.innerHTML = '';
        
        const filteredData = data.filter(sc => {
            const platformMatch = platformFilter === 'all' || sc.platform === platformFilter;
            const typeMatch = typeFilter === 'all' || sc.type === typeFilter;
            const acceptedMatch = acceptedFilter === 'all' || sc.acceptance_state === acceptedFilter;
            return platformMatch && typeMatch && acceptedMatch;
        });

        if (filteredData.length === 0) {
            const noResultsMessage = this.config.noResultsMessage || 'No screenshots match the current filters.';
            treePane.innerHTML = `<p>${noResultsMessage}</p>`;
            return;
        }

        const groupOrder = [];
        if (this.groupByFieldset) {
            const groupByCheckboxes = this.groupByFieldset.querySelectorAll('input[type="checkbox"]');
            groupByCheckboxes.forEach(checkbox => {
                if (checkbox.checked) {
                    groupOrder.push(checkbox.dataset.groupKey);
                }
            });
        }
        groupOrder.push('date');

        const hierarchicalData = {};
        filteredData.forEach(sc => {
            let currentLevel = hierarchicalData;
            groupOrder.forEach(key => {
                const value = sc[key] || 'Unknown';
                if (!currentLevel[value]) {
                    currentLevel[value] = {};
                }
                currentLevel = currentLevel[value];
            });
            
            if (!currentLevel[sc.submission_id]) {
                currentLevel[sc.submission_id] = [];
            }
            currentLevel[sc.submission_id].push(sc);
        });

        const createDetails = (summaryText, parentElement, allScreenshots, depth = 0, parentPath = []) => {
            const details = document.createElement('details');
            const currentPath = [...parentPath, summaryText];
            const pathKey = currentPath.join('|');
            
            // Restore previous open state if available, otherwise default based on depth
            if (pathKey in openStates) {
                details.open = openStates[pathKey];
            } else {
                details.open = depth < 3; // Default: open for shallow levels, closed for deep ones
            }
            
            details.classList.add(`tree-depth-${depth}`);
            const summary = document.createElement('summary');
            const summarySpan = document.createElement('span');
            summarySpan.textContent = summaryText;

            if (allScreenshots && allScreenshots.length > 0) {
                summarySpan.dataset.groupScreenshots = allScreenshots.map(sc => sc.id).join(',');
            }

            summary.appendChild(summarySpan);
            details.appendChild(summary);
            parentElement.appendChild(details);
            return { element: details, path: currentPath };
        };

        const renderNode = (node, parentElement, depth = 0, parentPath = []) => {
            for (const key in node) {
                const childNode = node[key];
                
                const isSubmissionContainer = Object.values(childNode).every(val => Array.isArray(val));

                if (isSubmissionContainer) {
                    const dateDetailsResult = createDetails(key, parentElement, this.getAllScreenshots(childNode), depth, parentPath);
                     for (const subId in childNode) {
                        const subScreenshots = childNode[subId];
                        if (subScreenshots.length > 0) {
                            const firstSc = subScreenshots[0];
                            const subLabel = `Submission ${firstSc.submission_id.substring(0, 8)}`;
                            const subDetailsResult = createDetails(subLabel, dateDetailsResult.element, subScreenshots, depth + 1, dateDetailsResult.path);
                            subDetailsResult.element.dataset.buildId = firstSc.build_id;

                            const scUl = document.createElement('ul');
                            scUl.classList.add(`tree-depth-${depth + 2}`);
                            subScreenshots.forEach(sc => {
                                const scLi = document.createElement('li');
                                const link = document.createElement('a');
                                link.href = '#';
                                link.className = 'screenshot-link';
                                link.textContent = sc.filename;
                                link.dataset.screenshotId = sc.id;
                                scLi.appendChild(link);
                                scUl.appendChild(scLi);
                            });
                            subDetailsResult.element.appendChild(scUl);
                        }
                    }
                } else {
                    const detailsResult = createDetails(key, parentElement, this.getAllScreenshots(childNode), depth, parentPath);
                    renderNode(childNode, detailsResult.element, depth + 1, detailsResult.path);
                }
            }
        };

        renderNode(hierarchicalData, treePane);
    }
    
    getAllScreenshots(node) {
        let screenshots = [];
        for (const key in node) {
            const child = node[key];
            if (Array.isArray(child)) {
                screenshots = screenshots.concat(child);
            } else {
                screenshots = screenshots.concat(this.getAllScreenshots(child));
            }
        }
        return screenshots;
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

        // Only show submission info if all screenshots belong to the same submission
        if (ids.length > 0) {
            const uniqueSubmissions = new Set();
            ids.forEach(id => {
                const screenshot = this.screenshotDataMap[id];
                if (screenshot) {
                    const submissionId = screenshot.submission_id || 
                                       (screenshot.submission_details && screenshot.submission_details.id);
                    if (submissionId) {
                        uniqueSubmissions.add(submissionId);
                    }
                }
            });

            // Only show submission info if there's exactly one unique submission
            if (uniqueSubmissions.size === 1) {
                const firstScreenshot = this.screenshotDataMap[ids[0]];
                if (firstScreenshot) {
                    this.renderSubmissionInfo(firstScreenshot.submission_details || firstScreenshot);
                }
            } else {
                // Clear submission info for multi-submission groups
                this.submissionInfoPane.innerHTML = '';
            }
        }
    }

    renderSinglePreview(screenshotId) {
        this.hideSubmissionPopup(); // Clear any existing popup
        this.previewContent.classList.remove('has-grid');
        const imageUrl = this.api.screenshotImage.replace('{sc_id}', screenshotId);
        this.previewContent.innerHTML = `
            <img id="preview-image" alt="Screenshot Preview" src="${imageUrl}?t=${Date.now()}" />
        `;
    }

    renderGridPreview(ids, isProgrammatic) {
        this.hideSubmissionPopup(); // Clear any existing popup
        this.previewContent.classList.add('has-grid');
        const grid = document.createElement('div');
        grid.id = 'preview-grid';
        grid.classList.add('preview-grid');

        ids.forEach(id => {
            const img = document.createElement('img');
            img.classList.add('preview-grid-img');
            img.dataset.screenshotId = id;
            
            // When a tile is clicked, scroll to build and then select the screenshot
            img.addEventListener('click', () => {
                const screenshotInfo = this.screenshotDataMap[id];
                if (screenshotInfo) {
                    console.log('Screenshot info:', screenshotInfo);
                    
                    // Extract build_id from screenshot data - try multiple possible locations
                    const buildId = screenshotInfo.build_id || 
                                   (screenshotInfo.submission_details && screenshotInfo.submission_details.build_id) ||
                                   screenshotInfo.submission_id; // fallback to submission_id
                    
                    console.log('Build ID found:', buildId);
                    
                    if (buildId) {
                        // First find the screenshot link to determine its build location
                        const link = this.treePane.querySelector(`a[data-screenshot-id="${id}"]`);
                        if (link) {
                            // Find the submission details element that contains this screenshot
                            const submissionDetails = link.closest('details[data-build-id]');
                            if (submissionDetails) {
                                console.log('Found submission details:', submissionDetails);
                                
                                // Expand all parent details elements
                                let currentElement = submissionDetails;
                                while (currentElement) {
                                    if (currentElement.tagName === 'DETAILS') {
                                        currentElement.open = true;
                                    }
                                    currentElement = currentElement.parentElement.closest('details');
                                }
                                
                                // Scroll to the submission and highlight it
                                submissionDetails.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                submissionDetails.classList.add('highlight');
                                
                                setTimeout(() => {
                                    submissionDetails.classList.remove('highlight');
                                    // Select the specific screenshot
                                    link.click();
                                }, 1000);
                            } else {
                                // Fallback: just click the link directly
                                link.click();
                            }
                        }
                    } else {
                        console.log('No build ID found, using fallback');
                        // Fallback to original behavior if no build_id found
                        const link = this.treePane.querySelector(`a[data-screenshot-id="${id}"]`);
                        if (link) {
                            link.scrollIntoView({behavior: 'smooth', block: 'center'});
                            link.click();
                        }
                    }
                } else {
                    console.log('No screenshot info found for ID:', id);
                }
            });

            // Add mouseover popup for submission info
            let popupTimeout;
            
            img.addEventListener('mouseover', (e) => {
                clearTimeout(popupTimeout);
                popupTimeout = setTimeout(() => {
                    this.showSubmissionPopup(e, id);
                }, 500); // Longer delay to let CSS hover animation show first
            });

            img.addEventListener('mouseout', () => {
                clearTimeout(popupTimeout);
                this.hideSubmissionPopup();
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

    showSubmissionPopup(e, screenshotId) {
        console.log('showSubmissionPopup called with ID:', screenshotId);
        const screenshotInfo = this.screenshotDataMap[screenshotId];
        if (!screenshotInfo) {
            console.log('No screenshot info found for ID:', screenshotId);
            return;
        }

        // Remove any existing popup
        this.hideSubmissionPopup();

        const popup = document.createElement('div');
        popup.id = 'submission-popup';
        popup.className = 'submission-popup';
        
        const info = screenshotInfo.submission_details || screenshotInfo;
        const state = info.is_withdrawn ? 'withdrawn' : info.acceptance_state;
        const stateText = state.charAt(0).toUpperCase() + state.slice(1);
        
        let statusHtml = `<span class="status-badge status-${state}">${stateText}</span>`;
        if (info.is_withdrawn && state !== 'withdrawn') {
            statusHtml += ` <span class="status-badge status-withdrawn">Withdrawn</span>`;
        }

        popup.innerHTML = `
            <div class="popup-content">
                <p><strong>Email:</strong> ${info.email}</p>
                <p><strong>Status:</strong> ${statusHtml}</p>
                <p><strong>Submission:</strong> ${info.id ? String(info.id).substring(0, 8) : 'N/A'}...</p>
                <p><strong>Screenshot:</strong> ${screenshotInfo.filename}</p>
            </div>
        `;

        document.body.appendChild(popup);
        console.log('Popup added to DOM:', popup);

        // Position the popup near the mouse cursor
        const rect = e.target.getBoundingClientRect();
        const popupRect = popup.getBoundingClientRect();
        
        let left = rect.right + 10; // Position to the right of the image
        let top = rect.top + rect.height / 2 - popupRect.height / 2; // Center vertically

        // Adjust position if popup would go off screen
        if (left + popupRect.width > window.innerWidth - 10) {
            left = rect.left - popupRect.width - 10; // Position to the left instead
        }
        if (top < 10) {
            top = 10;
        }
        if (top + popupRect.height > window.innerHeight - 10) {
            top = window.innerHeight - popupRect.height - 10;
        }

        popup.style.left = `${left}px`;
        popup.style.top = `${top}px`;
        popup.style.display = 'block';
        
        console.log('Popup positioned at:', left, top, 'with display:', popup.style.display);
        console.log('Popup computed styles:', window.getComputedStyle(popup));
        
        // Force visibility
        popup.style.visibility = 'visible';
        popup.style.opacity = '1';
    }

    hideSubmissionPopup() {
        console.log('hideSubmissionPopup called');
        const existingPopup = document.getElementById('submission-popup');
        if (existingPopup) {
            console.log('Removing existing popup:', existingPopup);
            existingPopup.remove();
        } else {
            console.log('No existing popup found to remove');
        }
    }
} 