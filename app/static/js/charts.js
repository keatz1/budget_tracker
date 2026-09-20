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
  // Validated categorical palette: light step -> dark step (same hue, re-stepped for the dark surface).
  var LIGHT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'];
  var DARK = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];
  function isDark() {
    var t = document.documentElement.dataset.theme;
    return t ? t === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
  }
  function seriesColour(hex) {
    if (!hex) return css('--muted');
    var i = LIGHT.indexOf(hex.toLowerCase());
    return (i >= 0 && isDark()) ? DARK[i] : hex;
  }
  function palette() { return isDark() ? DARK : LIGHT; }
  return {
    chart: chart, seriesColour: seriesColour, palette: palette, money: money, moneyFull: moneyFull, rgba: rgba,
    accent: function (a) { return rgba(css('--accent') || '#0f766e', a); },
    muted: function (a) { return rgba(css('--muted') || '#6b7280', a); },
    danger: function (a) { return rgba(css('--danger') || '#b91c1c', a); },
  };
})();
