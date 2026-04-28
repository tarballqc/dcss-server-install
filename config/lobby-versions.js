(function() {
  function groupVersions() {
    var p = document.getElementById('play_now');
    if (!p || p.querySelector('.old_versions')) return false;
    var rc = p.querySelectorAll('.edit_rc_link');
    if (rc.length <= 2) return false;
    var el = rc[2];
    while (el && el.parentElement !== p) el = el.parentElement;
    if (!el) return false;
    var d = document.createElement('details');
    d.className = 'old_versions';
    d.style.cssText = 'margin:4px 0;';
    var s = document.createElement('summary');
    s.style.cssText = 'cursor:pointer;color:#5fd7ff;list-style:none;padding:2px 0;';
    s.innerHTML = '&#9662; Click to see older versions';
    d.appendChild(s);
    p.insertBefore(d, el);
    while (d.nextSibling) d.appendChild(d.nextSibling);
    return true;
  }
  // Try multiple strategies since play_now content may load at different times
  if (groupVersions()) return;
  // MutationObserver for dynamic content
  var o = new MutationObserver(function() {
    if (groupVersions()) o.disconnect();
  });
  o.observe(document.documentElement, {childList: true, subtree: true});
  // Fallback: retry after short delays (covers race conditions)
  [500, 1500, 3000].forEach(function(ms) {
    setTimeout(function() { if (groupVersions()) o.disconnect(); }, ms);
  });
})();
