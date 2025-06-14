document.addEventListener('DOMContentLoaded', function() {
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

    const mapBuilder = (data) => {
        const map = {};
        if (!data) return map;
        data.forEach(sc => {
            map[sc.id] = sc;
        });
        return map;
    };

    const adminTreeRenderer = (data, treePane) => {
        const platformFilter = filters.platform.value;
        const typeFilter = filters.type.value;
        const acceptedFilter = filters.accepted.value;

        treePane.innerHTML = '';
        
        const filteredData = data.filter(sc => {
            const platformMatch = platformFilter === 'all' || sc.platform === platformFilter;
            const typeMatch = typeFilter === 'all' || sc.type === typeFilter;
            const acceptedMatch = acceptedFilter === 'all' || sc.acceptance_state === acceptedFilter;
            return platformMatch && typeMatch && acceptedMatch;
        });

        if (filteredData.length === 0) {
            treePane.innerHTML = '<p>No screenshots match the current filters.</p>';
            return;
        }

        const groupOrder = [];
        const groupByCheckboxes = groupByFieldset.querySelectorAll('input[type="checkbox"]');
        groupByCheckboxes.forEach(checkbox => {
            if (checkbox.checked) {
                groupOrder.push(checkbox.dataset.groupKey);
            }
        });
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

        const createDetails = (summaryText, parentElement, allScreenshots, depth = 0) => {
            const details = document.createElement('details');
            details.open = true;
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
            return details;
        };

        const renderNode = (node, parentElement, depth = 0) => {
            for (const key in node) {
                const childNode = node[key];
                
                const isSubmissionContainer = Object.values(childNode).every(val => Array.isArray(val));

                if (isSubmissionContainer) {
                    const dateDetails = createDetails(key, parentElement, getAllScreenshots(childNode), depth);
                     for (const subId in childNode) {
                        const subScreenshots = childNode[subId];
                        if (subScreenshots.length > 0) {
                            const firstSc = subScreenshots[0];
                            const subLabel = `Submission ${firstSc.submission_id.substring(0, 8)}`;
                            const subDetails = createDetails(subLabel, dateDetails, subScreenshots, depth + 1);
                            subDetails.dataset.buildId = firstSc.build_id;

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
                            subDetails.appendChild(scUl);
                        }
                    }
                } else {
                    const details = createDetails(key, parentElement, getAllScreenshots(childNode), depth);
                    renderNode(childNode, details, depth + 1);
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