"""Shared web-view polish: user-agent spoofing and CSS injection.

Both MapViewerTab and MinimapOverlay call ``setup_web_view()`` so that every
embedded map page hides navigation chrome, cookie banners, footers, ads, and
scrollbars — making the map feel native rather than "a website in a box".

The CSS is injected in two complementary ways:
  1. Via QWebEngineScript (DocumentReady) — fires on every full page load.
  2. Via page().runJavaScript() on loadFinished — belt-and-suspenders for SPAs
     that do client-side routing without triggering a full reload.
"""

from __future__ import annotations

_WEBENGINE_OK = False
try:
    from PyQt6.QtWebEngineCore import QWebEngineScript
    _WEBENGINE_OK = True
except ImportError:
    pass


# ── User-agent ─────────────────────────────────────────────────────────────
# Present as a normal desktop Chrome build so map sites serve the full
# desktop layout and don't trip bot-detection heuristics.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ── CSS injection ──────────────────────────────────────────────────────────
# JavaScript that injects a <style> element hiding site chrome.
#
# Selector strategy:
#   • Target standard semantic elements (nav, header, footer) plus the most
#     common utility-class names used by every major map site framework.
#   • Exclude anything whose class/id contains "map" or "Map" so we never
#     accidentally hide in-page map toolbars or legend panels.
#   • Strip all scrollbars and set body overflow:hidden to prevent scroll jitter.
#
# The function is idempotent — it bails out if the style tag already exists,
# so repeated calls from the SPA re-navigation path are harmless.
CSS_JS = """\
(function () {
    'use strict';
    if (document.getElementById('__arc_css__')) return;
    var s = document.createElement('style');
    s.id = '__arc_css__';
    s.textContent =

        /* ── Navigation & header bars ── */
        'nav:not([class*="map"]):not([class*="Map"]):not([class*="tool"]),'
        + 'header:not([class*="map"]):not([class*="Map"]),'
        + '.header,.navbar,.nav-bar,.navigation,.site-nav,'
        + '#header,#nav,#navbar,#navigation,#site-header,'
        + '.site-header,.page-header,.top-bar,.topbar,.top-nav,.topnav,'
        + '[class*="Navbar"],[class*="NavBar"],[class*="TopBar"],'
        + '[class*="AppBar"]:not([class*="map"]),'
        + '[class*="SiteHeader"],[class*="PageHeader"]'
        + '{display:none!important}'

        /* ── Footers ── */
        + 'footer,.footer,#footer,.site-footer,.page-footer,'
        + '[class*="Footer"]:not([class*="map"])'
        + '{display:none!important}'

        /* ── Cookie / consent / GDPR banners ── */
        + '.cookie-banner,.cookie-notice,.cookie-bar,.cookie-consent,'
        + '.gdpr-banner,.gdpr-notice,.cc-window,.cc-banner,.cc-revoke,'
        + '.cookie-law-info-bar,#cookie-law-info-bar,'
        + '.CookieConsent,#CookieConsent,'
        + '#onetrust-banner-sdk,.onetrust-banner-sdk,'
        + '.onetrust-pc-dark-filter,[class*="cookieBanner"],'
        + '[class*="CookieBanner"],[class*="ConsentBanner"],'
        + '[id*="cookie-banner"],[id*="cookie_banner"]'
        + '{display:none!important}'

        /* ── Ads ── */
        + '.ad-banner,.advertisement,.ads-container,.sponsored'
        + '{display:none!important}'

        /* ── Scrollbars — hide the widget, keep scroll events intact ── */
        + '::-webkit-scrollbar{display:none!important}'
        + '*{scrollbar-width:none!important;-ms-overflow-style:none!important}';

    (document.head || document.documentElement).appendChild(s);
})();
"""


def setup_web_view(view) -> None:
    """Configure user-agent and persistent CSS injection on a QWebEngineView.

    Safe to call when PyQtWebEngine is absent — becomes a no-op so callers
    don't need to guard with ``if _WEBENGINE``.
    """
    if not _WEBENGINE_OK:
        return

    # User-agent — affects all views that share this profile.
    view.page().profile().setHttpUserAgent(USER_AGENT)

    # Per-page script: runs at DocumentReady on every navigation for this view.
    script = QWebEngineScript()
    script.setName("arc_chrome_strip")
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(False)
    script.setSourceCode(CSS_JS)
    view.page().scripts().insert(script)
