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
    initializeSecretLinks();
    initializePinStarButtons();
    initializeShareButtons();
    initializeNavbar();
    
    // Function to load content via AJAX
    function loadContent(url) {
        fetch(url, {
            method: 'GET',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': csrfToken,  // Include CSRF token if required
            }
        })
        .then(response => response.text())
        .then(html => {
            document.getElementById('content-container').innerHTML = html; // Load the response into the content container
            history.pushState(null, '', url);  // Update URL without page reload
            
            // Reinitialize after loading new content
            initializeSecretLinks();
            initializePinStarButtons();
            initializeShareButtons();
            initializeNavbar();
    
            // Reset focus and scroll position
            document.getElementById('content-container').focus();
            document.body.scrollTop = 0; // For Safari
            document.documentElement.scrollTop = 0; // For Chrome, Firefox, IE, and Opera
        })
        .catch(error => console.error('Error loading page:', error));
    }
    
    // Handle the navbar AJAX without the loading of the page
    document.querySelectorAll('.dynamic-link').forEach(link => {
        link.addEventListener('click', function(event) {
            event.preventDefault(); // Prevent the default anchor behavior
            const url = this.getAttribute('data-url'); // Get the URL from data attribute
            loadContent(url); // Call the function to load content
        });
    });
    
    // Add event listener for the logo link
    document.querySelectorAll('.logo-link').forEach(link => {
        link.addEventListener('click', function(event) {
            event.preventDefault(); // Prevent the default anchor behavior
            const url = this.getAttribute('data-url'); // Get the URL from data attribute
            loadContent(url); // Call the function to load content
        });
    });
    
    // Handle back/forward browser buttons
    window.addEventListener('popstate', function() {
        fetch(location.href, {
            method: 'GET',
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(response => response.text())
        .then(html => {
            document.getElementById('content-container').innerHTML = html;
            // Reinitialize after loading new content
            initializeSecretLinks();
            initializePinStarButtons();
            initializeShareButtons();
            initializeNavbar();
        })
        .catch(error => console.error('Error loading page:', error));
    });

    // Initialize secret links
    function initializeSecretLinks() {
        const secretLinks = document.querySelectorAll('.secret-link');
        const secretDetails = document.querySelectorAll('.secret-details');

        // Function to hide all secret details
        function hideAllSecrets() {
            secretDetails.forEach(function (detail) {
                detail.style.display = 'none';
            });
        }

        // Attach click event listener to each secret link
        secretLinks.forEach(function (link) {
            link.addEventListener('click', function (e) {
                e.preventDefault();  // Prevent the default anchor behavior
                const targetId = link.getAttribute('data-target');
                const targetElement = document.querySelector(targetId);
                
                // Hide all secrets first
                hideAllSecrets();

                // Show the selected secret details
                if (targetElement) {
                    targetElement.style.display = 'block';
                }
            });
        });
    }

    // Initializes the tab bar
    function initializeNavbar() {
        // Reinitialize navbar or tab bar logic if needed
        const tabLinks = document.querySelectorAll('.nav-link'); // Adjust based on your HTML structure
        tabLinks.forEach(link => {
            link.addEventListener('click', function() {
                // Custom logic for tab activation
            });
        });
    }

    // Initialize Pin and Star buttons
    function initializePinStarButtons() {
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
    }

    // showFlashMessage function to use the existing flash-messages container
    function showFlashMessage(message, category = 'success') {
        const flashContainer = document.getElementById('flash-messages');
    
        if (!flashContainer) {
            console.error('Flash container not found!');
            return;
        }
    
        // Create an alert div for the flash message
        const alert = document.createElement('div');
        alert.className = `alert alert-${category} text-center mt-3 alert-dismissible fade show`;
        alert.role = 'alert';
        alert.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;
    
        flashContainer.appendChild(alert);
    
        // Automatically remove the flash message after 3 seconds
        setTimeout(() => {
            if (flashContainer.contains(alert)) {
                flashContainer.removeChild(alert);
            }
        }, 3000);
    }

    // Initialize share forms
    function initializeShareButtons() {
        // Add event listener for the share form submission
        document.querySelectorAll('[id^="shareForm-"]').forEach(form => {
            form.addEventListener('submit', function(event) {
                event.preventDefault(); // Prevent default form submission
                
                const url = this.action; // Get the form action URL
                const formData = new FormData(this); // Create a FormData object to hold the form data
                
                fetch(url, {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': csrfToken // Include CSRF token if required
                    }
                })
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Network response was not ok');
                    }
                    return response.json(); // Parse JSON response
                })
                .then(data => {
                    if (data.success) {
                        showFlashMessage(data.message); // Display success message
    
                        // Clear the modal fields
                        clearModalFields(this); // Call to clear modal fields
                        
                        // Get and close the modal only within a successful submission
                        const modalElement = this.closest('.modal'); // Find the closest modal element
                        if (modalElement) {
                            try {
                                const modalInstance = bootstrap.Modal.getInstance(modalElement) || new bootstrap.Modal(modalElement);
                                modalInstance.hide();  // Close the modal
                                const backdrop = document.querySelector('.modal-backdrop');
                                if (backdrop) {
                                    backdrop.classList.remove('show'); // Remove the 'show' class
                                    backdrop.remove(); // Clean up backdrop
                                }
                                console.log('Modal closed successfully.');
                            } catch (error) {
                                console.error('Error closing modal:', error);
                            }
                        } else {
                            console.warn('No modal element found for closing.');
                        }
                    } else {
                        showFlashMessage(data.message, 'danger'); // Display error message if not successful
                    }
                })
                .catch(error => console.error('Error submitting form:', error));
            });
        });

        // Add event listener for modal opening
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('show.bs.modal', function () {
                // Ensure scrolling is disabled when modal is opened
                document.body.style.overflow = 'hidden';
            });

            modal.addEventListener('hidden.bs.modal', function () {
                const backdrop = document.querySelector('.modal-backdrop');
                if (backdrop) {
                    backdrop.remove(); // Clean up backdrop on modal close
                }
                document.body.style.overflow = ''; // Ensure scrolling is enabled
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
        function resetModalFields(modal) {
            if (!modal) {
                console.warn('No modal element provided to resetModalFields.');
                return; // Exit if modal is not provided
            }

            // Use valid selectors to target elements
            const dateFieldSelect = modal.querySelector('.date-field-select');
            const dateLabelSelect = modal.querySelector('.date-label-select');
            const timeFieldSelect = modal.querySelector('.time-field-select');
            const timeLabelSelect = modal.querySelector('.time-label-select');
            const dateFieldPublic = modal.querySelector('.date-field-public');
            const dateLabelPublic = modal.querySelector('.date-label-public');

            // Check if elements exist before trying to set styles
            if (dateFieldSelect) dateFieldSelect.style.display = 'none';
            if (dateLabelSelect) dateLabelSelect.style.display = 'none';
            if (timeFieldSelect) timeFieldSelect.style.display = 'none';
            if (timeLabelSelect) timeLabelSelect.style.display = 'none';
            if (dateFieldPublic) dateFieldPublic.style.display = 'none';
            if (dateLabelPublic) dateLabelPublic.style.display = 'none';
        }

        
        // Toggle public share date field
        document.querySelectorAll('.toggle-date-button-public').forEach(function(button) {
            button.addEventListener('click', function() {
                var targetPopup = this.closest('.modal');
                toggleVisibility(targetPopup.querySelector('.date-field-public'));
                toggleVisibility(targetPopup.querySelector('.date-label-public'));
            });
        });

        // Function to clear modal fields
        function clearModalFields(form) {
            // Reset the form fields
            form.reset();

            // Reset visibility of fields if required
            const modal = form.closest('.modal');
            resetModalFields(modal); // Call to reset modal fields visibility
        }

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

    // Select elements
    const fileInput = document.getElementById('fileInput');
    const fileNameDisplay = document.getElementById('fileName');
    const previewContainer = document.getElementById('filePreview');
    const previewImage = document.getElementById('previewImage');
    const errorFlash = document.getElementById('errorFlash');
    const uploadProgressContainer = document.getElementById('uploadProgressContainer');
    const uploadProgress = document.getElementById('uploadProgress');
    

    const MAX_FILE_SIZE_MB = 500;
    const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

    if (fileInput) {
        fileInput.addEventListener('change', function () {
            const file = this.files[0];
            const fileName = file ? file.name : '';
            fileNameDisplay.textContent = fileName;

            // Reset error and progress
            if (errorFlash) errorFlash.style.display = 'none';
            if (uploadProgressContainer) uploadProgressContainer.style.display = 'none';
            if (uploadProgress) {
                uploadProgress.style.width = '0%';
                uploadProgress.textContent = '0%';
            }

            if (file && file.size > MAX_FILE_SIZE_BYTES) {
                errorFlash.textContent = `Error: The file size exceeds ${MAX_FILE_SIZE_MB} MB. Please select a smaller file.`;
                errorFlash.style.display = 'block';
                fileInput.value = '';
                fileNameDisplay.textContent = '';
                previewContainer.style.display = 'none';
                return;
            }

            if (file && file.type.startsWith('image/')) {
                const reader = new FileReader();
                reader.onload = function (e) {
                    previewImage.src = e.target.result;
                    previewContainer.style.display = 'block';
                };
                reader.readAsDataURL(file);
            } else {
                previewContainer.style.display = 'none';
            }

            // Start uploading the file immediately after selection
            uploadFileWithProgress();
        });
    }

    // Function to handle file upload with progress
    function uploadFileWithProgress() {
        const file = fileInput.files[0];
        if (!file) return;
    
        const formData = new FormData();
        formData.append('file', file);
    
        const xhr = new XMLHttpRequest();
        
        // Open the connection first
        xhr.open('POST', '/upload', true);
        
        // Now set the CSRF token in the request header
        const csrfToken = document.querySelector('input[name="csrf_token"]').value; // Make sure this selector matches your CSRF token input
        xhr.setRequestHeader('X-CSRF-Token', csrfToken);
        
        uploadProgressContainer.style.display = 'block';
    
        xhr.upload.addEventListener('progress', function (e) {
            if (e.lengthComputable) {
                const percentComplete = Math.round((e.loaded / e.total) * 100);
                uploadProgress.style.width = `${percentComplete}%`;
                uploadProgress.textContent = `${percentComplete}%`;
            }
        });
    
        xhr.addEventListener('load', function () {
            if (xhr.status === 200) {
                const response = JSON.parse(xhr.responseText);
                const filename = response.filename;
                document.getElementById('uploadedFileName').value = filename;
                uploadProgress.textContent = 'Upload Complete';
            } else {
                console.error(`Upload failed: ${xhr.status} - ${xhr.responseText}`); // Log status code and response text
                errorFlash.textContent = 'Upload failed. Please try again.';
                errorFlash.style.display = 'block';
                uploadProgressContainer.style.display = 'none';
            }
        });
    
        // Send the form data
        xhr.send(formData);
    }


    // Close popup function
    window.closePopup = function(index) {
        document.getElementById('share-popup-' + index).style.display = 'none';
    };
});


