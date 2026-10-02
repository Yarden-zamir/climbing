// Page script for /static/memes.html, moved out of the HTML unchanged.
// Page transition script
document.addEventListener("DOMContentLoaded", () => {
	document.querySelectorAll("nav a").forEach((link) => {
		link.addEventListener("click", function (e) {
			const href = this.getAttribute("href");
			if (
				href &&
				!href.startsWith("#") &&
				!this.classList.contains("active")
			) {
				e.preventDefault();
				const main = document.querySelector("main.page-fade");
				main.classList.add("fade-out");
				setTimeout(() => {
					window.location.href = href;
				}, 400);
			}
		});
	});
	
	// Check for PWA shortcut action parameter
	const urlParams = new URLSearchParams(window.location.search);
	if (urlParams.get('action') === 'add') {
		// Wait a moment for the page to fully load, then open the add meme modal
		setTimeout(() => {
			const addMemeFab = document.getElementById('add-meme-fab');
			if (addMemeFab) {
				addMemeFab.click();
			}
		}, 500);
	}
});
		
