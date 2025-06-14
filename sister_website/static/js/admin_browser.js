document.addEventListener('DOMContentLoaded', function() {
    const filters = {
        platform: document.getElementById('platform-filter'),
        type: document.getElementById('type-filter'),
        accepted: document.getElementById('accepted-filter')
    };

    const mapBuilder = (data) => {
        const map = {};
        for (const platform in data) {
            for (const type in data[platform]) {
                for (const date in data[platform][type]) {
                    data[platform][type][date].forEach(sc => {
                        map[sc.id] = sc;
                    });
                }
            }
        }
        return map;
    };

    const adminTreeRenderer = (data, treePane) => {
        const platformFilter = filters.platform.value;
        const typeFilter = filters.type.value;
        const acceptedFilter = filters.accepted.value;

        treePane.innerHTML = '';
        let hasResults = false;

        const createDetails = (summaryText) => {
            const details = document.createElement('details');
            details.open = true;
            const summary = document.createElement('summary');
            const summarySpan = document.createElement('span');
            summarySpan.textContent = summaryText;
            summary.appendChild(summarySpan);
            details.appendChild(summary);
            return details;
        };
        
        for (const platform in data) {
            if (platformFilter !== 'all' && platform !== platformFilter) continue;
            const platformDetails = createDetails(platform);

            for (const type in data[platform]) {
                if (typeFilter !== 'all' && type !== typeFilter) continue;
                const typeDetails = createDetails(type);
                    
                for (const date in data[platform][type]) {
                    const screenshots = data[platform][type][date].filter(sc => {
                        if (acceptedFilter === 'all') return true;
                        return sc.acceptance_state === acceptedFilter;
                    });

                    if (screenshots.length > 0) {
                        const dateDetails = createDetails(date);
                        const submissions = screenshots.reduce((acc, sc) => {
                            acc[sc.submission_id] = acc[sc.submission_id] || [];
                            acc[sc.submission_id].push(sc);
                            return acc;
                        }, {});

                        for (const submissionId in submissions) {
                            const subScreenshots = submissions[submissionId];
                            const firstSc = subScreenshots[0];
                            const subLabel = `Submission ${firstSc.submission_id.substring(0, 8)} (${firstSc.email})`;
                            
                            const subDetails = createDetails(subLabel);
                            subDetails.dataset.buildId = firstSc.build_id; // For scrolling
                            
                            const summary = subDetails.querySelector('summary');
                            const summarySpan = summary.querySelector('span');
                            summarySpan.dataset.groupScreenshots = subScreenshots.map(sc => sc.id).join(',');

                        const scUl = document.createElement('ul');
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

                            subDetails.appendChild(scUl);
                            dateDetails.appendChild(subDetails);
                            hasResults = true;
                    }
                    typeDetails.appendChild(dateDetails);
                }
                }
                if (typeDetails.childElementCount > 1) platformDetails.appendChild(typeDetails);
            }
            if (platformDetails.childElementCount > 1) treePane.appendChild(platformDetails);
        }

        if (!hasResults) {
            treePane.innerHTML = '<p>No screenshots match the current filters.</p>';
        }
    };
    
    const scriptTag = document.getElementById('admin-browser-script');
    const initialBuildId = scriptTag ? scriptTag.dataset.buildId : null;

    const config = {
        treePaneId: 'tree-pane',
        previewPaneId: 'preview-pane',
        submissionInfoPaneId: 'submission-info',
        previewContentId: 'preview-content',
        dataUrl: '/admin/api/screenshots',
        mapBuilder: mapBuilder,
        treeRenderer: (data, treePane) => adminTreeRenderer(data, treePane),
        // API Endpoints
        logAccessTokenUrl: '/api/log-access-token/{log_id}',
        emailLogUrl: '/admin/api/email_log/{log_id}',
        linkLogUrl: '/admin/api/link_log/{log_id}',
        screenshotImageUrl: '/admin/screenshot/{sc_id}'
    };

    const browser = new ScreenshotBrowser(config);
    browser.initialize(initialBuildId);

    Object.values(filters).forEach(filter => {
        filter.addEventListener('change', () => browser.renderTree());
    });
});