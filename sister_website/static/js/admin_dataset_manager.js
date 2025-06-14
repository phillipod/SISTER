document.addEventListener('DOMContentLoaded', function() {
    // New code for filter popups
    document.querySelectorAll('.filterable .filter-icon').forEach(trigger => {
        trigger.addEventListener('click', function(event) {
            event.stopPropagation();
            const popup = this.closest('.filterable').querySelector('.filter-popup');
            
            // Close other popups
            document.querySelectorAll('.filter-popup.active').forEach(activePopup => {
                if (activePopup !== popup) {
                    activePopup.classList.remove('active');
                }
            });

            // Toggle the current popup
            popup.classList.toggle('active');
        });
    });

    // Close popups when clicking anywhere else on the page
    document.addEventListener('click', function(event) {
        document.querySelectorAll('.filter-popup.active').forEach(popup => {
            const filterableHeader = popup.closest('.filterable');
            if (!filterableHeader.contains(event.target)) {
                popup.classList.remove('active');
            }
        });
    });

    // Stop propagation for clicks inside the popup to prevent it from closing
    document.querySelectorAll('.filter-popup').forEach(popup => {
        popup.addEventListener('click', function(event) {
            event.stopPropagation();
        });
    });

    const selectors = document.querySelectorAll('.dataset-label-select');
    let initialValue = null;

    selectors.forEach(select => {
        select.addEventListener('focus', function() {
            // Store the value when the user clicks on the select
            initialValue = this.value;
        });

        select.addEventListener('change', function() {
            const buildId = this.dataset.buildId;
            const labelId = this.value;
            const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

            fetch(`/admin/api/builds/${buildId}/set-label`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ label_id: labelId ? parseInt(labelId) : null })
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    this.style.borderColor = 'green';
                    setTimeout(() => { this.style.borderColor = '' }, 2000);
                } else {
                    alert('Error updating label: ' + (data.error || 'Unknown error'));
                    this.value = initialValue; // Revert on failure
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('An unexpected error occurred while updating the label.');
                this.value = initialValue; // Revert on failure
            });
        });
    });
}); 