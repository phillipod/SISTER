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
    let buildIndexCounter = 0; // Start from 1 since build 0 is already on the page
    const addBuildButton = document.getElementById('addBuildBtn');
    if (addBuildButton) {
        addBuildButton.addEventListener('click', function() {
            const container = document.getElementById('buildsContainer');
            const buildIndex = buildIndexCounter++; // Use and increment the counter

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
            
            // Add event listener to the new remove button
            const removeButton = buildSection.querySelector('.remove-build-btn');
            if (removeButton) {
                removeButton.addEventListener('click', function() {
                    buildSection.remove();
                });
            } else {
                 console.error('Could not find remove button for new build section.');
            }
        });
    } else {
        console.error('Add build button not found!');
    }
}); 