document.addEventListener('DOMContentLoaded', () => {
    const filters = {
        platform: document.getElementById('platform-filter'),
        type: document.getElementById('type-filter'),
        accepted: document.getElementById('accepted-filter')
    };

    const popup = document.getElementById('tree-options-popup');
    const openPopupBtn = document.getElementById('tree-options-btn');

    const toggleFiltersBtn = document.getElementById('toggle-filters-btn');
    const filtersContainer = document.querySelector('.screenshot-filters');
    const groupByFieldset = document.getElementById('group-by-fieldset');

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

        // 1. Filter data based on dropdowns
        const platformFilter = filters.platform.value;
        const typeFilter = filters.type.value;
        const acceptedFilter = filters.accepted.value;

        const filteredData = data.filter(sub => {
            // Filter by license status first
            return acceptedFilter === 'all' || sub.acceptance_state === acceptedFilter;
        }).map(sub => {
            // Then filter the builds within the matching submissions
            const newSub = {...sub, builds: []};
            sub.builds.forEach(build => {
                const platformMatch = platformFilter === 'all' || build.platform === platformFilter;
                const typeMatch = typeFilter === 'all' || build.type === typeFilter;
                if (platformMatch && typeMatch) {
                    newSub.builds.push(build);
                }
            });
            return newSub;
        }).filter(sub => sub.builds.length > 0); // Remove submissions with no matching builds

        if (!filteredData || filteredData.length === 0) {
            treePane.innerHTML = '<p>You have no submissions matching the current options.</p>';
            return;
        }

        const groupOrder = [];
        const groupByCheckboxes = groupByFieldset.querySelectorAll('input[type="checkbox"]');
        groupByCheckboxes.forEach(checkbox => {
            if (checkbox.checked) {
                groupOrder.push(checkbox.dataset.groupKey);
            }
        });
        groupOrder.push('date'); // Date is always a grouping level.

        // 2. Transform the flat submission list into a dynamic hierarchical structure.
        const hierarchicalData = {};
        filteredData.forEach(sub => {
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
        
        // 3. Render the tree from the hierarchical data.
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

    // Re-render tree when a filter is changed
    Object.values(filters).forEach(filter => {
        filter.addEventListener('change', () => browser.renderTree());
    });

    // Initialize SortableJS for drag-and-drop grouping
    new Sortable(groupByFieldset, {
        animation: 150,
        ghostClass: 'sortable-ghost',
        onEnd: () => browser.renderTree()
    });

    // Add listeners to checkboxes to re-render on check/uncheck
    groupByFieldset.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
        checkbox.addEventListener('change', () => browser.renderTree());
    });

    toggleFiltersBtn.addEventListener('click', () => {
        filtersContainer.classList.toggle('hidden');
    });

    openPopupBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        popup.classList.toggle('active');
    });

    document.addEventListener('click', (event) => {
        if (!popup.contains(event.target) && !openPopupBtn.contains(event.target)) {
            popup.classList.remove('active');
        }
    });

    popup.addEventListener('click', (event) => {
        event.stopPropagation();
    });
});