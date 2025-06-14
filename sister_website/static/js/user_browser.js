document.addEventListener('DOMContentLoaded', () => {
    const groupByPlatformCheckbox = document.getElementById('group-by-platform');
    const groupByTypeCheckbox = document.getElementById('group-by-type');

    const popup = document.getElementById('tree-options-popup');
    const openPopupBtn = document.getElementById('tree-options-btn');
    const applyBtn = document.getElementById('apply-tree-options');

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

        const groupOrder = [];
        if (groupByPlatformCheckbox.checked) groupOrder.push('platform');
        if (groupByTypeCheckbox.checked) groupOrder.push('type');
        groupOrder.push('date'); // Date is always a grouping level.

        // 1. Transform the flat submission list into a dynamic hierarchical structure.
        const hierarchicalData = {};
        data.forEach(sub => {
            const dateStr = new Date(sub.created_at).toISOString().split('T')[0];
            sub.builds.forEach(build => {
                build.screenshots.forEach(sc => {
                    const scData = {
                        platform: build.platform || "Unknown",
                        type: build.type || "Unknown",
                        date: dateStr,
                        screenshot: { // Keep original screenshot data separate
                            ...sc,
                            build_id: build.id,
                            submission_id: sub.id,
                            email: sub.email,
                            acceptance_state: sub.acceptance_state,
                            is_withdrawn: sub.is_withdrawn,
                            events: sub.events,
                            platform: build.platform || "Unknown",
                            type: build.type || "Unknown"
                        }
                    };

                    let currentLevel = hierarchicalData;
                    groupOrder.forEach(key => {
                        const value = scData[key];
                        if (!currentLevel[value]) {
                            if (key === 'date') {
                                currentLevel[value] = [];
                            } else {
                                currentLevel[value] = {};
                            }
                        }
                        currentLevel = currentLevel[value];
                    });
                    currentLevel.push(scData.screenshot);
                });
            });
        });
        
        // 2. Render the tree from the hierarchical data.
        const createDetails = (summaryText, parentElement, allScreenshots) => {
            const details = document.createElement('details');
            details.open = true;
            const summary = document.createElement('summary');
            const summarySpan = document.createElement('span');
            summarySpan.textContent = summaryText;
            
            if (allScreenshots && allScreenshots.length > 0) {
                summarySpan.dataset.groupScreenshots = allScreenshots.map(sc => sc.id).join(',');
            }

            summary.appendChild(summarySpan);
            details.appendChild(summary);
            parentElement.appendChild(details);
            return details;
        };

        const renderNode = (node, parentElement) => {
            for (const key in node) {
                const childNode = node[key];
                if (Array.isArray(childNode)) { // Leaf nodes (screenshot arrays)
                    // Group screenshots by submission
                    const submissions = childNode.reduce((acc, sc) => {
                        acc[sc.submission_id] = acc[sc.submission_id] || [];
                        acc[sc.submission_id].push(sc);
                        return acc;
                    }, {});

                    for (const subId in submissions) {
                        const subScreenshots = submissions[subId];
                        const firstSc = subScreenshots[0];
                        const subLabel = `Submission ${firstSc.submission_id.substring(0, 8)}`;
                        const subDetails = createDetails(subLabel, parentElement, subScreenshots);
                        
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
                    }
                } else { // It's a grouping node
                    const allScreenshotsInGroup = getAllScreenshots(childNode);
                    const details = createDetails(key, parentElement, allScreenshotsInGroup);
                    renderNode(childNode, details);
                }
            }
        };
        
        const getAllScreenshots = (node) => {
            let screenshots = [];
            for (const key in node) {
                const child = node[key];
                if (Array.isArray(child)) {
                    screenshots = screenshots.concat(child);
                } else {
                    screenshots = screenshots.concat(getAllScreenshots(child));
                }
            }
            return screenshots;
        };

        renderNode(hierarchicalData, treePane);
    };

    const config = {
        treePaneId: 'tree-pane',
        previewPaneId: 'preview-pane',
        submissionInfoPaneId: 'submission-info',
        previewContentId: 'preview-content',
        dataUrl: '/api/me/submissions_data',
        mapBuilder: userMapBuilder,
        treeRenderer: userTreeRenderer,
        userCanManage: true,
        // API Endpoints
        logAccessTokenUrl: '/api/log-access-token/{log_id}',
        emailLogUrl: '/api/me/email_log/{log_id}',
        linkLogUrl: '/api/me/link_log/{log_id}',
        screenshotImageUrl: '/me/screenshot/{sc_id}'
    };
    
    const browser = new ScreenshotBrowser(config);
    browser.initialize();

    openPopupBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        popup.classList.toggle('active');
    });

    applyBtn.addEventListener('click', () => {
        popup.classList.remove('active');
        browser.renderTree();
    });

    document.addEventListener('click', (event) => {
        if (!popup.contains(event.target) && !openPopupBtn.contains(event.target)) {
            popup.classList.remove('active');
        }
    });

    popup.addEventListener('click', (event) => {
        event.stopPropagation();
    });

    [groupByPlatformCheckbox, groupByTypeCheckbox].forEach(checkbox => {
        checkbox.addEventListener('change', () => {
            browser.renderTree();
        });
    });
});