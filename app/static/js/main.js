document.addEventListener('DOMContentLoaded', () => {
    // Handle AJAX navigation
    function loadContent(url, targetElementId) {
        fetch(url, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
        .then(response => {
            if (response.status === 403 && response.headers.get('content-type').includes('application/json')) {
                return response.json().then(data => {
                    if (data.redirect) {
                        console.log(`Redirecting to ${data.redirect} for non-authenticated user`);
                        window.location.href = data.redirect;
                    } else {
                        throw new Error('Unauthorized AJAX request');
                    }
                });
            }
            return response.json();
        })
        .then(data => {
            if (!data.html) return; // Already redirected
            // Update content
            const targetElement = document.getElementById(targetElementId);
            targetElement.innerHTML = data.html;
            document.title = data.title;

            // Reinitialize reCAPTCHA (only needed for other pages like home)
            if (data.reinitializeRecaptcha && typeof window[`reinitialize${data.reinitializeRecaptcha.charAt(0).toUpperCase() + data.reinitializeRecaptcha.slice(1)}Recaptcha`] === 'function') {
                window[`reinitialize${data.reinitializeRecaptcha.charAt(0).toUpperCase() + data.reinitializeRecaptcha.slice(1)}Recaptcha`]();
            }

            // Execute scripts in injected content
            const scripts = targetElement.querySelectorAll('script');
            scripts.forEach(oldScript => {
                const newScript = document.createElement('script');
                newScript.textContent = oldScript.textContent;
                oldScript.parentNode.replaceChild(newScript, oldScript);
            });
        })
        .catch(error => {
            console.error('Error loading content:', error);
            window.location.href = url; // Fallback to full page load
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