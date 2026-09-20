// Shared Chart.js setup: theme-aware colours, money ticks, one entry point.
var BT = (function () {
  function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
  function rgba(hex, a) {
    hex = hex.replace('#', '');
    if (hex.length === 3) hex = hex.split('').map(function (c) { return c + c; }).join('');
    var n = parseInt(hex, 16);
    return 'rgba(' + (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + (a === undefined ? 1 : a) + ')';
  }
  var sym = (document.documentElement.dataset.currency || '$');
  function money(v) {
    var abs = Math.abs(v);
    var s = abs >= 1000 ? sym + (abs / 1000).toFixed(abs >= 10000 ? 0 : 1) + 'k' : sym + abs.toFixed(0);
    return v < 0 ? '-' + s : s;
  }
  function moneyFull(v) { return (v < 0 ? '-' : '') + sym + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function chart(id, cfg) {
    var el = document.getElementById(id);
    if (!el || !window.Chart) return null;
    Chart.defaults.color = css('--muted');
    Chart.defaults.borderColor = css('--border');
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    cfg.options = cfg.options || {};
    cfg.options.responsive = true;
    cfg.options.maintainAspectRatio = false;
    cfg.options.interaction = cfg.options.interaction || { mode: 'index', intersect: false };
    cfg.options.plugins = cfg.options.plugins || {};
    cfg.options.plugins.legend = cfg.options.plugins.legend || { position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true } };
    cfg.options.plugins.tooltip = cfg.options.plugins.tooltip || {};
    cfg.options.plugins.tooltip.callbacks = cfg.options.plugins.tooltip.callbacks || {
      label: function (c) { return c.dataset.label + ': ' + moneyFull(c.parsed.y !== undefined ? c.parsed.y : c.parsed); }
    };
    return new Chart(el, cfg);
  }
  return {
    chart: chart, money: money, moneyFull: moneyFull, rgba: rgba,
    accent: function (a) { return rgba(css('--accent') || '#0f766e', a); },
    muted: function (a) { return rgba(css('--muted') || '#6b7280', a); },
    danger: function (a) { return rgba(css('--danger') || '#b91c1c', a); },
  };
})();
