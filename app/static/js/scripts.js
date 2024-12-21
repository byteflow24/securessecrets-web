// Google Analystic - Sessions Traker
window.dataLayer = window.dataLayer || [];
        function gtag(){dataLayer.push(arguments);}
        gtag('js', new Date());

        gtag('config', 'G-VV6NCJ0407');

window.addEventListener('DOMContentLoaded', () => {
    initializeSearchForm();
    initializeSecretLinks();
    initializeNewSecretForm();
    initializeShareButtons();
    initializeUpdateSecretForm();

    initializeReadSecret();
    initializeLastLoginHistory()
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

    
    // Toggles "Read More/Less" for overflowing secrets, expanding or collapsing content visibility. "Public Secrets Section"
    function initializeReadSecret() {
        const secrets = document.querySelectorAll('.secret-wrapper.clickable');

        secrets.forEach((wrapper) => {
            // Toggle expanded/collapsed state on click
            wrapper.addEventListener('click', function () {
                const isExpanded = wrapper.style['-webkit-line-clamp'] === 'unset';

                // Toggle styles
                wrapper.style['-webkit-line-clamp'] = isExpanded ? '1' : 'unset';
                wrapper.style['overflow'] = isExpanded ? 'hidden' : 'visible';
                wrapper.style['display'] = isExpanded ? '-webkit-box' : 'block';
            });

            // Optional: Add a hover effect for better UX
            wrapper.addEventListener('mouseover', function () {
                wrapper.style.backgroundColor = '#f9f9f9';
            });
            wrapper.addEventListener('mouseout', function () {
                wrapper.style.backgroundColor = '';
            });
        });
    }

    // CSRF token for AJAX requests
    const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
    function reinitializeAllComponents() {
        initializeSecretLinks();
        initializePinStarButtons();
        initializeShareButtons();
        initializeNavbar();
        initializeNewSecretForm();
        initializeSearchForm();
        initializeUpdateSecretForm();
        clearFlashMessages();

        initializeReadSecret();
        initializeLastLoginHistory()
    }
    
    // Function to load content via AJAX
    function loadContent(url) {
        fetch(url, {
            method: 'GET',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': csrfToken,  // Include CSRF token if required
            }
        })
        .then(response => {
            // Check if the user is unauthorized (session expired)
            if (response.status === 401) {
                window.location.href = '/';  // Redirect to login page
                return;  // Stop further processing
            }
    
            return response.text();
        })
        .then(html => {
            document.getElementById('content-container').innerHTML = html; // Load the response into the content container
            history.pushState(null, '', url);  // Update URL without page reload
            
            reinitializeAllComponents(); // Reinitialize everything

            // Add event listener for dynamically created dynamic links
            document.getElementById('content-container').addEventListener('click', function(event) {
                if (event.target.matches('.dynamic-link')) {
                    event.preventDefault();
                    loadContent(event.target.getAttribute('data-url'));
                }
            });
    
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
    window.addEventListener('popstate', function () {
        fetch(location.href, {
            method: 'GET',
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
            .then(response => {
                if (!response.ok) {
                    console.error(`Failed to load: ${response.status}`);
                    return;
                }
                return response.text();
            })
            .then(html => {
                if (html) {
                    const contentContainer = document.getElementById('content-container');
                    if (contentContainer) {
                        contentContainer.innerHTML = html;
    
                        // Reinitialize scripts to ensure everything works
                        reinitializeAllComponents();
                    }
                }
            })
            .catch(error => console.error('Error handling popstate:', error));
    });

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

    // Initialize secret links
    function initializeSecretLinks() {
        const secretLinks = document.querySelectorAll(".secret-link");
        const secretDetails = document.querySelectorAll(".secret-details");
        const noSecretAlert = document.getElementById("noSecretAlert");
        const secretsList = document.getElementById("accordionSecretsList");

        // Function to hide all secret details
        function hideAllSecrets() {
            secretDetails.forEach(secret => {
                secret.style.display = "none";
            });
        }

        // Function to check if any secret is visible and toggle the alert
        function checkSelection() {
            const anyVisible = Array.from(secretDetails).some(secret => secret.style.display === "block");

            // if (!secretsList) {
            //     console.error("Secrets list container not found.");
            //     return;
            // }

            if (noSecretAlert) {
                noSecretAlert.style.display = anyVisible ? "none" : "block";
            }
        }

        // Attach click event listener to each secret link
        secretLinks.forEach(link => {
            link.addEventListener("click", e => {
                e.preventDefault(); // Prevent default anchor behavior
                const targetId = link.getAttribute("data-target");
                const targetElement = document.querySelector(targetId);

                if (!targetElement) {
                    console.error(`No element found with selector: ${targetId}`);
                    return;
                }

                hideAllSecrets(); // Hide all secrets
                targetElement.style.display = "block"; // Show selected secret

                // Check if any secret is visible after the update
                checkSelection();
            });
        });

        // Initial check to ensure the alert is accurate on page load
        checkSelection();
    }
    
    // Search area
    function initializeSearchForm() {
        const searchForm = document.getElementById('searchForm');
        const secretsList = document.getElementById('accordionSecretsList');
    
        if (searchForm) {
            searchForm.addEventListener('submit', function (event) {
                event.preventDefault();
                console.log("Search form submitted");
                const formData = new FormData(searchForm);
                const url = searchForm.action;
    
                // Show a loading spinner
                secretsList.innerHTML = `
                    <div class="text-center py-4">
                        <span class="spinner-border text-primary" role="status"></span> Loading...
                    </div>
                `;
    
                fetch(url, {
                    method: 'POST',
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': document.querySelector('input[name="csrf_token"]').value,
                    },
                    body: formData,
                })
                    .then(response => {
                        console.log("Response received", response);
                        if (!response.ok) {
                            throw new Error(`HTTP Error: ${response.status}`);
                        }
                        return response.json();
                    })
                    .then(data => {
                        console.log("Response data:", data);
                        if (data.html) {
                            secretsList.innerHTML = data.html;
                            console.log("Secrets updated successfully");
    
                            // Update URL parameters for state
                            const url = new URL(window.location);
                            url.searchParams.set('search', formData.get('search') || '');
                            url.searchParams.set('date_filter', formData.get('date_filter') || '');
                            url.searchParams.set('alpha_filter', formData.get('alpha_filter') || '');
                            history.pushState(null, '', url);
    
                            // Reinitialize dynamic components
                            reinitializeAllComponents();
                        } else if (data.error) {
                            secretsList.innerHTML = `<div class="alert alert-danger">${data.error}</div>`;
                        }
                    })
                    .catch(error => {
                        console.error("Error during AJAX request:", error);
                        secretsList.innerHTML = `<div class="alert alert-danger">An error occurred: ${error.message}</div>`;
                    });
            });
        }
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
        setTimeout(() => {
            if (flashMessage.parentNode) {
                flashMessage.parentNode.removeChild(flashMessage);
            }
        }, 5000);
    }

    // clears only the currently displayed flash messages when transitioning between pages
    function clearFlashMessages() {
        const flashContainer = document.getElementById('flash-messages');
        if (flashContainer) {
            flashContainer.innerHTML = ''; // Clear the container content
        }
    }

    // Function for "New Secret" modal
    function initializeNewSecretForm() {
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
                            if (response.storageInfo) {
                                // Update storage info from the upload response if available
                                updateStorageInfo(response.storageInfo.used, response.storageInfo.total);
                            } else {
                                // Fetch storage info if not included in the response
                                fetch('/get-storage-info', {
                                    method: 'GET',
                                    headers: {
                                        'X-Requested-With': 'XMLHttpRequest',
                                    },
                                })
                                    .then(response => response.json())
                                    .then(data => {
                                        if (data.used !== undefined && data.total !== undefined) {
                                            updateStorageInfo(data.used, data.total);
                                        }
                                    })
                                    .catch(error => console.error('Error fetching storage info:', error));
                            }
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

        
        const newSecretForm = document.querySelector("#newSecretModal form");
        if (newSecretForm) {
            newSecretForm.addEventListener("submit", function (event) {
                event.preventDefault();
            
                const form = event.target;
                const secretField = form.querySelector('[name="secret"]');
                const hiddenFileName = document.getElementById('uploadedFileName')?.value;
                const file = fileInput?.files[0]; // Use optional chaining for file input
            
                // Error display element inside the modal
                const formError = document.getElementById("formError");
                formError.style.display = "none"; // Reset error display
            
                // Validate input: either a secret or a file must be provided
                if (!secretField.value.trim() && !hiddenFileName && !file) {
                    formError.style.display = "block";
                    formError.textContent = "Please provide a secret or upload a file.";
                    return;
                }
            
                const formData = new FormData(form);
            
                if (file) {
                    // If a file is present, upload it before submitting the form
                    uploadFileWithProgress(file)
                        .then((filename) => {
                            document.getElementById('uploadedFileName').value = filename; // Confirm filename is set
                            formData.set('uploadedFileName', filename); // Update formData
            
                            // Submit the form after file upload
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
                            formError.style.display = "block";
                            formError.textContent = "An error occurred while adding the secret.";
                        });
                } else {
                    // If no file is present, submit the form directly
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
                            formError.style.display = "block";
                            formError.textContent = "An error occurred while adding the secret.";
                        });
                }
            });
        }
        
        // Handle form response after submitting
        function handleFormResponse(data, form) {
            const formError = document.getElementById("formError");
            if (data.success) {
                const secretsList = document.querySelector("#accordionSecretsList");
                if (secretsList) {
                    const newSecretHTML = `
                        <a href="#" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center secret-link">
                            <span>${data.title}</span>
                            <small>${data.date}</small>
                        </a>`;
                    
                    // Remove "No secrets found" message if it exists
                    const noSecretsAlert = secretsList.querySelector(".alert-info");
                    if (noSecretsAlert) {
                        noSecretsAlert.remove();
                    }
        
                    // Add the new secret to the list
                    secretsList.insertAdjacentHTML("afterbegin", newSecretHTML);
                }
        
                // Update storage info if provided
                if (data.storageInfo) {
                    updateStorageInfo(data.storageInfo.used, data.storageInfo.total);
                } else {
                    fetch('/get-storage-info', {
                        method: 'GET',
                        headers: {
                            'X-Requested-With': 'XMLHttpRequest',
                        },
                    })
                        .then(response => response.json())
                        .then(data => {
                            if (data.used !== undefined && data.total !== undefined) {
                                updateStorageInfo(data.used, data.total);
                            }
                        })
                        .catch(error => console.error('Error fetching storage info:', error));
                }

                showFlashMessage(data.flash_message, 'success');
        
                // Reset the form and close the modal
                form.reset();
                closeModal(form);
        
                // Reset file input and preview
                resetFileInput();
            } else {
                formError.style.display = "block";
                formError.textContent = data.error || "An error occurred.";
            }
        }

        function updateStorageInfo(used, total) {
            const progressBar = document.querySelector('.progress-bar');
            const percentage = Math.round((used / total) * 100);
        
            progressBar.style.width = `${percentage}%`;
            progressBar.setAttribute('aria-valuenow', percentage);
            progressBar.textContent = `${percentage}%`;
        
            const storageText = document.querySelector('.text-muted');
            storageText.textContent = `${(used / (1024 * 1024)).toFixed(2)} MB used out of ${(total / (1024 * 1024)).toFixed(2)} MB`;
        }

        // Reset the file input and related elements
        function resetFileInput() {
            const fileInput = document.querySelector('#fileInput');
            const fileNameDisplay = document.querySelector('#fileName');
            const previewContainer = document.querySelector('#filePreview');
            const previewImage = document.querySelector('#previewImage');
            const errorFlash = document.querySelector('#errorFlash');

            fileInput.value = ''; // Reset file input
            fileNameDisplay.textContent = ''; // Reset file name display
            previewContainer.style.display = 'none'; // Hide file preview
            previewImage.src = ''; // Reset preview image
            if (errorFlash) errorFlash.style.display = 'none'; // Hide error flash
        }

        // Close the modal
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
        }
    }

    // Function for "Update Secret" modal
    function initializeUpdateSecretForm() {
        const updateForms = document.querySelectorAll('.updateSecretForm');
        updateForms.forEach((form) => {
            const index = form.dataset.index;
            const fileInput = document.getElementById(`file-${index}`);
            const fileNameDisplay = document.getElementById(`fileName-${index}`);
            const filePreview = document.getElementById(`filePreview-${index}`);
            const previewImage = document.getElementById(`previewImage-${index}`);
            const formError = document.getElementById(`errorFlash-${index}`);
            const submitButton = document.getElementById(`updateSecretSubmit-${index}`);
            const secretCardBody = document.querySelector(`.card-body[data-index="${index}"]`);
    
            const MAX_FILE_SIZE_MB = 500;
            const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;
    
            if (fileInput) {
                fileInput.addEventListener('change', function () {
                    const file = this.files[0];
                    if (file) {
                        fileNameDisplay.textContent = file.name;
    
                        if (file.size > MAX_FILE_SIZE_BYTES) {
                            formError.textContent = `Error: File size exceeds ${MAX_FILE_SIZE_MB} MB.`;
                            formError.style.display = 'block';
                            resetFileInput();
                            return;
                        }
    
                        if (file.type.startsWith('image/')) {
                            const reader = new FileReader();
                            reader.onload = function (e) {
                                previewImage.src = e.target.result;
                                filePreview.style.display = 'block';
                            };
                            reader.readAsDataURL(file);
                        } else {
                            filePreview.style.display = 'none';
                        }
    
                        formError.style.display = 'none';
                    }
                });
            }
    
            if (submitButton) {
                submitButton.addEventListener('click', function (event) {
                    event.preventDefault();
    
                    const formData = new FormData(form);
                    if (fileInput && fileInput.files[0]) {
                        formData.append('file', fileInput.files[0]);
                    }
    
                    fetch(form.action, {
                        method: 'POST',
                        body: formData,
                        headers: {
                            'X-Requested-With': 'XMLHttpRequest',
                            'X-CSRFToken': document.querySelector('input[name="csrf_token"]').value
                        }
                    })
                        .then(response => response.json())
                        .then(data => {
                            if (data.success) {
                                // Update secret details dynamically
                                if (data.secret) {
                                    const secretCardBody = document.querySelector(`#secretCardBody-${index}`);
                                    if (secretCardBody) {
                                        secretCardBody.innerHTML = `
                                            <p class="card-text m-0"><strong>Secret:</strong> ${data.secret.secret}</p>
                                            ${data.secret.file ? `
                                                <p class="card-text">
                                                    <strong>Attached File:</strong>
                                                    <a href="/downloads/${data.secret.file}" class="link-primary" download>
                                                        <i class="bi bi-file-earmark-arrow-down"></i> ${data.secret.file}
                                                    </a>
                                                </p>
                                                ${data.secret.file_preview ? `
                                                    <p><strong>Preview:</strong></p>
                                                    <img src="/downloads/${data.secret.file}" alt="File Preview" style="max-width: 20%; height: auto;">
                                                ` : `
                                                    <p style="font-size: small;">No preview available for this file type.</p>
                                                `}
                                            ` : ''}
                                        `;
                                    } else {
                                        console.error(`Element #secretCardBody-${index} not found.`);
                                    }

                                }
    
                                // Reset form and close modal
                                form.reset();
                                resetFileInput();
                                closeModal(form);
    
                                // Show flash message
                                showFlashMessage(data.flash_message, "success");
                            } else {
                                formError.textContent = data.error || 'Failed to update secret.';
                                formError.style.display = 'block';
                            }
                        })
                        .catch(error => {
                            console.error('Error:', error);
                            formError.textContent = 'An unexpected error occurred.';
                            formError.style.display = 'block';
                        });
                });
            }
    
            function resetFileInput() {
                fileInput.value = '';
                fileNameDisplay.textContent = '';
                filePreview.style.display = 'none';
                previewImage.src = '';
                formError.style.display = 'none';
            }
    
            function closeModal(form) {
                const modalElement = form.closest('.modal');
                if (modalElement) {
                    const modalInstance = bootstrap.Modal.getInstance(modalElement) || new bootstrap.Modal(modalElement);
                    modalInstance.hide();
                }
    
                document.body.style.overflow = '';
                document.body.style.paddingRight = '';
                const backdrops = document.querySelectorAll('.modal-backdrop');
                backdrops.forEach(backdrop => backdrop.remove());
            }
        });
    }
    
    

    // Initialize share forms
    function initializeShareButtons() {
        // Add event listener for the share form submission
        document.querySelectorAll('[id^="shareForm-"]').forEach(form => {
            // Initialize required fields based on the initial state
            toggleRequiredFields(form);
            
            form.addEventListener('submit', function (event) {
                event.preventDefault();
        
                // Clear previous errors
                this.querySelectorAll('.validation-error').forEach(el => el.remove());
                this.querySelectorAll('.is-invalid').forEach(el => el.classList.remove('is-invalid'));
        
                const sharingType = this.querySelector('input[name="sharing_type"]').value;
                const datePeriodInput = this.querySelector('input[name="date_period"]');
                const dateInput = this.querySelector('input[name="date"]');
                const timeInput = this.querySelector('input[name="time"]');
        
                let isValid = true;
        
                // Helper function to add validation error
                function addValidationError(input, message) {
                    if (input) {
                        input.classList.add('is-invalid');
                        const errorDiv = document.createElement('div');
                        errorDiv.className = 'validation-error text-danger small';
                        errorDiv.textContent = message;
                        input.parentNode.appendChild(errorDiv);
                    }
                }
        
                // Validate inputs based on sharing type
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
        
                // Proceed with submission if valid
                const url = this.action;
                const formData = new FormData(this);
        
                fetch(url, {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': csrfToken, // Ensure csrfToken is defined globally or passed correctly
                    },
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
                        } else {
                            // Show validation or error messages
                            if (data.errors) {
                                Object.entries(data.errors).forEach(([field, messages]) => {
                                    const inputElement = this.querySelector(`[name="${field}"]`);
                                    if (inputElement) {
                                        addValidationError(inputElement, messages.join(', '));
                                    }
                                });
                            } else {
                                showFlashMessage(data.message || 'An error occurred.', 'danger');
                            }
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
        
            // Check if the container exists
            if (!emailInputContainer) {
                console.warn(`Email input container with ID '${containerId}' not found. Skipping initialization.`);
                return; // Skip the rest of the function
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
        function toggleRequiredFields(form) {
            const sharingTypeInput = form.querySelector('input[name="sharing_type"]:checked');
            const sharingType = sharingTypeInput ? sharingTypeInput.value : null;
        
            const datePeriodInput = form.querySelector('input[name="date_period"]');
            const dateInput = form.querySelector('input[name="date"]');
            const timeInput = form.querySelector('input[name="time"]');
        
            if (sharingType === "last_login") {
                // Enable only date period input
                if (datePeriodInput) {
                    datePeriodInput.required = true;
                    datePeriodInput.parentElement.style.display = 'block';
                }
                if (dateInput) dateInput.required = false;
                if (timeInput) timeInput.required = false;
                if (dateInput) dateInput.parentElement.style.display = 'none';
                if (timeInput) timeInput.parentElement.style.display = 'none';
            } else if (sharingType === "scheduled") {
                // Enable date and time inputs
                if (datePeriodInput) datePeriodInput.required = false;
                if (dateInput) {
                    dateInput.required = true;
                    dateInput.parentElement.style.display = 'block';
                }
                if (timeInput) {
                    timeInput.required = true;
                    timeInput.parentElement.style.display = 'block';
                }
                if (datePeriodInput) datePeriodInput.parentElement.style.display = 'none';
            } else {
                // Hide all inputs if no valid sharing type is selected
                if (datePeriodInput) datePeriodInput.parentElement.style.display = 'none';
                if (dateInput) dateInput.parentElement.style.display = 'none';
                if (timeInput) timeInput.parentElement.style.display = 'none';
            }
        }
        
        // Attach toggle logic to sharing type changes
        document.querySelectorAll('input[name="sharing_type"]').forEach(input => {
            input.addEventListener('change', function () {
                const form = this.closest('form');
                if (form) toggleRequiredFields(form);
            });
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
    function initializeLastLoginHistory() {
        const loginHistoryModal = document.getElementById('loginHistoryModal');
        if (loginHistoryModal) {
            loginHistoryModal.addEventListener('show.bs.modal', function () {
                // Initialize variables
                let currentPage = 1;
    
                const tableBody = document.getElementById('loginHistoryTableBody');
                const paginationControls = document.getElementById('paginationControls');
    
                // Function to render a page of login history
                function renderPage(page) {
                    fetch(`/api/login-history?page=${page}`)
                        .then(response => response.json())
                        .then(data => {
                            const loginHistory = data.data;  // Get login history data from the response
                            const totalPages = data.pages;   // Get the total number of pages
    
                            // Clear the table body
                            tableBody.innerHTML = '';
    
                            // Add the rows for the current page
                            loginHistory.forEach(login => {
                                const row = document.createElement('tr');
                                const loginTimeCell = document.createElement('td');
                                const ipAddressCell = document.createElement('td');
    
                                loginTimeCell.textContent = login.login_time;
                                ipAddressCell.textContent = login.ip_address;
    
                                row.appendChild(loginTimeCell);
                                row.appendChild(ipAddressCell);
                                tableBody.appendChild(row);
                            });
    
                            // Render pagination controls
                            renderPaginationControls(page, totalPages);
                        })
                        .catch(error => {
                            console.error('Error fetching login history:', error);
                        });
                }
    
                // Function to render pagination controls
                function renderPaginationControls(page, totalPages) {
                    paginationControls.innerHTML = ''; // Clear previous pagination controls
    
                    // Number of pages to show (5 pages at a time)
                    const maxPagesToShow = 5;
    
                    // Calculate the range of pages to display
                    let startPage = Math.max(1, page - 2); // Start from 2 pages before the current page
                    let endPage = Math.min(totalPages, page + 2); // End at 2 pages after the current page
    
                    // Adjust the start page if there are fewer than maxPagesToShow pages
                    if (endPage - startPage < maxPagesToShow) {
                        startPage = Math.max(1, endPage - maxPagesToShow);
                    }
    
                    // Generate pagination items (previous, page numbers, next)
                    const createPageItem = (pageNum, text) => {
                        const pageItem = document.createElement('li');
                        pageItem.className = `page-item ${pageNum === page ? 'active' : ''}`;
                        const pageLink = document.createElement('a');
                        pageLink.className = 'page-link';
                        pageLink.href = '#';
                        pageLink.textContent = text;
                        pageLink.addEventListener('click', (e) => {
                            e.preventDefault();
                            renderPage(pageNum);
                        });
                        pageItem.appendChild(pageLink);
                        return pageItem;
                    };
    
                    // Add "Previous" button
                    if (page > 1) {
                        paginationControls.appendChild(createPageItem(page - 1, 'Previous'));
                    }
    
                    // Add page numbers
                    for (let i = startPage; i <= endPage; i++) {
                        paginationControls.appendChild(createPageItem(i, i));
                    }
    
                    // Add "Next" button
                    if (page < totalPages) {
                        paginationControls.appendChild(createPageItem(page + 1, 'Next'));
                    }
                }
    
                // Render the first page initially
                renderPage(currentPage);
            });
        }
    }
    



    // Close popup function
    window.closePopup = function(index) {
        document.getElementById('share-popup-' + index).style.display = 'none';
    };
});


