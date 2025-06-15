document.addEventListener('DOMContentLoaded', function() {
    // Get initial build ID from script tag if available
    const scriptTag = document.getElementById('admin-browser-script');
    const initialBuildId = scriptTag ? scriptTag.dataset.buildId : null;

    // Configuration for admin submission browser
    const config = {
        treePaneId: 'tree-pane',
        previewPaneId: 'preview-pane',
        submissionInfoPaneId: 'submission-info',
        previewContentId: 'preview-content',
        dataUrl: '/admin/api/submissions',
        noResultsMessage: 'No submissions match the current filters.',
        // API Endpoints
        logAccessTokenUrl: '/api/log-access-token/{log_id}',
        emailLogUrl: '/admin/api/email_log/{log_id}',
        linkLogUrl: '/admin/api/link_log/{log_id}',
        screenshotImageUrl: '/admin/screenshot/{sc_id}',
        userCanManage: false, // Admins should not be able to accept/decline licenses
        isAdminView: true, // This is an admin view
        canResendConsent: true, // Admins can resend consent emails
        showSubmissionEmail: true // Admins need to see submission email addresses
    };

    // Initialize the browser with common UI setup
    const browser = new ScreenshotBrowser(config);
    browser.initialize(initialBuildId);
}); 