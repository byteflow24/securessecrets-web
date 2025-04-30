document.addEventListener('DOMContentLoaded', () => {
    // Handle AJAX navigation
    function loadContent(url, targetElementId) {
        fetch(url, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
        .then(response => response.json())
        .then(data => {
            // Update content
            const targetElement = document.getElementById(targetElementId);
            targetElement.innerHTML = data.html;
            document.title = data.title;

            // Reinitialize reCAPTCHA
            if (data.reinitializeRecaptcha === 'home' && typeof window.reinitializeHomeRecaptcha === 'function') {
                window.reinitializeHomeRecaptcha();
            } else if (data.reinitializeRecaptcha === 'contact' && typeof window.reinitializeContactRecaptcha === 'function') {
                window.reinitializeContactRecaptcha();
            } else if (data.reinitializeRecaptcha) {
                console.warn(`No reCAPTCHA reinitialization function for ${data.reinitializeRecaptcha}`);
            }
        })
        .catch(error => {
            console.error('Error loading content:', error);
            alert('Failed to load content. Please try again.');
        });
    }

    // Handle navigation links
    document.querySelectorAll('a[data-ajax-nav]').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const url = link.getAttribute('href');
            loadContent(url, 'content-container');
        });
    });
});