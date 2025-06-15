document.addEventListener('DOMContentLoaded', function() {
    // Get initial build ID from script tag if available
    const scriptTag = document.getElementById('admin-browser-script');
    const initialBuildId = scriptTag ? scriptTag.dataset.buildId : null;

    // Configuration for admin browser
    const config = {
        treePaneId: 'tree-pane',
        previewPaneId: 'preview-pane',
        submissionInfoPaneId: 'submission-info',
        previewContentId: 'preview-content',
        dataUrl: '/admin/api/screenshots',
        noResultsMessage: 'No screenshots match the current filters.',
        // API Endpoints
        logAccessTokenUrl: '/api/log-access-token/{log_id}',
        emailLogUrl: '/admin/api/email_log/{log_id}',
        linkLogUrl: '/admin/api/link_log/{log_id}',
        screenshotImageUrl: '/admin/screenshot/{sc_id}'
    };

    // Initialize the browser with common UI setup
    const browser = new ScreenshotBrowser(config);
    browser.initialize(initialBuildId);
});