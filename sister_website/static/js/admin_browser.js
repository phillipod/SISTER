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
                            const acceptedMatch = acceptedFilter === 'yes';
                            if (sc.is_accepted !== acceptedMatch) return;
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
        screenshotInfo.innerHTML = '';

        const grid = document.createElement('div');
        grid.id = 'preview-grid';
        grid.style.display = 'grid';
        grid.style.gridTemplateColumns = 'repeat(auto-fill, minmax(180px, 1fr))';
        grid.style.gap = '8px';

        ids.forEach(id => {
            const img = document.createElement('img');
            img.src = `/admin/screenshot/${id}?t=${Date.now()}`;
            img.style.width = '100%';
            img.style.objectFit = 'cover';
            grid.appendChild(img);
        });

        document.getElementById('preview-pane').appendChild(grid);
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

        let infoHtml = `
            <p><strong>Submission:</strong> ${info.submission_id}</p>
            <p><strong>Email:</strong> ${info.email}</p>
            <p><strong>License Accepted:</strong>
            <span class="status-badge ${info.is_accepted ? 'status-accepted' : 'status-declined'}">
                ${info.is_accepted ? 'Yes' : 'No'}
            </span>
            </p>
        `;

        // Add resend button for unaccepted submissions
        if (!info.is_accepted) {
            infoHtml += `
                <div class="resend-section">
                    <button class="btn resend-btn" data-submission-id="${info.submission_id}">
                        Resend Consent Email
                    </button>
                    <span class="resend-status"></span>
                </div>
            `;
        }

        screenshotInfo.innerHTML = infoHtml;

        // Add click handler for resend button if it exists
        const resendBtn = screenshotInfo.querySelector('.resend-btn');
        if (resendBtn) {
            resendBtn.addEventListener('click', async function() {
                const submissionId = this.dataset.submissionId;
                const statusSpan = this.nextElementSibling;

                // Add confirmation dialog
                if (!confirm('Are you sure you want to resend the consent email? This will invalidate any previous consent links.')) {
                    return;
                }

                try {
                    this.disabled = true;
                    statusSpan.textContent = 'Sending...';

                    const response = await fetch(`/admin/api/resend-consent/${submissionId}`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        }
                    });

                    const data = await response.json();

                    if (response.ok) {
                        statusSpan.textContent = 'Email sent successfully!';
                        statusSpan.style.color = 'var(--tip-color)';
                    } else {
                        throw new Error(data.error || 'Failed to send email');
                    }
                } catch (error) {
                    statusSpan.textContent = `Error: ${error.message}`;
                    statusSpan.style.color = 'var(--danger-color)';
                } finally {
                    this.disabled = false;
                }
            });
        }
    }

    Object.values(filters).forEach(filter => {
        filter.addEventListener('change', buildAndRenderTree);
    });

    fetchScreenshots();
});