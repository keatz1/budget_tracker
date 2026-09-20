function toggleTheme() {
  var cur = document.documentElement.dataset.theme;
  var dark = cur ? cur === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
  var next = dark ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('theme', next); } catch (e) {}
}

// Flash messages fade.
document.addEventListener('DOMContentLoaded', function () {
  var f = document.getElementById('flash');
  if (f) setTimeout(function () { f.style.transition = 'opacity .5s'; f.style.opacity = '0'; }, 3500);
});

// Bottom sheet picker. Any element with data-sheet="#id" opens it; inside,
// buttons with data-value call the sheet's onpick(value, label).
var Sheet = {
  open: function (id, onpick) {
    var sheet = document.querySelector(id), bd = document.getElementById('sheet-backdrop');
    if (!sheet) return;
    sheet.onpick = onpick;
    sheet.classList.add('open'); bd.classList.add('open');
    var s = sheet.querySelector('input[type=search]');
    if (s) { s.value = ''; Sheet.filter(sheet, ''); if (window.innerWidth >= 900) s.focus(); }
  },
  close: function () {
    document.querySelectorAll('.sheet.open, .sheet-backdrop.open').forEach(function (e) { e.classList.remove('open'); });
  },
  filter: function (sheet, q) {
    q = q.toLowerCase();
    sheet.querySelectorAll('.options button').forEach(function (b) {
      b.classList.toggle('hidden', q && b.textContent.toLowerCase().indexOf(q) === -1);
    });
  }
};
document.addEventListener('click', function (e) {
  if (e.target.id === 'sheet-backdrop') Sheet.close();
  var b = e.target.closest('.sheet .options button');
  if (b) { var sheet = b.closest('.sheet'); if (sheet.onpick) sheet.onpick(b.dataset.value, b.dataset.label || b.textContent.trim()); Sheet.close(); }
});
document.addEventListener('input', function (e) {
  if (e.target.matches('.sheet input[type=search]')) Sheet.filter(e.target.closest('.sheet'), e.target.value);
});
document.addEventListener('keydown', function (e) { if (e.key === 'Escape') Sheet.close(); });
