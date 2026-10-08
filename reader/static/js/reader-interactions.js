import Panzoom from './vendor/panzoom-4.6.2.es.min.js';

export const NAV_EDGE_RATIO = 0.18;
export const NAV_EDGE_MIN_PX = 64;
export const NAV_EDGE_MAX_PX = 160;
export const DOUBLE_TAP_MS = 300;
export const DOUBLE_TAP_DISTANCE_PX = 40;
export const PAN_THRESHOLD_PX = 6;
export const ZOOM_SCALE = 2;
export const MOBILE_SPREAD_ZOOM_SCALE = 3;
export const ZOOM_DURATION_MS = 200;
export const MOBILE_READER_MEDIA_QUERY = '(max-width: 639px)';

const PAN_SETTLE_EPSILON_PX = 0.5;
const ZOOM_SETTLE_BUFFER_MS = 32;
const ZOOM_EASING = 'ease-out';

const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const cssPixels = (value) => parseFloat(value) || 0;

const innerBounds = (element) => {
  const rect = element.getBoundingClientRect();
  const style = window.getComputedStyle(element);
  return {
    left: rect.left + cssPixels(style.borderLeftWidth) + cssPixels(style.paddingLeft),
    right: rect.right - cssPixels(style.borderRightWidth) - cssPixels(style.paddingRight),
    top: rect.top + cssPixels(style.borderTopWidth) + cssPixels(style.paddingTop),
    bottom: rect.bottom - cssPixels(style.borderBottomWidth) - cssPixels(style.paddingBottom),
  };
};

const axisCorrection = (viewportStart, viewportEnd, contentStart, contentEnd) => {
  const viewportSize = viewportEnd - viewportStart;
  const contentSize = contentEnd - contentStart;
  if (contentSize <= viewportSize) {
    return (viewportStart + viewportEnd - contentStart - contentEnd) / 2;
  }
  if (contentStart > viewportStart) return viewportStart - contentStart;
  if (contentEnd < viewportEnd) return viewportEnd - contentEnd;
  return 0;
};

export function navigationEdgeWidth(viewportWidth) {
  return Math.max(NAV_EDGE_MIN_PX, Math.min(NAV_EDGE_MAX_PX, viewportWidth * NAV_EDGE_RATIO));
}

// Zones are anchored to the displayed page(s), not to the frame: on a wide window the page is
// centred between empty bands, and an edge measured on the frame would land in those bands
// instead of on the page. Everything left of the page plus its left edge band turns back.
export function navigationZone(clientX, pageLeft, pageRight) {
  const pageWidth = pageRight - pageLeft;
  // A third of the page always stays in the centre for toolbar taps and double-tap zoom.
  const edge = Math.min(navigationEdgeWidth(pageWidth), pageWidth / 3);
  if (clientX <= pageLeft + edge) return 'previous';
  if (clientX >= pageRight - edge) return 'next';
  return 'center';
}

