window.addEventListener('DOMContentLoaded', () => {
    // Scroll handling for the main navigation
    let scrollPos = 0;
    const mainNav = document.getElementById('mainNav');

    if (!mainNav) {
        console.error('Element with ID "mainNav" not found.');
        return; // Exit if mainNav is not found
    }

    const headerHeight = mainNav.clientHeight;

    window.addEventListener('scroll', function() {
        const currentTop = document.body.getBoundingClientRect().top * -1;
        if (currentTop < scrollPos) {
            // Scrolling Up
            if (currentTop > 0 && mainNav.classList.contains('is-fixed')) {
                mainNav.classList.add('is-visible');
            } else {
                mainNav.classList.remove('is-visible', 'is-fixed');
            }
        } else {
            // Scrolling Down
            mainNav.classList.remove('is-visible');
            if (currentTop > headerHeight && !mainNav.classList.contains('is-fixed')) {
                mainNav.classList.add('is-fixed');
            }
        }
        scrollPos = currentTop;
    });

    // CSRF token for AJAX requests
    const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

    // Toggle Pin functionality
    document.querySelectorAll('.toggle-pin').forEach(function(button) {
        button.addEventListener('click', function() {
            var secretId = this.getAttribute('data-id');
            fetch(`/toggle_pin/${secretId}`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    let icon = this.querySelector('i');
                    icon.classList.toggle('bi-pin');
                    icon.classList.toggle('bi-pin-fill');
                }
            });
        });
    });

    // Toggle Star functionality
    document.querySelectorAll('.toggle-star').forEach(function(button) {
        button.addEventListener('click', function() {
            var secretId = this.getAttribute('data-id');
            fetch(`/toggle_star/${secretId}`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    let icon = this.querySelector('i');
                    icon.classList.toggle('bi-star');
                    icon.classList.toggle('bi-star-fill');
                }
            });
        });
    });

    // Share button click event
    document.querySelectorAll('.share-button').forEach(function(button) {
        button.addEventListener('click', function() {
            var targetPopup = this.getAttribute('data-target');
            document.querySelector(targetPopup).style.display = 'block';
            // Reset fields in the modal
            resetModalFields(targetPopup);
        });
    });

    // Function to reset modal fields
    function resetModalFields(targetPopup) {
        const modal = document.querySelector(targetPopup);
        const dateFieldSelect = modal.querySelector('.date-field-select');
        const dateLabelSelect = modal.querySelector('.date-label-select');
        const timeFieldSelect = modal.querySelector('.time-field-select');
        const timeLabelSelect = modal.querySelector('.time-label-select');
        const dateFieldPublic = modal.querySelector('.date-field-public');
        const dateLabelPublic = modal.querySelector('.date-label-public');

        // Initialize states
        dateFieldSelect.style.display = 'none';
        dateLabelSelect.style.display = 'none';
        timeFieldSelect.style.display = 'none';
        timeLabelSelect.style.display = 'none';
        dateFieldPublic.style.display = 'none';
        dateLabelPublic.style.display = 'none';
    }

    // Toggle public share date field
    document.querySelectorAll('.toggle-date-button-public').forEach(function(button) {
        button.addEventListener('click', function() {
            var targetPopup = this.closest('.modal');
            toggleVisibility(targetPopup.querySelector('.date-field-public'));
            toggleVisibility(targetPopup.querySelector('.date-label-public'));
        });
    });

    // Toggle email input visibility
    document.querySelectorAll('.toggle-email-button').forEach(function(button) {
        button.addEventListener('click', function() {
            var targetPopup = this.closest('.modal');
            toggleVisibility(targetPopup.querySelector('.email-container'));
        });
    });

    // Toggle date and time visibility for Share via Email
    document.querySelectorAll('.toggle-date-button-email').forEach(function(button) {
        button.addEventListener('click', function() {
            var targetPopup = this.closest('.modal');
            toggleVisibility(targetPopup.querySelector('.date-field-email'));
            toggleVisibility(targetPopup.querySelector('.time-field-email'));
        });
    });

    // Function to toggle visibility
    function toggleVisibility(element) {
        element.style.display = (element.style.display === 'none' || element.style.display === '') ? 'block' : 'none';
    }

    // Deadline field visibility
    document.querySelectorAll('.modal').forEach(function(modal) {
        var confirmDeletionCheck = modal.querySelector('.form-check-input#confirmDeletionCheck');
        if (confirmDeletionCheck) {
            confirmDeletionCheck.addEventListener('change', function() {
                toggleDeadlineField(modal);
            });
        }
    });

    // Function to handle visibility of deadline date field
    function toggleDeadlineField(modal) {
        var confirmDeletionCheck = modal.querySelector('.form-check-input#confirmDeletionCheck');
        var publicSharingCheck = modal.querySelector('.form-check-input#publicSharingCheck');
        var deadlineDateContainer = modal.querySelector('.deadline-date-container');

        deadlineDateContainer.style.display = (confirmDeletionCheck.checked && publicSharingCheck.checked) ? 'block' : 'none';
    }

    // Upgrade plan event listener
    var confirmUpgradeButton = document.getElementById('confirm-upgrade');
    if (confirmUpgradeButton) {
        confirmUpgradeButton.addEventListener('click', function() {
            var planSelect = document.getElementById("upgrade-form").querySelector("select[name='plan_id']");
            if (planSelect.value == 0) {
                alert("Please select a valid plan to upgrade.");
                return false; // Prevent form submission
            } else {
                document.getElementById('upgrade-form').submit();
            }
        });
    }

    // Pay Now Modal Logic
    const savedCardRadio = document.getElementById('savedCard');
    const newCardRadio = document.getElementById('newCard');
    const newCardDetails = document.getElementById('newCardDetails');

    if (savedCardRadio && newCardRadio && newCardDetails) {
        savedCardRadio.addEventListener('change', function() {
            if (savedCardRadio.checked) {
                newCardDetails.style.display = 'none';
            }
        });

        newCardRadio.addEventListener('change', function() {
            if (newCardRadio.checked) {
                newCardDetails.style.display = 'block';
            }
        });
    }

    // Last login
    const loginHistoryModal = document.getElementById('loginHistoryModal');
    if (loginHistoryModal) {
        loginHistoryModal.addEventListener('show.bs.modal', function() {
            fetch('/api/login-history')
                .then(response => response.json())
                .then(data => {
                    const loginHistoryList = document.getElementById('loginHistoryList');
                    loginHistoryList.innerHTML = '';
                    data.forEach(login => {
                        const listItem = document.createElement('li');
                        listItem.className = 'list-group-item';
                        listItem.textContent = `Login Time: ${login.login_time}, IP Address: ${login.ip_address}`;
                        loginHistoryList.appendChild(listItem);
                    });
                })
                .catch(error => {
                    console.error('Error fetching login history:', error);
                });
        });
    }

    // File upload and preview functionality
    const fileInput = document.getElementById('fileInput');
    const fileNameDisplay = document.getElementById('fileName');
    const previewContainer = document.getElementById('filePreview');
    const previewImage = document.getElementById('previewImage');
    const errorFlash = document.getElementById('errorFlash'); // Assuming this is your error message element

    const MAX_FILE_SIZE_MB = 500; // Maximum file size in MB
    const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024; // Convert MB to bytes

    if (fileInput) {
        fileInput.addEventListener('change', function () {
            const file = this.files[0];
            const fileName = file ? file.name : '';
            fileNameDisplay.textContent = fileName;

            // Reset error message
            if (errorFlash) {
                errorFlash.style.display = 'none';
            }

            // Check file size
            if (file && file.size > MAX_FILE_SIZE_BYTES) {
                // Show error flash if the file is too large
                if (errorFlash) {
                    errorFlash.textContent = `Error: The file size exceeds ${MAX_FILE_SIZE_MB} MB. Please select a smaller file.`;
                    errorFlash.style.display = 'block'; // Show the error message
                }
                // Clear the file input
                fileInput.value = '';
                fileNameDisplay.textContent = '';
                previewContainer.style.display = 'none'; // Hide the preview
                return; // Exit the function
            }

            // Handle image preview if the file is an image
            if (file && file.type.startsWith('image/')) {
                const reader = new FileReader();
                reader.onload = function (e) {
                    previewImage.src = e.target.result;
                    previewContainer.style.display = 'block'; // Show the preview
                };
                reader.readAsDataURL(file);
            } else {
                previewContainer.style.display = 'none'; // Hide the preview if not an image
            }
        });
    }

    

    // Close popup function
    window.closePopup = function(index) {
        document.getElementById('share-popup-' + index).style.display = 'none';
    };
});


