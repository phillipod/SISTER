document.addEventListener('DOMContentLoaded', function() {
    const scriptTag = document.getElementById('admin-browser-script');
    let initialBuildId = scriptTag ? scriptTag.dataset.buildId : null;

    const filters = {
        platform: document.getElementById('platform-filter'),
        type: document.getElementById('type-filter'),
        accepted: document.getElementById('accepted-filter')
    };
    const treePane = document.getElementById('tree-pane');
    const previewImage = document.getElementById('preview-image');
    const previewPlaceholder = document.getElementById('preview-placeholder');
    const screenshotInfo = document.getElementById('screenshot-info');
    let screenshotData = {};

    function fetchScreenshots() {
        fetch('/admin/api/screenshots')
            .then(resp => {
                if (!resp.ok) throw new Error('Failed to fetch screenshot data.');
                return resp.json();
            })
            .then(data => {
                screenshotData = data;
                buildAndRenderTree();
                resetPreview();
            })
            .catch(error => {
                treePane.innerHTML = `<div class="error-message">${error.message}</div>`;
                console.error(error);
            });
    }

    function buildAndRenderTree() {
        const platformFilter = filters.platform.value;
        const typeFilter = filters.type.value;
        const acceptedFilter = filters.accepted.value;

        const treeData = {};
        let hasResults = false;

        for (const platform in screenshotData) {
            if (platformFilter !== 'all' && platform !== platformFilter) continue;
            treeData[platform] = {};

            for (const type in screenshotData[platform]) {
                if (typeFilter !== 'all' && type !== typeFilter) continue;
                treeData[platform][type] = {};

                for (const date in screenshotData[platform][type]) {
                    const screenshots = screenshotData[platform][type][date];
                    
                    const filteredScreenshots = screenshots.filter(sc => {
                        if (acceptedFilter === 'all') return true;
                        if (acceptedFilter === 'yes' && sc.acceptance_state === 'accepted') return true;
                        if (acceptedFilter === 'no' && sc.acceptance_state === 'declined') return true;
                        if (acceptedFilter === 'pending' && sc.acceptance_state === 'pending') return true;
                        return false;
                    });

                    if (filteredScreenshots.length > 0) {
                        const builds = filteredScreenshots.reduce((acc, sc) => {
                            acc[sc.build_id] = acc[sc.build_id] || {
                                screenshots: [],
                                build_id: sc.build_id,
                                submission_id: sc.submission_id,
                                email: sc.email // Store email for display
                            };
                            acc[sc.build_id].screenshots.push(sc);
                            return acc;
                        }, {});

                        treeData[platform][type][date] = builds;
                        hasResults = true;
                    }
                }
            }
        }
        renderTree(treeData, hasResults);
        
        // After rendering, check if we need to scroll to a specific build
        if (initialBuildId) {
            scrollToBuild(initialBuildId);
            // Clear the ID after the first use to prevent re-scrolling on filter change
            initialBuildId = null; 
        }
    }

    function renderTree(data, hasResults) {
        if (!treePane) return;
        treePane.innerHTML = '';

        if (!hasResults) {
            treePane.innerHTML = '<p>No screenshots match the current filters.</p>';
            return;
        }

        for (const platform in data) {
            const platformDetails = createDetails(platform);
            for (const type in data[platform]) {
                const typeDetails = createDetails(type);
                for (const date in data[platform][type]) {
                    const dateDetails = createDetails(date);
                    for (const buildId in data[platform][type][date]) {
                        const buildGroup = data[platform][type][date][buildId];
                        const { screenshots, build_id, submission_id, email } = buildGroup;
                        const buildLabel = `Build ${build_id.substring(0, 8)} (Submission ${submission_id.substring(0, 8)})`;
                        
                        const buildScreenshotIds = screenshots.map(sc => sc.id);
                        const buildDetails = createDetails(buildLabel, buildScreenshotIds);
                        buildDetails.dataset.buildId = build_id; // Set build_id attribute

                        const scUl = document.createElement('ul');
                        scUl.className = 'list-unstyled pl-3';

                        screenshots.forEach(sc => {
                            const scLi = document.createElement('li');
                            const link = document.createElement('a');
                            link.href = '#';
                            link.textContent = sc.filename;
                            link.dataset.screenshotId = sc.id;
                            link.dataset.info = JSON.stringify(sc);
                            link.addEventListener('click', handleScreenshotClick);
                            scLi.appendChild(link);
                            scUl.appendChild(scLi);
                        });
                        buildDetails.appendChild(scUl);
                        dateDetails.appendChild(buildDetails);
                    }
                    typeDetails.appendChild(dateDetails);
                }
                platformDetails.appendChild(typeDetails);
            }
            treePane.appendChild(platformDetails);
        }
    }

    function createDetails(summaryText, screenshotIds = []) {
        const details = document.createElement('details');
        details.open = true;
        const summary = document.createElement('summary');
        summary.textContent = summaryText;
        summary.classList.add('cursor-pointer');

        // If this node represents a group (submission or build) attach screenshotIds for preview
        if (screenshotIds.length > 0) {
            summary.dataset.groupScreenshots = screenshotIds.join(',');
            summary.addEventListener('click', handleGroupClick);
        }

        details.appendChild(summary);
        return details;
    }

    function scrollToBuild(buildId) {
        // Find the element for the build. We added a 'data-build-id' attribute for this.
        const buildElement = treePane.querySelector(`details[data-build-id="${buildId}"]`);
        
        if (buildElement) {
            // Scroll the element into view
            buildElement.scrollIntoView({ behavior: 'smooth', block: 'start' });

            // Optionally, open the details and highlight it
            buildElement.open = true;
            buildElement.classList.add('highlight'); // Add a class for styling
            
            // Trigger a click on the summary to show the screenshot previews
            const summary = buildElement.querySelector('summary');
            if (summary) {
                summary.click();
            } else {
                console.log('[Debug] scrollToBuild: Could not find summary element to click.');
            }

            // Remove the highlight after a few seconds
            setTimeout(() => {
                buildElement.classList.remove('highlight');
            }, 3000);
        } else {
            console.log('[Debug] scrollToBuild: Did not find element for Build ID:', buildId);
        }
    }

    function handleGroupClick(e) {
        const idsCsv = e.target.dataset.groupScreenshots;
        if (!idsCsv) {
            return;
        }

        const ids = idsCsv.split(',');

        // Remove single preview image and any previous grid
        previewImage.classList.add('hidden');
        previewImage.src = '';
        const existingGrid = document.getElementById('preview-grid');
        if (existingGrid) existingGrid.remove();

        previewPlaceholder.classList.add('hidden');

        const grid = document.createElement('div');
        grid.id = 'preview-grid';
        grid.classList.add('preview-grid');

        const isProgrammaticClick = !e.isTrusted;

        ids.forEach(id => {
            const img = document.createElement('img');
            
            img.classList.add('preview-grid-img');
            img.dataset.screenshotId = id;

            if (isProgrammaticClick) {
                // Programmatic click (from scrollToBuild), load image directly
                img.src = `/admin/screenshot/${id}?t=${Date.now()}`;
            } else {
                // Real user click, use lazy loading
                img.dataset.src = `/admin/screenshot/${id}?t=${Date.now()}`;
                img.loading = 'lazy'; // native hint where supported
            }

            // When a tile is clicked, trigger the corresponding tree link click
            img.addEventListener('click', () => {
                const link = treePane.querySelector(`a[data-screenshot-id="${id}"]`);
                if (link) {
                    link.scrollIntoView({behavior: 'smooth', block: 'center'});
                    link.click();
                }
            });

            grid.appendChild(img);
        });

        document.getElementById('preview-pane').appendChild(grid);        // Render submission info for the group
        if (ids.length > 0) {
            const firstScreenshotId = ids[0];
            const link = treePane.querySelector(`a[data-screenshot-id="${firstScreenshotId}"]`);
            if (link) {
                const info = JSON.parse(link.dataset.info);
                renderScreenshotInfo(info);
                // Move the info box to appear after the grid
                document.getElementById('preview-pane').appendChild(screenshotInfo);
                screenshotInfo.classList.remove('hidden');
            }
        }

        // Initialize lazy loading for the newly added grid, but only if it wasn't a programmatic click
        if (!isProgrammaticClick) {
            initLazyLoad(grid);
        }
    }

    function handleScreenshotClick(e) {
        e.preventDefault();
        const target = e.target;
        const info = JSON.parse(target.dataset.info);
        
        // Clear any existing grid preview
        const existingGrid = document.getElementById('preview-grid');
        if (existingGrid) existingGrid.remove();

        previewImage.src = `/admin/screenshot/${target.dataset.screenshotId}?t=${Date.now()}`;
        previewImage.classList.remove('hidden');
        previewPlaceholder.classList.remove('hidden');

        renderScreenshotInfo(info);

        // Make sure info card is visible
        screenshotInfo.classList.remove('hidden');
    }

    function renderScreenshotInfo(info) {
        screenshotInfo.innerHTML = ''; // Clear previous info

        const card = document.createElement('div');
        card.className = 'info-card';

            let statusText;
            let statusClass;
        let isWithdrawn = info.is_withdrawn;

            switch (info.acceptance_state) {
                case 'accepted':
                    statusText = 'Yes';
                    statusClass = 'status-accepted';
                    break;
                case 'declined':
                    statusText = 'No';
                    statusClass = 'status-declined';
                    break;
                case 'pending':
            default:
                    statusText = 'Pending';
                    statusClass = 'status-pending';
                    break;
        }

        const statusP = document.createElement('p');
        statusP.innerHTML = `<strong>Status:</strong> <span class="status-badge ${statusClass}">${statusText}</span>`;

        if (isWithdrawn) {
            statusP.innerHTML += ` <span class="status-badge status-withdrawn">Withdrawn</span>`;
        }
        
        const emailP = document.createElement('p');
        emailP.innerHTML = `<strong>Email:</strong> ${info.email}`;

        card.appendChild(statusP);
        card.appendChild(emailP);

        // Timeline for events
        if (info.events && info.events.length > 0) {
            const timeline = document.createElement('div');
            timeline.className = 'timeline';
            info.events.forEach(event => {
                const eventElement = document.createElement('div');
                eventElement.className = 'timeline-item';
                
                const timestamp = new Date(event.timestamp).toLocaleString();

                let eventDetailsHTML = `<p><strong>${event.type}</strong> - ${timestamp}`;
                
                let viaContent = '';
                if (event.method === 'Email' && event.log_id) {
                    viaContent = ` <a href="#" class="view-email" data-log-id="${event.log_id}">(Email)</a>`;
                } else if (event.method === 'Link' && event.details) {
                    viaContent = ` <a href="#" class="view-link-details" data-details='${JSON.stringify(event.details)}'>(Link)</a>`;
                } else if (event.method && event.method !== 'Web Form') {
                     viaContent = ` (${event.method})`;
                }

                eventElement.innerHTML = eventDetailsHTML + viaContent + `</p>`;
                timeline.appendChild(eventElement);
            });
            card.appendChild(timeline);
        }
        
        // Add resend consent button if license is pending
        if (info.acceptance_state === 'pending' && !info.is_withdrawn) {
            const container = document.createElement('div');
            container.className = 'resend-consent-container';

            const resendButton = document.createElement('button');
            resendButton.textContent = 'Resend Consent Email';
            resendButton.className = 'btn btn-secondary btn-sm';
            resendButton.dataset.submissionId = info.submission_id;
            resendButton.addEventListener('click', handleResendConsent);
            
            const statusSpan = document.createElement('span');
            statusSpan.className = 'resend-status-message';

            container.appendChild(resendButton);
            container.appendChild(statusSpan);
            card.appendChild(container);
        }

        screenshotInfo.appendChild(card);
        attachTimelineEventListeners();
    }

    function attachTimelineEventListeners() {
        screenshotInfo.querySelectorAll('.view-email').forEach(link => {
            link.addEventListener('click', function(e) {
                e.preventDefault();
                const logId = this.dataset.logId;
                fetch(`/admin/api/email_log/${logId}`)
                    .then(response => {
                        if (!response.ok) throw new Error('Failed to fetch email log.');
                        return response.json();
                    })
                    .then(data => {
                        let emailContent = `<h3>${data.subject}</h3>
                                            <p><strong>From:</strong> ${data.from}</p>
                                            <p><strong>To:</strong> ${data.to}</p>
                                            <p><strong>Date:</strong> ${new Date(data.received_at).toLocaleString()}</p>
                                            <hr>
                                            <div>${data.body_html || '<p>No HTML body.</p>'}</div>`;
                        showModal('Email Details', emailContent);
                    })
                    .catch(error => {
                        console.error('Error fetching email log:', error);
                        showModal('Error', 'Could not load email details.');
                    });
            });
        });

        screenshotInfo.querySelectorAll('.view-link-details').forEach(link => {
            link.addEventListener('click', function(e) {
                e.preventDefault();
                try {
                    const details = JSON.parse(this.dataset.details);
                    let detailsContent = '<ul>';
                    if (details.ip_address) detailsContent += `<li>IP Address: ${details.ip_address}</li>`;
                    if (details.user_agent) detailsContent += `<li>User Agent: ${details.user_agent}</li>`;
                    detailsContent += '</ul>';
                    showModal('Link Details', detailsContent);
                } catch (error) {
                    console.error('Error parsing link details:', error);
                    showModal('Error', 'Could not display link details.');
                }
            });
        });
    }

    function showModal(title, content) {
        // Remove existing modal first
        const existingModal = document.getElementById('event-details-modal');
        if (existingModal) {
            existingModal.remove();
        }

        const modal = document.createElement('div');
        modal.id = 'event-details-modal';
        modal.className = 'modal-backdrop'; // Use a class for styling
        
        modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h2>${title}</h2>
                    <button id="close-modal-btn" class="close-btn">&times;</button>
                </div>
                <div class="modal-body">
                    ${content}
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        modal.querySelector('#close-modal-btn').addEventListener('click', () => modal.remove());
        modal.addEventListener('click', function(e) {
            if (e.target.id === 'event-details-modal') {
                modal.remove();
            }
        });
    }

    async function handleResendConsent(e) {
        const button = e.target;
        const submissionId = button.dataset.submissionId;
        const statusSpan = button.parentElement.querySelector('.resend-status-message');
        const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

        if (!statusSpan) {
            console.error("Could not find status message element for resend button.");
            return;
        }

        if (!confirm('Are you sure you want to resend the consent email for this submission?')) {
            return;
        }

        button.disabled = true;
        statusSpan.textContent = 'Sending...';
        statusSpan.classList.add('resend-status-sending');

        try {
            const response = await fetch(`/admin/api/resend-consent/${submissionId}`, {
                method: 'POST',
                headers: {
                    'X-CSRF-Token': csrfToken
                }
            });

            const result = await response.json();

            if (response.ok) {
                statusSpan.textContent = 'Sent successfully!';
                statusSpan.className = 'resend-status-message resend-status-success';
            } else {
                statusSpan.textContent = `Error: ${result.error || 'Unknown error'}`;
                statusSpan.className = 'resend-status-message resend-status-error';
            }
        } catch (error) {
            console.error('Error resending consent email:', error);
            statusSpan.textContent = 'Failed to send.';
            statusSpan.className = 'resend-status-message resend-status-error';
        } finally {
            button.disabled = false;
            setTimeout(() => {
                statusSpan.textContent = '';
            }, 5000);
        }
    }

    // Lazy load helper using IntersectionObserver
    function initLazyLoad(container) {
        const lazyImages = [].slice.call(container.querySelectorAll("img[data-src]"));
        if (!lazyImages.length) return;

        if ('IntersectionObserver' in window) {
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
        } else {
            // Fallback: load all immediately
            lazyImages.forEach(img => {
                img.src = img.dataset.src;
                img.removeAttribute('data-src');
            });
        }
    }

    // Hide preview image & grid, show placeholder
    function resetPreview() {
        // Hide image
        previewImage.classList.add('hidden');
        previewImage.src = '';

        // Remove any grid
        const existingGrid = document.getElementById('preview-grid');
        if (existingGrid) existingGrid.remove();

        // Show placeholder and clear info
        previewPlaceholder.classList.remove('hidden');
        screenshotInfo.innerHTML = '';
        screenshotInfo.classList.add('hidden');
    }

    Object.values(filters).forEach(filter => {
        filter.addEventListener('change', buildAndRenderTree);
    });

    fetchScreenshots();
});