document.addEventListener('DOMContentLoaded', () => {
    // Configuration for user browser
    const config = {
        treePaneId: 'tree-pane',
        previewPaneId: 'preview-pane',
        submissionInfoPaneId: 'submission-info',
        previewContentId: 'preview-content',
        dataUrl: '/api/me/submissions_data',
        noResultsMessage: 'You have no submissions matching the current options.',
        userCanManage: true, // Allow user to manage their own submissions
        isAdminView: false, // This is not an admin view
        canResendConsent: false, // Users cannot resend consent emails
        showSubmissionEmail: false, // Users don't need to see their own email
        // API Endpoints
        logAccessTokenUrl: '/api/log-access-token/{log_id}',
        emailLogUrl: '/api/me/email_log/{log_id}',
        linkLogUrl: '/api/me/link_log/{log_id}',
        screenshotImageUrl: '/me/screenshot/{sc_id}'
    };
    
    // Initialize the browser with common UI setup
    const browser = new ScreenshotBrowser(config);
    browser.initialize();
});