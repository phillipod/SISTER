document.addEventListener('DOMContentLoaded', function() {
    const filterForm = document.querySelector('.filter-form');
    if (filterForm) {
        const filterInputs = filterForm.querySelectorAll('.filter-popup .form-control');
        let debounceTimer;

        function submitForm() {
            filterForm.submit();
        }

        filterInputs.forEach(input => {
            if (input.tagName.toLowerCase() === 'select') {
                input.addEventListener('change', submitForm);
            } else if (input.type === 'text') {
                input.addEventListener('keyup', () => {
                    clearTimeout(debounceTimer);
                    debounceTimer = setTimeout(submitForm, 500); // 500ms debounce
                });
            }
        });
    }

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

    // --- Original Dataset Label Selectors ---
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

    // --- New Build Detail Selectors (Platform, Type) ---
    document.querySelectorAll('.build-detail-select').forEach(select => {
        let initialDetailValue = select.value;

        select.addEventListener('focus', function() {
            initialDetailValue = this.value;
        });

        select.addEventListener('change', function() {
            const buildId = this.dataset.buildId;
            const field = this.dataset.field;
            const value = this.value;
            const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

            fetch(`/admin/api/builds/${buildId}/update-details`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ field: field, value: value })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    this.style.borderColor = 'green';
                    setTimeout(() => { this.style.borderColor = '' }, 2000);
                } else {
                    alert('Error updating ' + field + ': ' + (data.error || 'Unknown error'));
                    this.value = initialDetailValue; // Revert on failure
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('An unexpected error occurred while updating the ' + field + '.');
                this.value = initialDetailValue; // Revert on failure
            });
        });
    });

    // --- Audit Log Modal Logic ---
    const modal = document.getElementById('auditLogModal');
    const closeBtn = modal.querySelector('.close-btn');
    const modalBuildIdSpan = document.getElementById('modalBuildId');
    const auditLogTableBody = document.querySelector('#auditLogTable tbody');

    document.querySelectorAll('.audit-log-icon').forEach(icon => {
        icon.addEventListener('click', function() {
            const buildId = this.dataset.buildId;
            modalBuildIdSpan.textContent = buildId.substring(0, 8) + '...';
            auditLogTableBody.innerHTML = '<tr><td colspan="5" style="text-align:center;">Loading...</td></tr>';
            modal.style.display = 'block';

            fetch(`/admin/api/builds/${buildId}/audit-log`)
                .then(response => response.json())
                .then(logs => {
                    auditLogTableBody.innerHTML = ''; // Clear loading message
                    if (logs.length > 0) {
                        logs.forEach(log => {
                            const row = `<tr>
                                <td>${log.changed_at}</td>
                                <td>${log.admin_user}</td>
                                <td>${log.field_changed}</td>
                                <td>${log.old_value}</td>
                                <td>${log.new_value}</td>
                            </tr>`;
                            auditLogTableBody.innerHTML += row;
                        });
                    } else {
                        auditLogTableBody.innerHTML = '<tr><td colspan="5" style="text-align:center;">No audit history found for this build.</td></tr>';
                    }
                })
                .catch(error => {
                    console.error('Error fetching audit log:', error);
                    auditLogTableBody.innerHTML = '<tr><td colspan="5" style="text-align:center; color: red;">Failed to load audit log.</td></tr>';
                });
        });
    });

    closeBtn.onclick = function() {
        modal.style.display = 'none';
    }

    window.onclick = function(event) {
        if (event.target == modal) {
            modal.style.display = 'none';
        }
    }
}); 