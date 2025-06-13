document.addEventListener('DOMContentLoaded', function() {
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

        const nested = {};
        let hasResults = false;

        for (const platform in screenshotData) {
            if (platformFilter !== 'all' && platform !== platformFilter) continue;
            for (const type in screenshotData[platform]) {
                if (typeFilter !== 'all' && type !== typeFilter) continue;

                for (const date in screenshotData[platform][type]) {
                    screenshotData[platform][type][date].forEach(sc => {
                        // License filter
                        if (acceptedFilter !== 'all') {
                            if (acceptedFilter === 'yes' && sc.acceptance_state !== 'accepted') return;
                            if (acceptedFilter === 'no' && sc.acceptance_state !== 'declined') return;
                            if (acceptedFilter === 'pending' && sc.acceptance_state !== 'pending') return;
                        }

                        hasResults = true;

                        nested[platform] = nested[platform] || {};
                        nested[platform][type] = nested[platform][type] || {};

                        const submissionId = sc.submission_id;
                        const buildId = sc.build_id;

                        if (!nested[platform][type][submissionId]) {
                            nested[platform][type][submissionId] = {
                                meta: {
                                    created_at: sc.submission_created,
                                    is_accepted: sc.is_accepted,
                                    email: sc.email
                                },
                                builds: {}
                            };
                        }

                        if (!nested[platform][type][submissionId].builds[buildId]) {
                            nested[platform][type][submissionId].builds[buildId] = [];
                        }

                        nested[platform][type][submissionId].builds[buildId].push(sc);
                    });
                }
            }
        }

        renderTree(nested, hasResults);

        // After tree build, if nothing selected, ensure placeholder visible
        if (!treePane.querySelector('a.active')) {
            resetPreview();
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

                for (const submissionId in data[platform][type]) {
                    const submission = data[platform][type][submissionId];
                    const submissionLabel = `Submission ${submissionId.substring(0, 8)} (${submission.meta.created_at.split(' ')[0]})`;

                    // Collect all screenshot ids under this submission for group preview
                    const submissionScreenshotIds = [];

                    const submissionDetails = createDetails(submissionLabel, submissionScreenshotIds);

                    for (const buildId in submission.builds) {
                        const buildScreens = submission.builds[buildId];

                        // push screenshots ids to submission ids list
                        buildScreens.forEach(sc => submissionScreenshotIds.push(sc.id));

                        const buildLabel = `Build ${buildId.substring(0, 8)}`;
                        const buildScreenshotIds = buildScreens.map(sc => sc.id);
                        const buildDetails = createDetails(buildLabel, buildScreenshotIds);

                        const scUl = document.createElement('ul');
                        scUl.className = 'list-unstyled pl-3';

                        buildScreens.forEach(sc => {
                            const scLi = document.createElement('li');
                            const link = document.createElement('a');
                            link.href = '#';
                            link.textContent = sc.filename;
                            link.dataset.screenshotId = sc.id;
                            link.dataset.info = JSON.stringify({
                                is_accepted: sc.is_accepted,
                                acceptance_state: sc.acceptance_state,
                                is_withdrawn: sc.is_withdrawn,
                                submission_id: sc.submission_id,
                                email: sc.email
                            });
                            link.addEventListener('click', handleScreenshotClick);
                            scLi.appendChild(link);
                            scUl.appendChild(scLi);
                        });

                        buildDetails.appendChild(scUl);
                        submissionDetails.appendChild(buildDetails);
                    }

                    // After processing builds, attach aggregated ids to submission summary
                    const submissionSummary = submissionDetails.querySelector('summary');
                    submissionSummary.dataset.groupScreenshots = submissionScreenshotIds.join(',');
                    submissionSummary.addEventListener('click', handleGroupClick);

                    typeDetails.appendChild(submissionDetails);
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
        summary.style.cursor = 'pointer';

        // If this node represents a group (submission or build) attach screenshotIds for preview
        if (screenshotIds.length > 0) {
            summary.dataset.groupScreenshots = screenshotIds.join(',');
            summary.addEventListener('click', handleGroupClick);
        }

        details.appendChild(summary);
        return details;
    }

    function handleGroupClick(e) {
        const idsCsv = e.target.dataset.groupScreenshots;
        if (!idsCsv) return;

        const ids = idsCsv.split(',');

        // Remove single preview image and any previous grid
        previewImage.style.display = 'none';
        previewImage.src = '';
        const existingGrid = document.getElementById('preview-grid');
        if (existingGrid) existingGrid.remove();

        previewPlaceholder.style.display = 'none';

        const grid = document.createElement('div');
        grid.id = 'preview-grid';
        grid.style.display = 'grid';
        grid.style.gridTemplateColumns = 'repeat(auto-fill, minmax(180px, 1fr))';
        grid.style.gap = '8px';

        ids.forEach(id => {
            const img = document.createElement('img');
            // Defer actual loading using data-src for lazy observer
            img.dataset.src = `/admin/screenshot/${id}?t=${Date.now()}`;
            img.style.width = '100%';
            img.style.objectFit = 'cover';
            img.dataset.screenshotId = id;
            img.loading = 'lazy'; // native hint where supported

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

        document.getElementById('preview-pane').appendChild(grid);

        // Render submission info for the group
        if (ids.length > 0) {
            const firstScreenshotId = ids[0];
            const link = treePane.querySelector(`a[data-screenshot-id="${firstScreenshotId}"]`);
            if (link) {
                const info = JSON.parse(link.dataset.info);
                renderScreenshotInfo(info);
            }
        }

        // Initialize lazy loading for the newly added grid
        initLazyLoad(grid);
    }

    function handleScreenshotClick(e) {
        e.preventDefault();
        const target = e.target;
        const info = JSON.parse(target.dataset.info);
        
        // Clear any existing grid preview
        const existingGrid = document.getElementById('preview-grid');
        if (existingGrid) existingGrid.remove();

        previewImage.src = `/admin/screenshot/${target.dataset.screenshotId}?t=${Date.now()}`;
        previewImage.style.display = 'block';
        previewPlaceholder.style.display = 'none';

        renderScreenshotInfo(info);
    }

    function renderScreenshotInfo(info) {
        // Ensure screenshot info section is visible
        screenshotInfo.style.display = 'block';

        let infoHtml = `
            <p><strong>Submission:</strong> ${info.submission_id}</p>
            <p><strong>Email:</strong> ${info.email}</p>
        `;

        // Check for withdrawn status first, but only if it was previously accepted
        if (info.is_withdrawn && info.acceptance_state === 'accepted') {
            infoHtml += `
                <p><strong>Status:</strong>
                <span class="status-badge status-withdrawn">
                    Withdrawn
                </span>
                </p>
            `;
        } else {
            let statusText;
            let statusClass;

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
                    statusText = 'Pending';
                    statusClass = 'status-pending';
                    break;
                default:
                    // Fallback for old data or unexpected values
                    statusText = info.is_accepted ? 'Yes' : 'No';
                    statusClass = info.is_accepted ? 'status-accepted' : 'status-declined';
            }
            
            infoHtml += `
                <p><strong>License Accepted:</strong>
                <span class="status-badge ${statusClass}">
                    ${statusText}
                </span>
                </p>
            `;

            // Add a resend consent button if the submission is still pending
            if (info.acceptance_state === 'pending') {
                infoHtml += `
                    <div class="resend-consent-container">
                        <button class="btn btn-secondary btn-sm" id="resend-consent-btn" data-submission-id="${info.submission_id}">
                            Resend Consent Email
                        </button>
                        <span id="resend-status" class="resend-status-message"></span>
                    </div>
                `;
            }
        }

        screenshotInfo.innerHTML = infoHtml;

        // Add event listener for the resend button if it was added
        const resendBtn = document.getElementById('resend-consent-btn');
        if (resendBtn) {
            resendBtn.addEventListener('click', handleResendConsent);
        }
    }

    async function handleResendConsent(e) {
        e.preventDefault();
        const submissionId = e.target.dataset.submissionId;
        const statusSpan = document.getElementById('resend-status');

        // Add confirmation dialog
        if (!confirm('Are you sure you want to resend the consent email for this submission?')) {
            return;
        }

        try {
            e.target.disabled = true;
            statusSpan.textContent = 'Sending...';

            const response = await fetch(`/admin/api/resend-consent/${submissionId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            const result = await response.json();

            if (response.ok) {
                statusSpan.textContent = result.message || 'Email sent successfully!';
                statusSpan.style.color = 'var(--success-color)';
            } else {
                statusSpan.textContent = result.message || 'Failed to send email.';
                statusSpan.style.color = 'var(--danger-color)';
            }
        } catch (error) {
            console.error('Error resending consent email:', error);
            statusSpan.textContent = 'An error occurred.';
            statusSpan.style.color = 'var(--danger-color)';
        } finally {
            e.target.disabled = false;
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
        previewImage.style.display = 'none';
        previewImage.src = '';

        // Remove any grid
        const existingGrid = document.getElementById('preview-grid');
        if (existingGrid) existingGrid.remove();

        // Show placeholder and clear info
        previewPlaceholder.style.display = 'block';
        screenshotInfo.innerHTML = '';
        screenshotInfo.style.display = 'none';
    }

    Object.values(filters).forEach(filter => {
        filter.addEventListener('change', buildAndRenderTree);
    });

    fetchScreenshots();
});