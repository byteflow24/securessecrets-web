window.addEventListener('DOMContentLoaded', () => {
    // Scroll handling for the main navigation
    let scrollPos = 0;
    const mainNav = document.getElementById('mainNav');

    if (!mainNav) {
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
    // initializeShareButtons();
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
    function showFlashMessage(message, type = 'success') {
        const flashContainer = document.getElementById('flash-messages');
        if (!flashContainer) return;
    
        const flashMessage = document.createElement('div');
        flashMessage.className = `alert alert-${type} alert-dismissible fade show`;
        flashMessage.role = 'alert';
        flashMessage.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;
    
        flashContainer.appendChild(flashMessage);
    
        // Automatically remove after 5 seconds
        setTimeout(() => flashMessage.remove(), 5000);
    }

    // New secret
    const fileInput = document.getElementById('fileInput');
    const fileNameDisplay = document.getElementById('fileName');
    const previewContainer = document.getElementById('filePreview');
    const previewImage = document.getElementById('previewImage');
    const errorFlash = document.getElementById('errorFlash');
    const uploadProgressContainer = document.getElementById('uploadProgressContainer');
    const uploadProgress = document.getElementById('uploadProgress');
    const saveButton = document.querySelector('button[type="submit"]');

    // Constants for file size limits
    const MAX_FILE_SIZE_MB = 500;
    const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

    // Handle file selection
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

            // Validate file size
            if (file && file.size > MAX_FILE_SIZE_BYTES) {
                errorFlash.textContent = `Error: The file size exceeds ${MAX_FILE_SIZE_MB} MB. Please select a smaller file.`;
                errorFlash.style.display = 'block';
                fileInput.value = '';
                fileNameDisplay.textContent = '';
                previewContainer.style.display = 'none';
                return;
            }

            // Preview image files
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
        });
    }

    // Upload file with progress
    function uploadFileWithProgress(file) {
        return new Promise((resolve, reject) => {
            const formData = new FormData();
            formData.append('file', file);

            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/upload', true);

            // Set CSRF token
            const csrfToken = document.querySelector('input[name="csrf_token"]').value;
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
                    if (response.filename) {
                        document.getElementById('uploadedFileName').value = response.filename; // Set hidden input
                        resolve(response.filename);
                    } else {
                        reject('Filename missing from upload response');
                    }
                } else {
                    reject('Upload failed');
                }
            });

            xhr.addEventListener('error', function () {
                reject('Upload error');
            });

            xhr.send(formData);
        });
    }

    // Form submission handler
    document.querySelector("#newSecretModal form").addEventListener("submit", function (event) {
        event.preventDefault();

        const form = event.target;
        const formData = new FormData(form);
        const file = fileInput.files[0];

        if (file) {
            // Ensure file is uploaded before submission
            uploadFileWithProgress(file)
                .then((filename) => {
                    document.getElementById('uploadedFileName').value = filename; // Confirm filename is set

                    // Append updated form data
                    formData.set('uploadedFileName', filename);

                    // Submit the form
                    return fetch("/add-secret", {
                        method: "POST",
                        body: formData,
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                        },
                    });
                })
                .then(response => response.json())
                .then(data => handleFormResponse(data, form))
                .catch(error => {
                    console.error("Error:", error);
                    alert("An error occurred while adding the secret.");
                });
        } else {
            // Ensure the hidden input has a value
            const hiddenFileName = document.getElementById('uploadedFileName').value;
            if (!hiddenFileName) {
                alert("File upload incomplete. Please wait until the file is fully uploaded.");
                return;
            }

            // Submit the form directly
            fetch("/add-secret", {
                method: "POST",
                body: formData,
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
            })
            .then(response => response.json())
            .then(data => handleFormResponse(data, form))
            .catch(error => {
                console.error("Error:", error);
                alert("An error occurred while adding the secret.");
                closeModal(document.querySelector("#newSecretModal form")); // Clean up on error
            });
        }
    });

    function closeModal(form) {
        const modalElement = form.closest('.modal'); // Find the closest modal container
        if (modalElement) {
            const modalInstance = bootstrap.Modal.getInstance(modalElement) || new bootstrap.Modal(modalElement);
            modalInstance.hide(); // Properly close the modal
        }
    
        // Ensure the body styles are reset
        document.body.style.overflow = ''; 
        document.body.style.paddingRight = ''; // Reset padding if a scrollbar was present
    
        // Ensure leftover backdrops are removed
        const backdrops = document.querySelectorAll('.modal-backdrop');
        backdrops.forEach(backdrop => backdrop.remove());

        // Reset file input and associated elements
        fileInput.value = ''; // Reset file input
        fileNameDisplay.textContent = ''; // Reset file name display
        previewContainer.style.display = 'none'; // Hide file preview
        previewImage.src = ''; // Reset preview image
        if (errorFlash) errorFlash.style.display = 'none'; // Hide error flash
    }

    document.querySelector("#newSecretModal").addEventListener("hidden.bs.modal", () => {
        // Remove any remaining backdrop elements
        const backdrops = document.querySelectorAll('.modal-backdrop');
        backdrops.forEach(backdrop => backdrop.remove());
    
        // Reset body styles
        document.body.style.overflow = ''; 
        document.body.style.paddingRight = '';
    });

    const modalElement = document.querySelector("#newSecretModal");
    if (modalElement) {
        new bootstrap.Modal(modalElement); // Initialize modal if not already initialized
    }

    function handleFormResponse(data, form) {
        if (data.success) {
            const newSecretHTML = `
                <a href="#" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center secret-link">
                    <span>${data.title}</span>
                    <small>${data.date}</small>
                </a>
            `;
            document.querySelector("#accordionSecretsList").insertAdjacentHTML("afterbegin", newSecretHTML);

             // Reset the form and close the modal with cleanup
            form.reset();
            closeModal(form); // Use the new closeModal function

            // Reset file input and preview after successful form submission
            fileInput.value = ''; // Reset file input
            fileNameDisplay.textContent = ''; // Reset file name display
            previewContainer.style.display = 'none'; // Hide file preview
            previewImage.src = ''; // Reset preview image
            if (errorFlash) errorFlash.style.display = 'none'; // Hide error flash
        } else {
            alert(data.error || "An error occurred.");
        }
    }

    // Initialize share forms
    function initializeShareButtons() {
        // Add event listener for the share form submission
        document.querySelectorAll('[id^="shareForm-"]').forEach(form => {
            form.removeEventListener('submit', handleSubmit); // Remove previous listener
            form.addEventListener('submit', handleSubmit); 
            form.addEventListener('submit', function(event) {
                event.preventDefault();
    
                // Clear previous errors
                this.querySelectorAll('.validation-error').forEach(el => el.remove());
                this.querySelectorAll('.is-invalid').forEach(el => el.classList.remove('is-invalid'));
    
                const sharingType = this.querySelector('input[name="sharing_type"]').value;
                const datePeriodInput = this.querySelector('input[name="date_period"]');
                const dateInput = this.querySelector('input[name="date"]');
                const timeInput = this.querySelector('input[name="time"]');
    
                let isValid = true;
    
                if (sharingType === "last_login" && (!datePeriodInput || !datePeriodInput.value.trim())) {
                    isValid = false;
                    addValidationError(datePeriodInput, "Please set the period for Last Login Check.");
                }
    
                if (sharingType === "scheduled") {
                    if (!dateInput || !dateInput.value.trim()) {
                        isValid = false;
                        addValidationError(dateInput, "Please specify a date.");
                    }
                    if (!timeInput || !timeInput.value.trim()) {
                        isValid = false;
                        addValidationError(timeInput, "Please specify a time.");
                    }
                }
    
                if (!isValid) return; // Stop submission if validation fails
    
                const url = this.action;
                const formData = new FormData(this);
    
                fetch(url, {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': csrfToken 
                    }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        // Show success flash message
                        showFlashMessage(data.message, 'success');
                
                        // Close the modal
                        closeModal(this);
                
                        // Optional: Clear form fields
                        clearModalFields(this);
                    } else if (data.errors) {
                        // Show validation errors
                        Object.entries(data.errors).forEach(([field, messages]) => {
                            const inputElement = this.querySelector(`[name="${field}"]`);
                            if (inputElement) {
                                addValidationError(inputElement, messages.join(', '));
                            }
                        });
                    } else {
                        // General error handling
                        showFlashMessage(data.message || 'An error occurred.', 'danger');
                    }
                })
                .catch(error => {
                    console.error('Error submitting form:', error);
                    showFlashMessage('An unexpected error occurred.', 'danger');
                });
            });
        });

        // Helper function to display error messages
        function addValidationError(inputElement, errorMessage) {
            inputElement.classList.add('is-invalid');
            const errorDiv = document.createElement('div');
            errorDiv.className = 'validation-error text-danger small mt-1';
            errorDiv.textContent = errorMessage;
        
            // Add error after input element
            inputElement.parentNode.insertBefore(errorDiv, inputElement.nextSibling);
        }
    
        // Modal opening and closing events
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('show.bs.modal', function() {
                document.body.style.overflow = 'hidden';
            });
    
            modal.addEventListener('hidden.bs.modal', function() {
                const backdrop = document.querySelector('.modal-backdrop');
                if (backdrop) {
                    backdrop.classList.remove('show');
                    backdrop.remove();
                }
                document.body.style.overflow = '';
            });
        });
    
        // Share button click event
        document.querySelectorAll('.share-button').forEach(button => {
            button.addEventListener('click', function () {
                const targetPopup = this.getAttribute('data-target');
                const modalElement = document.querySelector(targetPopup);
    
                if (modalElement) {
                    let modalInstance = bootstrap.Modal.getInstance(modalElement);
                    if (modalInstance) {
                        modalInstance.dispose(); // Dispose of previous instance
                    }
                    modalInstance = new bootstrap.Modal(modalElement); // Create a new instance
                    resetModalFields(modalElement);
                    modalInstance.show();
                }
            });
        });
    
        // Function to reset modal fields
        function resetModalFields(modal) {
            if (!modal) {
                console.warn('No modal element provided to resetModalFields.');
                return;
            }
        
            modal.querySelectorAll('.validation-error').forEach(el => el.remove()); // Remove errors
            modal.querySelectorAll('.is-invalid').forEach(el => el.classList.remove('is-invalid')); // Clear invalid states
        
            const scheduledDateFields = modal.querySelectorAll('.date-field-email-scheduled, .time-field-email-scheduled');
            scheduledDateFields.forEach(field => field.style.display = 'block'); // Ensure fields are visible
        }
    
        // Function to clear modal fields
        function clearModalFields(form) {
            form.reset();
    
            const modal = form.closest('.modal');
            resetModalFields(modal); // Call to reset modal fields visibility
        }
    
        // Closing modal with cleanup
        function closeModal(form) {
            const modalElement = form.closest('.modal');
            if (modalElement) {
                const modalInstance = bootstrap.Modal.getInstance(modalElement) || new bootstrap.Modal(modalElement);
                modalInstance.hide(); // Close the modal
            }
            document.body.style.overflow = ''; // Reset body overflow
            const backdrop = document.querySelector('.modal-backdrop');
            if (backdrop) backdrop.remove(); // Remove the backdrop
        }
    
        // Email preparation for emailLogin
        try {
            initializeEmailInput('emailLogin', 'emailLoginContainer', 'emails_login');
            initializeEmailInput('emailScheduled', 'emailScheduledContainer', 'emails_scheduled');
        } catch (error) {
            console.error('Error initializing share buttons:', error);
        }
    
        function initializeEmailInput(inputId, containerId, hiddenFieldName) {
            const emailInput = document.getElementById(inputId);
            const emailInputContainer = document.getElementById(containerId);
            
            if (!emailInputContainer) {
                console.warn(`Email input container with ID '${containerId}' not found. Skipping initialization.`);
                return;
            }
        
            // Hidden field to store email addresses
            const hiddenEmailField = document.createElement('input');
            hiddenEmailField.type = 'hidden';
            hiddenEmailField.name = hiddenFieldName;
            emailInputContainer.appendChild(hiddenEmailField);
        
            let emails = [];
            const maxEmails = 5; // Set the maximum number of emails allowed
        
            // Add email on 'Enter' or comma key press
            emailInput.addEventListener('keydown', function(event) {
                if ((event.key === 'Enter' || event.key === ',') && emailInput.value.trim() !== '') {
                    event.preventDefault();
                    addEmail(emailInput.value.trim());
                    emailInput.value = '';
                }
            });
        
            // Add email on input blur (when the field loses focus)
            emailInput.addEventListener('blur', function() {
                addEmail(emailInput.value.trim());
                emailInput.value = '';
            });
        
            // Function to add email
            function addEmail(email) {
                if (email && !emails.includes(email)) {
                    if (emails.length >= maxEmails) {
                        alert(`You can only add up to ${maxEmails} emails.`);
                        return;
                    }
                    if (validateEmail(email)) {
                        emails.push(email);
                        updateEmails();
                        createEmailTag(email);
                        
                        // Remove placeholder after the first email is added
                        emailInput.placeholder = '';
                    } else {
                        alert("Please enter a valid email address.");
                    }
                }
            }
        
            // Function to create a visual email tag
            function createEmailTag(email) {
                const tag = document.createElement('span');
                tag.classList.add('email-tag');
                tag.innerHTML = `<span>${email}</span><span class="remove-tag" data-email="${email}">&times;</span>`;
                emailInputContainer.insertBefore(tag, emailInput);
        
                // Remove email on click
                tag.querySelector('.remove-tag').addEventListener('click', function() {
                    const emailToRemove = this.getAttribute('data-email');
                    emails = emails.filter(e => e !== emailToRemove);
                    updateEmails();
                    tag.remove();
                    
                    // Restore placeholder if all emails are removed
                    if (emails.length === 0) {
                        emailInput.placeholder = "Enter recipient's email/s";
                    }
                });
            }
        
            // Update hidden input with emails array
            function updateEmails() {
                hiddenEmailField.value = emails.join(','); // Store emails as comma-separated
            }
        
            // Validate email format
            function validateEmail(email) {
                const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                return re.test(email);
            }
        }
    
        // Toggle Required Fields Based on Sharing Type
        function toggleRequiredFields() {
            document.querySelectorAll('[id^="shareForm-"]').forEach(form => {
                const sharingType = form.querySelector('input[name="sharing_type"]:checked').value;
                const datePeriodInput = form.querySelector('input[name="date_period"]');
                const dateInput = form.querySelector('input[name="date"]');
                const timeInput = form.querySelector('input[name="time"]');
        
                if (sharingType === "last_login") {
                    datePeriodInput.required = true;
                    dateInput.required = false;
                    timeInput.required = false;
                } else if (sharingType === "scheduled") {
                    datePeriodInput.required = false;
                    dateInput.required = true;
                    timeInput.required = true;
                }
            });
        }
        
        // Attach toggle logic to sharing type changes
        document.querySelectorAll('input[name="sharing_type"]').forEach(input => {
            input.addEventListener('change', toggleRequiredFields);
        });                
    
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


    // Close popup function
    window.closePopup = function(index) {
        document.getElementById('share-popup-' + index).style.display = 'none';
    };
});


