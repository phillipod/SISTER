document.addEventListener('DOMContentLoaded', function() {
    // Logic for submit button spinner
    const form = document.getElementById('uploadForm');
    const submitButton = document.getElementById('submitBtn');
    if (form && submitButton) {
        form.addEventListener('submit', function(event) {
            if (!form.checkValidity()) {
                return;
            }
            const buttonText = submitButton.querySelector('.button-text');
            if (buttonText) {
                buttonText.textContent = 'Submitting...';
            }
            submitButton.classList.add('submitting');
            submitButton.disabled = true;
        });
    } else {
        console.error('Submit button or form not found!');
    }

    // Logic for adding and removing builds
    const container = document.getElementById('buildsContainer');
    let buildIndexCounter = container.children.length; // Initialize based on current number of builds

    function reindexBuilds() {
        const buildSections = container.querySelectorAll('.build-section');
        buildSections.forEach((section, index) => {
            section.setAttribute('data-build-index', index);

            // Update header for additional builds (index 0 is the primary build)
            const header = section.querySelector('h3');
            if (index > 0) {
                header.textContent = `Additional Build #${index}`;
            }

            // Update name attributes for all inputs inside
            section.querySelector('input[name^="build_platform_"]').name = `build_platform_${index}`;
            section.querySelector('input[name^="build_type_"]').name = `build_type_${index}`;
            section.querySelector('input[name^="screenshots_"]').name = `screenshots_${index}`;
        });
        // Reset the counter to the new total number of builds
        buildIndexCounter = buildSections.length;
    }

    const addBuildButton = document.getElementById('addBuildBtn');
    if (addBuildButton) {
        addBuildButton.addEventListener('click', function() {
            const buildIndex = buildIndexCounter; // Use the current counter

            const buildSection = document.createElement('div');
            buildSection.className = 'build-section';
            buildSection.setAttribute('data-build-index', buildIndex);
            
            buildSection.innerHTML = `
                <div class="build-header">
                    <h3>Additional Build #${buildIndex}</h3>
                    <button type="button" class="remove-build-btn">Remove Build</button>
                </div>
                <div class="screenshots-section">
                    <div class="build-platform-selection">
                        <h4>Build Platform</h4>
                        <div class="radio-group">
                            <label class="radio-option">
                                <input type="radio" name="build_platform_${buildIndex}" value="PC" checked>
                                PC
                            </label>
                            <label class="radio-option">
                                <input type="radio" name="build_platform_${buildIndex}" value="Console">
                                Console
                            </label>
                        </div>
                    </div>
                    <div class="build-type-selection">
                        <h4>Build Type</h4>
                        <div class="radio-group">
                            <label class="radio-option">
                                <input type="radio" name="build_type_${buildIndex}" value="space" checked>
                                Space Build
                            </label>
                            <label class="radio-option">
                                <input type="radio" name="build_type_${buildIndex}" value="ground">
                                Ground Build
                            </label>
                        </div>
                    </div>
                    <div class="file-upload-section">
                        <h4>Screenshots</h4>
                        <input type="file" name="screenshots_${buildIndex}" multiple class="file-input">
                    </div>
                </div>
            `;
            
            container.appendChild(buildSection);
            
            buildIndexCounter++; // Increment for the next potential addition
        });
    } else {
        console.error('Add build button not found!');
    }

    // Use event delegation for remove buttons. One listener handles all remove buttons.
    container.addEventListener('click', function(event) {
        if (event.target.classList.contains('remove-build-btn')) {
            const buildSectionToRemove = event.target.closest('.build-section');
            if (buildSectionToRemove) {
                buildSectionToRemove.remove();
                reindexBuilds(); // Re-index everything after a removal
            }
        }
    });
}); 