/*!
* Start Bootstrap - Clean Blog v6.0.9 (https://startbootstrap.com/theme/clean-blog)
* Copyright 2013-2023 Start Bootstrap
* Licensed under MIT (https://github.com/StartBootstrap/startbootstrap-clean-blog/blob/master/LICENSE)
*/
window.addEventListener('DOMContentLoaded', () => {
    let scrollPos = 0;
    const mainNav = document.getElementById('mainNav');
    const headerHeight = mainNav.clientHeight;
    window.addEventListener('scroll', function() {
        const currentTop = document.body.getBoundingClientRect().top * -1;
        if ( currentTop < scrollPos) {
            // Scrolling Up
            if (currentTop > 0 && mainNav.classList.contains('is-fixed')) {
                mainNav.classList.add('is-visible');
            } else {
                console.log(123);
                mainNav.classList.remove('is-visible', 'is-fixed');
            }
        } else {
            // Scrolling Down
            mainNav.classList.remove(['is-visible']);
            if (currentTop > headerHeight && !mainNav.classList.contains('is-fixed')) {
                mainNav.classList.add('is-fixed');
            }
        }
        scrollPos = currentTop;
    });
})


// Pin & Star functions
document.addEventListener("DOMContentLoaded", function() {
    var csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

    // Toggle Pin
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

    // Toggle Star
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

    // Show the correct popup on Share button click
    document.querySelectorAll('.share-button').forEach(function(button) {
        button.addEventListener('click', function() {
            var targetPopup = this.getAttribute('data-target');
            document.querySelector(targetPopup).style.display = 'block';
            
            // Reset the date and time field display when opening the modal
            var dateField = document.querySelector(targetPopup).querySelector('.date-field');
            var dateLabel = document.querySelector(targetPopup).querySelector('.date-label');
            var timeField = document.querySelector(targetPopup).querySelector('.time-field');
            var timeLabel = document.querySelector(targetPopup).querySelector('.time-label');
            
            dateField.style.display = 'none'; // Hide date field initially
            dateLabel.style.display = 'none'; // Hide label initially
            timeField.style.display = 'none'; // Hide time field initially
            timeLabel.style.display = 'none'; // Hide time label initially
        });
    });

    // Toggle the date and time field visibility
    document.querySelectorAll('.toggle-date-button').forEach(function(button) {
        button.addEventListener('click', function() {
            var targetPopup = this.closest('.modal'); // Get the closest modal
            var dateField = targetPopup.querySelector('.date-field');
            var dateLabel = targetPopup.querySelector('.date-label');
            var timeField = targetPopup.querySelector('.time-field');
            var timeLabel = targetPopup.querySelector('.time-label');
            
            if (dateField.style.display === 'none') {
                dateField.style.display = 'block';
                dateLabel.style.display = 'block';
                timeField.style.display = 'block';  // Show time field
                timeLabel.style.display = 'block';  // Show time label
            } else {
                dateField.style.display = 'none';
                dateLabel.style.display = 'none';
                timeField.style.display = 'none';  // Hide time field
                timeLabel.style.display = 'none';  // Hide time label
            }
        });
    });

    // Add event listener for upgrading the plan
    document.getElementById('confirm-upgrade').addEventListener('click', function () {
        var planSelect = document.getElementById("upgrade-form").querySelector("select[name='plan_id']");
        if (planSelect.value == 0) {
            alert("Please select a valid plan to upgrade.");
            return false; // Prevent form submission
        } else {
            // Submit the form after the user confirms
            document.getElementById('upgrade-form').submit();
        }
    });
    

    document.querySelectorAll('.btn-outline-secondary').forEach(button => {
        button.addEventListener('click', function() {
            const secretId = this.getAttribute('data-id');
        });
    });

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

});


// Close popup function
function closePopup(index) {
    document.getElementById('share-popup-' + index).style.display = 'none';
}




