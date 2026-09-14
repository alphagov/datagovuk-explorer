// Toggle — intercept "More …" link clicks so the extra items show/hide without a page load.
// The toggles are real links so they still work without JS.
document.querySelectorAll('.facet-toggle').forEach((toggle) => {
	toggle.addEventListener('click', (event) => {
		event.preventDefault()

		const list = toggle.closest('.facet-list')
		const expanded = list.classList.toggle('facet-list--expanded')

		toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false')
		toggle.textContent = expanded ? toggle.dataset.fewerLabel : toggle.dataset.moreLabel

		// Propagate the expanded state into every facet link's href so clicking
		// a facet value doesn't collapse the list back to the top 10.
		const param = toggle.dataset.param
		const value = toggle.dataset.value
		if (param && value) {
			const updaters = [toggle, ...document.querySelectorAll('.facet-link')]
			for (const a of updaters) {
				const url = new URL(a.getAttribute('href'), window.location.href)
				if (expanded) url.searchParams.set(param, value)
				else url.searchParams.delete(param)
				a.setAttribute('href', url.pathname + url.search + url.hash)
			}
		}
	})
})

// Live search — filter a facet group's values as the user types.
// While a term is active, .facet-list--filtering disables the More/Fewer toggle
// (via CSS) so all values are candidates; non-matching items get .facet-hidden.
//
// ANNOUNCE_DELAY is intentionally long: screen-reader users hear each keystroke
// echoed, so a short delay fires mid-word and gets cut off by the next echo.
// We also skip announcing when the count hasn't changed.
const ANNOUNCE_DELAY = 1000

document.querySelectorAll('.facet-search-input').forEach((input) => {
	const group = input.closest('.facet-group')
	const list = group.querySelector('.facet-list')
	const empty = group.querySelector('.facet-search-empty')
	const live = group.querySelector('.facet-search-live')
	const links = list.querySelectorAll('.facet-link')

	let timer = null
	let lastCount = null

	const announce = (count) => {
		if (count === 0) return empty ? empty.textContent : 'No results matched your search'
		return count === 1 ? '1 result' : `${count} results`
	}

	input.addEventListener('input', () => {
		const term = input.value.trim().toLowerCase()

		if (timer) {
			clearTimeout(timer)
			timer = null
		}

		if (!term) {
			list.classList.remove('facet-list--filtering')
			list.querySelectorAll('.facet-hidden').forEach((li) => li.classList.remove('facet-hidden'))
			if (empty) empty.hidden = true
			if (live) live.textContent = ''
			lastCount = null
			return
		}

		list.classList.add('facet-list--filtering')
		let matches = 0
		links.forEach((link) => {
			const name = (link.querySelector('.facet-name').textContent || '').toLowerCase()
			const matched = name.includes(term)
			link.parentElement.classList.toggle('facet-hidden', !matched)
			if (matched) matches++
		})
		if (empty) empty.hidden = matches > 0

		if (matches === lastCount) return

		timer = setTimeout(() => {
			lastCount = matches
			if (live) live.textContent = announce(matches)
		}, ANNOUNCE_DELAY)
	})
})
