/* A small stand-in for the Claude dashboard runtime, so that the dashboard's own page code
   (dashboard/app.js, unchanged) runs on a plain website.

   It offers the same three calls the page uses:
     dash.data(name)        the rows of one data file, with a status: loading, ok or error
     dash.onData(fn)        run fn whenever the data or the page width changes
     dash.draw(name, fn)    draw every element marked data-draw="name" with fn

   It loads the ten data files from data/, redraws when the window is resized or the colour scheme
   changes, and shows a notice when the newest data is more than two days old. */
(function () {
  'use strict';

  var NAMES = ['history', 'today', 'indicators', 'turns', 'zones', 'blind', 'early', 'grades', 'baselines', 'strategy'];
  var STALE_AFTER_DAYS = 2;
  var version = document.documentElement.getAttribute('data-v') || '';
  var store = {};
  var draws = {};
  var onDatas = [];

  NAMES.forEach(function (n) { store[n] = { status: 'loading', data: [], columns: [] }; });

  function run(name) {
    var fn = draws[name];
    if (!fn) return;
    var draw = typeof fn === 'function' ? fn : fn.update;
    document.querySelectorAll('[data-draw="' + name + '"]').forEach(function (el) {
      if (el.closest('[hidden]')) return;
      try { draw(el); } catch (err) { console.error('Drawing "' + name + '" failed', err); }
    });
  }

  function runAll() {
    onDatas.forEach(function (fn) {
      try { fn(); } catch (err) { console.error(err); }
    });
    Object.keys(draws).forEach(run);
  }

  window.dash = {
    data: function (name) { return store[name] || { status: 'missing', data: [], columns: [] }; },
    onData: function (fn) { onDatas.push(fn); },
    draw: function (name, fn) { if (fn) draws[name] = fn; else run(name); }
  };

  function load(name) {
    return fetch('data/' + name + '.json?v=' + encodeURIComponent(version), { cache: 'no-cache' })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (json) {
        var rows = json && Array.isArray(json.rows) ? json.rows : [];
        store[name] = { status: 'ok', data: rows, columns: Object.keys(rows[0] || {}) };
      })
      .catch(function (err) {
        console.error('Could not load data/' + name + '.json', err);
        store[name] = { status: 'error', data: [], columns: [] };
      });
  }

  // The reading for day D uses the close at midnight UTC that ends D. Once more than two days have
  // passed since that close, two daily updates in a row have failed: say so above the dashboard.
  function staleCheck() {
    var box = document.getElementById('site-stale');
    var today = store.today;
    if (!box || today.status !== 'ok' || !today.data.length) return;
    var day = String(today.data[0].date || '').slice(0, 10);
    var close = Date.parse(day + 'T00:00:00Z');
    if (Number.isNaN(close)) return;
    close += 24 * 3600 * 1000;
    var ageDays = (Date.now() - close) / (24 * 3600 * 1000);
    if (ageDays <= STALE_AFTER_DAYS) { box.hidden = true; return; }
    var shown = typeof d3 !== 'undefined' ? d3.utcFormat('%-d %b %Y')(new Date(close - 1)) : day;
    box.textContent = 'These numbers use the close of ' + shown + '. The daily update has not come through for '
      + Math.floor(ageDays) + ' days, so they may be out of date.';
    box.hidden = false;
  }

  function start() {
    runAll();
    Promise.all(NAMES.map(load)).then(function () {
      runAll();
      staleCheck();
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();

  var timer = null;
  window.addEventListener('resize', function () {
    clearTimeout(timer);
    timer = setTimeout(runAll, 120);
  });
  var scheme = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  if (scheme && scheme.addEventListener) scheme.addEventListener('change', runAll);
})();
