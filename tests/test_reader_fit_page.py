from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
READER = PROJECT_ROOT / "reader"


def _read(*parts: str) -> str:
    return READER.joinpath(*parts).read_text(encoding="utf-8")


def test_fit_page_choice_is_applied_before_first_paint():
    base = _read("templates", "base.html")

    assert "localStorage.getItem('issued-reader-fit')" in base
    assert "root.dataset.readerFit = savedReaderFit === 'page' ? 'page' : 'none';" in base
    assert "root.dataset.readerFit = 'none';" in base


def test_reader_offers_a_fit_page_toggle():
    template = _read("templates", "reader.html")
    script = _read("static", "js", "reader.js")

    assert 'id="btn-fit-page"' in template
    assert 'aria-pressed="false"' in template
    assert "const FIT_STORAGE_KEY = 'issued-reader-fit';" in script
    assert "const isImmersive = () => Boolean(document.fullscreenElement) || isFitPage();" in script
    assert "w: toggleFitPage" in script
    assert "W: toggleFitPage" in script
    assert "if (e.ctrlKey || e.metaKey || e.altKey) return;" in script
    assert "e.key === 'Escape' && isFitPage() && !document.fullscreenElement" in script
    # Toolbars auto-hide in both immersive modes, not only in fullscreen.
    assert "if (!document.fullscreenElement) return;" not in script


def test_fit_page_styles_fill_the_window_without_page_buttons():
    styles = _read("static", "css", "style.css")

    assert 'html[data-reader-fit="page"] .reader-page .site-header' in styles
    assert 'html[data-reader-fit="page"] .reader-page .reader {\n  position: relative;\n  height: 100dvh;' in styles
    # The end-of-issue card no longer leaves with the toolbar.
    assert 'html[data-reader-fit="page"] .reader-page .reader.cursor-hidden #reader-series-end' not in styles
    assert 'html[data-reader-fit="page"] .reader-page .reader-navigation' in styles
    assert 'html[data-reader-fit="page"] .reader-page .reader-image-wrap img' in styles


def test_page_turn_zones_are_anchored_to_the_displayed_page():
    script = _read("static", "js", "reader-interactions.js")
    styles = _read("static", "css", "style.css")

    assert "export function navigationZone(clientX, pageLeft, pageRight)" in script
    assert "Math.min(navigationEdgeWidth(pageWidth), pageWidth / 3)" in script
    assert "content.querySelectorAll('img')" in script
    assert "viewport.dataset.navZone = zoneAt(event.clientX);" in script
    assert '.reader-image-wrap[data-nav-zone="previous"]' in styles
    assert '.reader-image-wrap[data-nav-zone="next"]' in styles


def test_fit_page_enlarges_scans_smaller_than_the_window():
    styles = _read("static", "css", "style.css")
    start = styles.index("@media (min-width: 640px) {\n  html[data-reader-fit=\"page\"]")
    block = styles[start:styles.index("\n}\n", start)]

    assert "height: 100%;" in block
    assert "max-width: 100%;" in block
    assert "object-fit: contain;" in block
    assert "#reader-image {\n    object-position: right center;" in block
    assert "#reader-image-right {\n    object-position: left center;" in block


def test_toolbar_hides_soon_after_the_mouse_stops_unless_in_use():
    script = _read("static", "js", "reader.js")

    assert "const HIDE_AFTER_MOUSE_MS = 1000;" in script
    assert "const HIDE_AFTER_TOUCH_MS = 3000;" in script
    assert "if (event.pointerType === 'mouse') showControls(HIDE_AFTER_MOUSE_MS);" in script
    assert "readerControls?.addEventListener('pointerenter'" in script
    assert "readerControls?.addEventListener('pointerleave'" in script
    assert "if (controlsInUse()) scheduleHide(HIDE_AFTER_MOUSE_MS);" in script
