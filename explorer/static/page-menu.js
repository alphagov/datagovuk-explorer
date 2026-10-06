// Dismiss the pagination 3-dots menu (a native <details>) on outside click
// or Escape. The open/close toggle itself is the browser's own <details>
// behaviour, so the menu still works with JS disabled.
document.addEventListener('click', (event) => {
	document.querySelectorAll('details.page-menu[open]').forEach((menu) => {
		if (!menu.contains(event.target)) menu.removeAttribute('open')
	})
})

document.addEventListener('keydown', (event) => {
	if (event.key !== 'Escape') return
	document.querySelectorAll('details.page-menu[open]').forEach((menu) => menu.removeAttribute('open'))
})
