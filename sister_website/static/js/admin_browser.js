document.addEventListener('DOMContentLoaded', function() {
    const filters = {
        platform: document.getElementById('platform-filter'),
        type: document.getElementById('type-filter'),
        accepted: document.getElementById('accepted-filter')
    };

    const adminTreeRenderer = (data, treePane) => {
        const platformFilter = filters.platform.value;
        const typeFilter = filters.type.value;
        const acceptedFilter = filters.accepted.value;

        // The data from the admin API is structured differently, so we process it.
        // We will assume a flat list of screenshot objects, each with submission_details.
        // First, let's flatten the complex data structure from the admin endpoint.
        let allScreenshots = [];
        for (const platform in data) {
            for (const type in data[platform]) {
                for (const date in data[platform][type]) {
                    allScreenshots.push(...data[platform][type][date]);
                }
            }
        }

        // Apply filters
        const filteredScreenshots = allScreenshots.filter(sc => {
            if (platformFilter !== 'all' && sc.platform !== platformFilter) return false;
            if (typeFilter !== 'all' && sc.type !== typeFilter) return false;
            if (acceptedFilter === 'all') return true;
            if (acceptedFilter === 'yes' && sc.acceptance_state === 'accepted') return true;
            if (acceptedFilter === 'no' && sc.acceptance_state === 'declined') return true;
            if (acceptedFilter === 'pending' && sc.acceptance_state === 'pending') return true;
            return false;
        });

        // Group by Submission -> Build
        const groupedData = filteredScreenshots.reduce((acc, sc) => {
            if (!acc[sc.submission_id]) {
                acc[sc.submission_id] = { ...sc.submission_details, builds: {} };
            }
            if (!acc[sc.submission_id].builds[sc.build_id]) {
                acc[sc.submission_id].builds[sc.build_id] = { platform: sc.platform, type: sc.type, screenshots: [] };
            }
            acc[sc.submission_id].builds[sc.build_id].screenshots.push(sc);
            return acc;
        }, {});

        // Render the filtered tree
        treePane.innerHTML = '';
        if (Object.keys(groupedData).length === 0) {
            treePane.innerHTML = '<p>No screenshots match the current filters.</p>';
            return;
        }

        let treeHtml = '';
        for (const subId in groupedData) {
            const sub = groupedData[subId];
            treeHtml += `
                <details open>
                    <summary>Submission ${subId.substring(0, 8)} (${sub.email})</summary>
                    <ul>
                        ${Object.values(sub.builds).map(build => `
                            <li>
                                <details open>
                                    <summary>${build.platform} - ${build.type}</summary>
                                    <ul>
                                        ${build.screenshots.map(sc => `
                                            <li>
                                                <a href="#" class="screenshot-link" data-screenshot-id="${sc.id}">${sc.filename}</a>
                                            </li>
                                        `).join('')}
                                    </ul>
                                </details>
                            </li>
                        `).join('')}
                    </ul>
                </details>
            `;
        }
        treePane.innerHTML = treeHtml;
    };
    
    const config = {
        treePaneId: 'tree-pane',
        previewPaneId: 'preview-pane',
        previewImageId: 'preview-image',
        previewPlaceholderId: 'preview-placeholder',
        submissionInfoPaneId: 'submission-info',
        modalId: 'log-modal',
        dataUrl: '/admin/api/screenshots',
        treeRenderer: adminTreeRenderer
    };

    const browser = new ScreenshotBrowser(config);
    
    // The main data object for the browser needs to be the one from the instance.
    // We also need to adapt the buildScreenshotMap for the admin data structure.
    browser.buildScreenshotMap = (data) => {
        browser.screenshotDataMap = {};
        for (const platform in data) {
            for (const type in data[platform]) {
                for (const date in data[platform][type]) {
                    data[platform][type][date].forEach(sc => {
                        browser.screenshotDataMap[sc.id] = sc;
                        // Attach submission details to each screenshot for consistency
                        sc.submission_details = {
                            id: sc.submission_id,
                            email: sc.email,
                            acceptance_state: sc.acceptance_state,
                            is_withdrawn: sc.is_withdrawn,
                            events: sc.events,
                            acceptance_token: sc.acceptance_token // This might not be in admin view, but good to have
                        };
                    });
                }
            }
        }
    };
    
    Object.values(filters).forEach(filter => {
        filter.addEventListener('change', () => browser.renderTree(browser.data));
    });
});