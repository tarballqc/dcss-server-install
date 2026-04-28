(function() {
  // ── Latency indicator (refreshes every 30s) ──
  function latencyClass(ms) {
    return ms < 100 ? 'good' : ms < 200 ? 'ok' : 'poor';
  }

  function updateLatencyDisplay() {
    var el = document.getElementById('rgg-latency');
    if (!el) return;

    // Ping this server only — no server-name prefix; the user is already on it.
    var t0 = performance.now();
    fetch('/health', { cache: 'no-store' })
      .then(function() {
        var ms = Math.round(performance.now() - t0);
        el.innerHTML = '<span class="rgg-this"><span class="' + latencyClass(ms) + '">' + ms + 'ms</span></span>';
      })
      .catch(function() {
        el.innerHTML = '<span class="rgg-this"><span class="offline">--</span></span>';
      });
  }
  updateLatencyDisplay();
  setInterval(updateLatencyDisplay, 30000);

  // ── Dynamic banner content ──
  var banner = document.getElementById('rgg-banner');
  if (!banner) return;

  function esc(s) {
    if (!s) return '';
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function renderBanner(d) {
    var html = '<div class="bn-row">';

    // ── Card 1: Latest Win ──
    html += '<div class="bn-card bn-win">';
    html += '<div class="bn-card-header">[win] Latest Victory</div>';
    if (d.latest_win) {
      var w = d.latest_win;
      var god = w.god ? ' of ' + esc(w.god) : '';
      var runes = w.runes && w.runes !== '0' ? w.runes + ' runes' : '';
      html += '<span class="bn-player">' + esc(w.name) + '</span> ';
      html += '<span class="bn-win-text">ascended</span> ';
      html += 'a L' + esc(w.xl) + ' ';
      html += '<span class="bn-combo">' + esc(w.race) + ' ' + esc(w.cls) + '</span>';
      html += '<span class="bn-god">' + esc(god) + '</span>';
      html += '<br><span class="bn-detail">';
      var details = [];
      if (runes) details.push(runes);
      if (w.dur && w.dur !== '?') details.push(w.dur);
      if (w.score) details.push(w.score + ' pts');
      if (w.version && w.version !== '?') details.push('v' + esc(w.version));
      html += details.join(' · ');
      if (w.morgue_url) html += ' <a class="bn-morgue-link" href="' + esc(w.morgue_url) + '">[morgue]</a>';
      html += '</span>';
    } else {
      html += '<span class="bn-empty">No victories yet — the Orb awaits its first champion.</span>';
    }
    html += '</div>';

    // ── Card 2: Death of the Day ──
    html += '<div class="bn-card bn-death">';
    html += '<div class="bn-card-header">[rip] ' + esc(d.death_label || 'Death of the Day') + '</div>';
    if (d.death_of_day) {
      var dd = d.death_of_day;
      var dgod = dd.god ? ' of ' + esc(dd.god) : '';
      html += '<span class="bn-player">' + esc(dd.name) + '</span>';
      html += ' (L' + esc(dd.xl) + ' ';
      html += '<span class="bn-combo">' + esc(dd.race) + ' ' + esc(dd.cls) + '</span>';
      html += '<span class="bn-god">' + esc(dgod) + '</span>)';
      html += '<br>';
      if (dd.tmsg) {
        html += '<span class="bn-death-text">' + esc(dd.tmsg) + '</span>';
      } else if (dd.killer) {
        html += '<span class="bn-death-text">slain by ' + esc(dd.killer) + '</span>';
      }
      html += '<br><span class="bn-detail">';
      var ddetails = [];
      if (dd.place && dd.place !== '?') ddetails.push(esc(dd.place));
      if (dd.score) ddetails.push(dd.score + ' pts');
      if (dd.version && dd.version !== '?') ddetails.push('v' + esc(dd.version));
      html += ddetails.join(' · ');
      if (dd.morgue_url) html += ' <a class="bn-morgue-link" href="' + esc(dd.morgue_url) + '">[morgue]</a>';
      html += '</span>';
    } else {
      html += '<span class="bn-empty">No deaths recorded yet. The dungeon is quiet… for now.</span>';
    }
    html += '</div>';

    html += '</div>'; // end row 1

    // ── Row 2: Stats + MOTD ──
    html += '<div class="bn-row">';

    // ── Card 3: Server Stats ──
    html += '<div class="bn-card bn-stats">';
    html += '<div class="bn-card-header">[#] Server Activity</div>';
    var statsLine = '';
    statsLine += '<span class="bn-stat-num">' + (d.unique_players || 0).toLocaleString() + '</span> adventurers';
    statsLine += ' · ';
    statsLine += '<span class="bn-stat-num">' + (d.total_games || 0).toLocaleString() + '</span> games played';
    statsLine += ' · ';
    var winCount = d.total_wins || 0;
    statsLine += '<span class="bn-stat-num">' + winCount + '</span> ' + (winCount === 1 ? 'victory' : 'victories');
    html += statsLine;
    html += '<br><span class="bn-detail">';
    html += 'Today: <span class="bn-stat-num">' + (d.games_today || 0) + '</span> games';
    html += ' · ';
    html += 'This week: <span class="bn-stat-num">' + (d.games_this_week || 0) + '</span> games';
    html += '</span>';
    html += '</div>';

    // ── Card 4: Message of the Day ──
    if (d.motd) {
      html += '<div class="bn-card bn-motd">';
      html += '<div class="bn-card-header">[!] Message of the Day</div>';
      html += '<span class="bn-motd-text">' + esc(d.motd) + '</span>';
      if (d.newest_user) {
        html += '<br><span class="bn-motd-text">Welcome our newest adventurer, <span class="bn-newest-name">' + esc(d.newest_user) + '</span>!</span>';
      }
      html += '</div>';
    }

    html += '</div>'; // end row 2

    banner.innerHTML = html;
  }

  // Show placeholder while loading
  banner.innerHTML = '<div class="bn-row" style="min-height:80px"><div class="bn-card" style="flex:1"><span style="color:#666">Loading...</span></div></div>';

  // Fetch and render
  fetch('/scores/banner-stats.json', { cache: 'no-store' })
    .then(function(r) { return r.ok ? r.json() : null; })
    .then(function(data) { if (data) renderBanner(data); })
    .catch(function() {
      banner.innerHTML = '<div class="bn-row"><div class="bn-card" style="flex:1"><span class="bn-empty">Stats temporarily unavailable.</span></div></div>';
    });

  // Refresh every 60 seconds
  setInterval(function() {
    fetch('/scores/banner-stats.json', { cache: 'no-store' })
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) { if (data) renderBanner(data); })
      .catch(function() {});
  }, 60000);
})();
