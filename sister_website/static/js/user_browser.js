document.addEventListener('DOMContentLoaded', () => {
    const userTreeRenderer = (data, treePane) => {
        if (data.length === 0) {
            treePane.innerHTML = '<p>You have no submissions.</p>';
            return;
        }

        const treeHtml = data.map(sub => `
            <details class="submission-node" open>
                <summary>
                    Submission (${new Date(sub.created_at).toLocaleDateString()})
                    <span class="status-badge status-${sub.acceptance_state}">${sub.acceptance_state}</span>
                </summary>
                <ul>
                    ${sub.builds.map(build => `
                        <li>
                            <details class="build-node" open>
                                <summary>${build.platform} - ${build.type}</summary>
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
        `).join('');
        treePane.innerHTML = treeHtml;
    };

    const config = {
        treePaneId: 'tree-pane',
        previewPaneId: 'preview-pane',
        previewImageId: 'preview-image',
        previewPlaceholderId: 'preview-placeholder',
        submissionInfoPaneId: 'submission-info',
        modalId: 'log-modal',
        dataUrl: '/api/me/submissions_data',
        treeRenderer: userTreeRenderer
    };

    new ScreenshotBrowser(config);
});