export function createReaderInteractions({
  viewport,
  content,
  onPrevious,
  onNext,
  onCenterTap = () => {},
  isDisabled = () => false,
}) {
  if (!viewport || !content) {
    throw new Error('Reader interactions require viewport and content elements');
  }

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const mobileReader = window.matchMedia(MOBILE_READER_MEDIA_QUERY);
  let zoomed = false;
  let customContainment = false;
  let constraintTimer = null;
  let lastTap = null;
  let pointer = null;
  let centerTapTimer = null;

  const panzoom = Panzoom(content, {
    minScale: 1,
    maxScale: ZOOM_SCALE,
    startScale: 1,
    disablePan: true,
    disableZoom: true,
    panOnlyWhenZoomed: true,
    pinchAndPan: false,
    duration: ZOOM_DURATION_MS,
    easing: ZOOM_EASING,
    cursor: 'default',
    touchAction: 'manipulation',
    handleStartEvent: () => {},
  });

  const animationOptions = (animate) => ({
    animate: animate && !reducedMotion.matches,
    duration: ZOOM_DURATION_MS,
  });

  const isMobileSpread = () => mobileReader.matches && content.classList.contains('spread-mode');

  const zoomScale = () => (
    isMobileSpread()
      ? MOBILE_SPREAD_ZOOM_SCALE
      : ZOOM_SCALE
  );

  const clearConstraintTimer = () => {
    window.clearTimeout(constraintTimer);
    constraintTimer = null;
  };

  const clearCenterTap = () => {
    window.clearTimeout(centerTapTimer);
    centerTapTimer = null;
  };

  // Panzoom's built-in containment does not account for a flex-centered element.
  // The spread therefore settles against its actual rendered edges after a drag.
  const constrainSpreadPan = ({ animate = false } = {}) => {
    if (!zoomed || !customContainment) return;

    const scale = panzoom.getScale();
    const pan = panzoom.getPan();
    const bounds = innerBounds(viewport);
    const contentRect = content.getBoundingClientRect();
    const visualDeltaX = axisCorrection(
      bounds.left,
      bounds.right,
      contentRect.left,
      contentRect.right,
    );
    const visualDeltaY = axisCorrection(
      bounds.top,
      bounds.bottom,
      contentRect.top,
      contentRect.bottom,
    );

    if (
      Math.abs(visualDeltaX) < PAN_SETTLE_EPSILON_PX
      && Math.abs(visualDeltaY) < PAN_SETTLE_EPSILON_PX
    ) return;
    panzoom.pan(
      pan.x + visualDeltaX / scale,
      pan.y + visualDeltaY / scale,
      {
        animate: animate && !reducedMotion.matches,
        contain: false,
        duration: ZOOM_DURATION_MS,
        easing: ZOOM_EASING,
        force: true,
        silent: true,
      },
    );
  };

  const setZoomed = (value, targetScale = ZOOM_SCALE) => {
    zoomed = value;
    customContainment = value && isMobileSpread();
    viewport.classList.toggle('is-zoomed', value);
    // Zoomed clicks pan instead of turning pages; drop the page-turn cursor until the next move.
    if (value) delete viewport.dataset.navZone;
    viewport.dataset.zoomed = value ? 'true' : 'false';
    viewport.setAttribute(
      'aria-label',
      value
        ? 'Comic page zoomed – drag to pan, double-tap to reset'
        : 'Comic page – tap near an edge to navigate, double-tap the center to zoom',
    );
    panzoom.setOptions({
      contain: value && !customContainment ? 'outside' : false,
      disablePan: !value,
      maxScale: value ? targetScale : ZOOM_SCALE,
      touchAction: value ? 'none' : 'manipulation',
    });
  };

  const resetZoom = ({ animate = true } = {}) => {
    lastTap = null;
    // A page turn can land inside the double-tap window of a center tap; without this the
    // pending tap would toggle the toolbars on the new page.
    clearCenterTap();
    clearConstraintTimer();
    if (!zoomed && panzoom.getScale() === 1) return;
    panzoom.reset({ ...animationOptions(animate), contain: false });
    setZoomed(false);
  };

  const zoomAt = (clientX, clientY) => {
    const targetScale = zoomScale();
    const bounds = innerBounds(viewport);
    const contentRect = content.getBoundingClientRect();
    const contentStyle = window.getComputedStyle(content);
    const focal = {
      x: (
        clientX
        - bounds.left
        - cssPixels(contentStyle.marginLeft)
        - contentRect.width / 2
      ) * targetScale,
      y: (
        clientY
        - bounds.top
        - cssPixels(contentStyle.marginTop)
        - contentRect.height / 2
      ) * targetScale,
    };
    setZoomed(true, targetScale);
    panzoom.zoom(targetScale, {
      ...animationOptions(true),
      focal,
      force: true,
    });
    if (customContainment) {
      const settleDelay = reducedMotion.matches
        ? ZOOM_SETTLE_BUFFER_MS
        : ZOOM_DURATION_MS + ZOOM_SETTLE_BUFFER_MS;
      constraintTimer = window.setTimeout(() => {
        constraintTimer = null;
        constrainSpreadPan();
      }, settleDelay);
    }
  };

  const toggleZoomAtCenter = () => {
    if (zoomed) {
      resetZoom();
      return;
    }
    const rect = viewport.getBoundingClientRect();
    zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2);
  };

  const registerTap = (event) => {
    const tap = { x: event.clientX, y: event.clientY, time: performance.now() };
    if (
      lastTap &&
      tap.time - lastTap.time <= DOUBLE_TAP_MS &&
      distance(tap, lastTap) <= DOUBLE_TAP_DISTANCE_PX
    ) {
      lastTap = null;
      clearCenterTap();
      if (zoomed) resetZoom();
      else zoomAt(tap.x, tap.y);
      return;
    }
    lastTap = tap;
    // A single tap is only known once the double-tap window has passed without a second tap.
    if (!zoomed) {
      clearCenterTap();
      centerTapTimer = window.setTimeout(() => {
        centerTapTimer = null;
        onCenterTap();
      }, DOUBLE_TAP_MS);
    }
  };

  const pointerDown = (event) => {
    if (!event.isPrimary || (event.pointerType === 'mouse' && event.button !== 0)) return;
    pointer = {
      id: event.pointerId,
      start: { x: event.clientX, y: event.clientY },
      moved: false,
    };
    try { viewport.setPointerCapture(event.pointerId); } catch (_) { /* capture is best-effort */ }
  };

  const pointerMove = (event) => {
    if (!pointer || pointer.id !== event.pointerId) return;
    if (distance(pointer.start, { x: event.clientX, y: event.clientY }) >= PAN_THRESHOLD_PX) {
      pointer.moved = true;
      lastTap = null;
    }
  };

  const pointerUp = (event) => {
    if (!pointer || pointer.id !== event.pointerId) return;
    const moved = pointer.moved;
    pointer = null;
    try { viewport.releasePointerCapture(event.pointerId); } catch (_) { /* capture may already be lost */ }
    if (moved || isDisabled()) return;

    event.preventDefault();
    if (zoomed) {
      registerTap(event);
      return;
    }

    const zone = zoneAt(event.clientX);
    if (zone === 'previous') {
      lastTap = null;
      onPrevious();
    } else if (zone === 'next') {
      lastTap = null;
      onNext();
    } else {
      registerTap(event);
    }
  };

  // Horizontal extent of the visible page images; the frame itself while none has a size yet.
  const pageBounds = () => {
    let left = Infinity;
    let right = -Infinity;
    content.querySelectorAll('img').forEach((image) => {
      const rect = image.getBoundingClientRect();
      if (rect.width === 0) return;
      left = Math.min(left, rect.left);
      right = Math.max(right, rect.right);
    });
    if (left < right) return { left, right };
    const rect = viewport.getBoundingClientRect();
    return { left: rect.left, right: rect.right };
  };

  const zoneAt = (clientX) => {
    const { left, right } = pageBounds();
    return navigationZone(clientX, left, right);
  };

  // A mouse shows which way a click turns the page.
  const hover = (event) => {
    if (event.pointerType !== 'mouse' || zoomed) {
      delete viewport.dataset.navZone;
      return;
    }
    viewport.dataset.navZone = zoneAt(event.clientX);
  };
  const leave = () => { delete viewport.dataset.navZone; };

  const pointerCancel = () => {
    pointer = null;
    lastTap = null;
  };

  const panStart = () => {
    if (zoomed) viewport.classList.add('is-panning');
  };
  const panEnd = () => {
    viewport.classList.remove('is-panning');
    constrainSpreadPan({ animate: true });
  };
  const resize = () => resetZoom({ animate: false });

  viewport.addEventListener('pointerdown', pointerDown);
  viewport.addEventListener('pointermove', pointerMove);
  viewport.addEventListener('pointerup', pointerUp);
  viewport.addEventListener('pointercancel', pointerCancel);
  viewport.addEventListener('pointermove', hover);
  viewport.addEventListener('pointerleave', leave);
  content.addEventListener('panzoomstart', panStart);
  content.addEventListener('panzoomend', panEnd);
  window.addEventListener('resize', resize);

  const destroy = () => {
    viewport.removeEventListener('pointerdown', pointerDown);
    viewport.removeEventListener('pointermove', pointerMove);
    viewport.removeEventListener('pointerup', pointerUp);
    viewport.removeEventListener('pointercancel', pointerCancel);
    viewport.removeEventListener('pointermove', hover);
    viewport.removeEventListener('pointerleave', leave);
    content.removeEventListener('panzoomstart', panStart);
    content.removeEventListener('panzoomend', panEnd);
    window.removeEventListener('resize', resize);
    clearConstraintTimer();
    clearCenterTap();
    panzoom.destroy();
    panzoom.resetStyle();
  };

  return {
    destroy,
    isZoomed: () => zoomed,
    resetZoom,
    toggleZoomAtCenter,
  };
}
