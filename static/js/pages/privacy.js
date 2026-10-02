// Page script for /static/privacy.html, moved out of the HTML unchanged.
// Privacy link scroll detection
function handlePrivacyLinkVisibility() {
    const privacyLink = document.querySelector('.privacy-link');
    const scrollHeight = document.documentElement.scrollHeight;
    const scrollTop = document.documentElement.scrollTop;
    const clientHeight = document.documentElement.clientHeight;
    
    // Show when scrolled to within 100px of bottom
    if (scrollTop + clientHeight >= scrollHeight - 100) {
        privacyLink.classList.add('visible');
    } else {
        privacyLink.classList.remove('visible');
    }
}

// Throttled scroll listener
let ticking = false;
function onScroll() {
    if (!ticking) {
        requestAnimationFrame(() => {
            handlePrivacyLinkVisibility();
            ticking = false;
        });
        ticking = true;
    }
}

window.addEventListener('scroll', onScroll);
window.addEventListener('resize', handlePrivacyLinkVisibility);

// Check initial state
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(handlePrivacyLinkVisibility, 100);
});
    
