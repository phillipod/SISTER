document.addEventListener('DOMContentLoaded', () => {
    // This map builder is for the user data structure, which is a flat list of submissions.
    const userMapBuilder = (data) => {
        const map = {};
        if (!data) return map;
        data.forEach(sub => {
            sub.builds.forEach(build => {
                build.screenshots.forEach(sc => {
                    // The user API already provides submission_details nested correctly.
                    map[sc.id] = sc;
                });
            });
        });
        return map;
    };

    const userTreeRenderer = (data, treePane) => {
        treePane.innerHTML = '';
        if (!data || data.length === 0) {
            treePane.innerHTML = '<p>You have no submissions.</p>';
            return;
        }

        // 1. Transform the flat submission list into the hierarchical structure
        //    that the rendering logic expects (Platform -> Type -> Date -> Screenshot List)
        const hierarchicalData = {};
        data.forEach(sub => {
            const dateStr = new Date(sub.created_at).toISOString().split('T')[0];
            sub.builds.forEach(build => {
                build.screenshots.forEach(sc => {
                    const platform = build.platform || "Unknown";
                    const type = build.type || "Unknown";

                    if (!hierarchicalData[platform]) hierarchicalData[platform] = {};
                    if (!hierarchicalData[platform][type]) hierarchicalData[platform][type] = {};
                    if (!hierarchicalData[platform][type][dateStr]) hierarchicalData[platform][type][dateStr] = [];
                    
                    // Create a screenshot object that mimics the admin API's structure for consistency
                    const screenshotForTree = {
                        ...sc,
                        build_id: build.id,
                        submission_id: sub.id,
                        email: sub.email,
                        acceptance_state: sub.acceptance_state,
                        is_withdrawn: sub.is_withdrawn,
                        events: sub.events,
                        platform: platform,
                        type: type
                    };
                    hierarchicalData[platform][type][dateStr].push(screenshotForTree);
                });
            });
        });
        
        // 2. Render the tree using the same logic as the admin browser
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

        for (const platform in hierarchicalData) {
            const platformDetails = createDetails(platform);
            for (const type in hierarchicalData[platform]) {
                const typeDetails = createDetails(type);
                for (const date in hierarchicalData[platform][type]) {
                    const screenshots = hierarchicalData[platform][type][date];
                    const dateDetails = createDetails(date);
                    
                    // In the user view, all screenshots on a given date from a given build belong to the same submission.
                    // We can group them visually by submission.
                    const submissions = screenshots.reduce((acc, sc) => {
                        acc[sc.submission_id] = acc[sc.submission_id] || [];
                        acc[sc.submission_id].push(sc);
                        return acc;
                    }, {});

                    for (const subId in submissions) {
                        const subScreenshots = submissions[subId];
                        const firstSc = subScreenshots[0];
                        const subLabel = `Submission ${firstSc.submission_id.substring(0, 8)}`;

                        const subDetails = createDetails(subLabel);
                        const summarySpan = subDetails.querySelector('span');
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
                    }
                    typeDetails.appendChild(dateDetails);
                }
                platformDetails.appendChild(typeDetails);
            }
            treePane.appendChild(platformDetails);
        }
    };

    const config = {
        treePaneId: 'tree-pane',
        previewPaneId: 'preview-pane',
        submissionInfoPaneId: 'submission-info',
        previewContentId: 'preview-content',
        dataUrl: '/api/me/submissions_data',
        mapBuilder: userMapBuilder,
        treeRenderer: userTreeRenderer
    };
    
    const browser = new ScreenshotBrowser(config);
    browser.initialize();
});