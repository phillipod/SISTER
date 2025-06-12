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

        const filteredData = {};
        let hasResults = false;

        for (const platform in screenshotData) {
            if (platformFilter !== 'all' && platform !== platformFilter) continue;
            for (const type in screenshotData[platform]) {
                if (typeFilter !== 'all' && type !== typeFilter) continue;
                for (const date in screenshotData[platform][type]) {
                    const screenshots = screenshotData[platform][type][date].filter(sc => {
                        if (acceptedFilter === 'all') return true;
                        return acceptedFilter === 'yes' ? sc.is_accepted : !sc.is_accepted;
                    });

                    if (screenshots.length > 0) {
                        if (!filteredData[platform]) filteredData[platform] = {};
                        if (!filteredData[platform][type]) filteredData[platform][type] = {};
                        filteredData[platform][type][date] = screenshots;
                        hasResults = true;
                    }
                }
            }
        }

        renderTree(filteredData, hasResults);
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
                    const scUl = document.createElement('ul');
                    scUl.className = 'list-unstyled pl-3';
                    data[platform][type][date].forEach(sc => {
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
                    dateDetails.appendChild(scUl);
                    typeDetails.appendChild(dateDetails);
                }
                platformDetails.appendChild(typeDetails);
            }
            treePane.appendChild(platformDetails);
        }
    }

    function createDetails(summaryText) {
        const details = document.createElement('details');
        details.open = true;
        const summary = document.createElement('summary');
        summary.textContent = summaryText;
        summary.style.cursor = 'pointer';
        details.appendChild(summary);
        return details;
    }

    function handleScreenshotClick(e) {
        e.preventDefault();
        const target = e.target;
        const info = JSON.parse(target.dataset.info);
        
        previewImage.src = `/admin/screenshot/${target.dataset.screenshotId}?t=${Date.now()}`;
        previewImage.style.display = 'block';
        previewPlaceholder.style.display = 'none';

        screenshotInfo.innerHTML = `
            <p><strong>Submission:</strong> ${info.submission_id}</p>
            <p><strong>Email:</strong> ${info.email}</p>
            <p><strong>License Accepted:</strong>
            <span class="status-badge ${info.is_accepted ? 'status-accepted' : 'status-declined'}">
                ${info.is_accepted ? 'Yes' : 'No'}
            </span>
            </p>
        `;
    }

    Object.values(filters).forEach(filter => {
        filter.addEventListener('change', buildAndRenderTree);
    });

    fetchScreenshots();
});
