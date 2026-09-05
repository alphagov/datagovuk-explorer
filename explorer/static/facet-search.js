// Facet live search — filter a facet's values in place as the user types.
//
// Opt-in per facet group: a group renders a .facet-search box (see the
// facet_group macro) only when it carries a `search` placeholder. The JS
// is a progressive enhancement — with it off, the box is inert and the
// ordinary "More …" toggle still reveals the long list.
//
// Searching covers ALL values in the list, not just the visible cut-off:
// while a term is active the list gets the .facet-list--filtering class,
// which (facets.css) stands down the More/Fewer toggle and makes every
// hidden value eligible again. Non-matching items are then hidden with
// .facet-hidden; clearing the box drops both, returning the list to its
// previous expanded/collapsed state.
//
// Screen readers get debounced feedback: after the user stops typing we
// announce the result count into the group's sr-only role="status" line.
// Two rules keep that announcement usable:
//
//   • The pause must be long (ANNOUNCE_DELAY below). Screen-reader users
//     type slowly — every keystroke is echoed back — so a short pause
//     (300ms) fires the announcement mid-word while the user is still
//     typing, and the next character echo cuts the announcement off.
//   • We only announce when the count actually changes — extending a term
//     that narrows the same set isn't news, and re-announcing identical
//     counts is just noise on top of the typing echo.
//
// The no-match case announces the visible empty line, so the spoken and
// visible messages stay identical.

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
			// Back to the ordinary (collapsed or expanded) list.
			list.classList.remove('facet-list--filtering')
			list.querySelectorAll('.facet-hidden').forEach((li) => li.classList.remove('facet-hidden'))
			if (empty) empty.hidden = true
			if (live) live.textContent = ''
			lastCount = null
			return
		}

		// Filter immediately (the visual feedback); announce after a pause.
		list.classList.add('facet-list--filtering')
		let matches = 0
		links.forEach((link) => {
			const name = (link.querySelector('.facet-name').textContent || '').toLowerCase()
			const matched = name.includes(term)
			link.parentElement.classList.toggle('facet-hidden', !matched)
			if (matched) matches++
		})
		if (empty) empty.hidden = matches > 0

		// Nothing new to say — the last count we announced still stands.
		if (matches === lastCount) return

		timer = setTimeout(() => {
			lastCount = matches
			if (live) live.textContent = announce(matches)
		}, ANNOUNCE_DELAY)
	})
})
