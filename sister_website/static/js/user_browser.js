document.addEventListener('DOMContentLoaded', () => {

    const userTreeRenderer = (data, treePane) => {
        if (!data || data.length === 0) {
            treePane.innerHTML = '<p>You have no submissions.</p>';
            return;
        }

        const treeHtml = data.map(sub => {
            const state = sub.is_withdrawn ? 'withdrawn' : sub.acceptance_state;
            const stateText = state.charAt(0).toUpperCase() + state.slice(1);
            const submissionScreenshots = sub.builds.flatMap(b => b.screenshots.map(sc => sc.id));

            return `
            <details class="submission-node" open>
                <summary data-group-screenshots="${submissionScreenshots.join(',')}" data-build-id="${sub.id}">
                    Submission from ${new Date(sub.created_at).toLocaleDateString()}
                    <span class="status-badge status-${state}">${stateText}</span>
                </summary>
                <ul>
                    ${sub.builds.map(build => `
                        <li>
                            <details class="build-node" open>
                                <summary data-group-screenshots="${build.screenshots.map(sc => sc.id).join(',')}" data-build-id="${build.id}">
                                    ${build.platform} - ${build.type}
                                </summary>
                                <ul>
                                    ${build.screenshots.map(sc => `
                                        <li>
                                            <a href="#" class="screenshot-link" data-screenshot-id="${sc.id}">
                                                ${sc.filename}
                                            </a>
                                        </li>
                                    `).join('')}
                                </ul>
                            </details>
                        </li>
                    `).join('')}
                </ul>
            </details>
        `}).join('');
        treePane.innerHTML = treeHtml;
    };

    const config = {
        treePaneId: 'tree-pane',
        previewPaneId: 'preview-pane',
        submissionInfoPaneId: 'submission-info',
        previewContentId: 'preview-content',
        dataUrl: '/api/me/submissions_data',
        treeRenderer: userTreeRenderer // The default mapBuilder in the class is sufficient
    };
    
    const browser = new ScreenshotBrowser(config);
    browser.initialize();
});