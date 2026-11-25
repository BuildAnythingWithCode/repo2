/* Bitcoin Risk Metric dashboard.
   The words live in index.html; this file only draws what the data decides. */

// Zone edges are part of the metric's design (ZONES in src/btcrisk/model.py), not data.
const EDGES = [0, 0.2, 0.4, 0.6, 0.8, 1];
const zoneOf = (r) => (r < EDGES[1] ? 0 : r < EDGES[2] ? 1 : r < EDGES[3] ? 2 : r < EDGES[4] ? 3 : 4);
// Row order of the indicator chart. The labels themselves come from the data.
const FAMILY_ORDER = ['trend', 'onchain', 'range', 'momentum', 'miners', 'network', 'sentiment'];

const parseDay = d3.utcParse('%Y-%m-%d');
const fDay = d3.utcFormat('%-d %b %Y');
const num = (v) => (v === null || v === undefined || v === '' || Number.isNaN(+v) ? null : +v);
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const usd = (v) => (v >= 1000 ? d3.format('$,.0f')(v) : v >= 1 ? d3.format('$,.2f')(v) : d3.format('$.3f')(v));
const usdShort = (v) => (v >= 1e6 ? '$' + d3.format('.3~g')(v / 1e6) + 'M' : v >= 1e3 ? '$' + d3.format('.3~g')(v / 1e3) + 'k' : usd(v));
const usdTick = (v) => (v >= 1e6 ? '$' + d3.format('~g')(v / 1e6) + 'M' : v >= 1e3 ? '$' + d3.format('~g')(v / 1e3) + 'k'
  : v >= 1 ? '$' + d3.format('~g')(v) : '$' + d3.format('.2f')(v));

const F = {
  text: (v) => String(v),
  risk: (v) => d3.format('.2f')(+v),
  signed: (v) => d3.format('+.2f')(+v),
  usd: (v) => usd(+v),
  pct: (v) => d3.format('.0%')(+v),
  pctSigned: (v) => d3.format('+.0%')(+v),
  int: (v) => d3.format(',d')(Math.round(+v)),
  date: (v) => { const d = parseDay(String(v).slice(0, 10)); return d ? fDay(d) : String(v); },
  times: (v) => (+v >= 100 ? d3.format(',.0f')(+v) : d3.format('.1f')(+v)) + 'x',
};

/* ---------- small helpers ---------- */

// The one cell an element shows. A printed value is marked data-source + data-field + data-row (or
// data-where), which is also what Sources reads. A small graphic (a meter, a dot) carries data-source
// and names its column in data-f, since it prints no number to check.
function cell(el) {
  const d = dash.data(el.dataset.source);
  if (d.status !== 'ok') return { status: d.status, value: null };
  const rows = Array.isArray(d.data) ? d.data : [];
  let row;
  if (el.dataset.where !== undefined) {
    const conds = el.dataset.where.split('&').map((s) => s.split('=').map(decodeURIComponent));
    row = rows.find((r) => conds.every(([k, v]) => String(r[k]) === v));
  } else {
    row = rows[+(el.dataset.row || 0)];
  }
  const value = row ? row[el.dataset.field || el.dataset.f] : null;
  return { status: 'ok', value: value === undefined || value === '' ? null : value };
}

// Each chart and table has a line beside it, written in the page, for a failed load.
function flagError(el, failed) {
  const block = el.closest('.brm-block');
  if (block) block.querySelectorAll('.brm-err').forEach((p) => { p.hidden = !failed; });
}

function zoneName(i) {
  const n = document.querySelector('.brm [data-zone-name="' + i + '"]');
  return n ? n.textContent.trim() : '';
}

function node(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = text;
  return n;
}

function meterNodes(v, withTicks) {
  const z = zoneOf(v);
  const track = node('div', 'brm-track');
  for (let i = 0; i < 5; i += 1) track.append(node('i', 'brm-seg brm-z' + i + (i === z ? ' is-on' : '')));
  const pin = node('i', 'brm-pin');
  pin.style.left = (clamp(v, 0, 1) * 100).toFixed(2) + '%';
  const out = [track, pin];
  if (withTicks) {
    const ticks = node('div', 'brm-ticks');
    EDGES.forEach((e) => { const t = node('span', '', d3.format('~g')(e)); t.style.left = e * 100 + '%'; ticks.append(t); });
    out.push(ticks);
  }
  return out;
}

function textWidth(svg, cls, strings) {
  const t = svg.append('text').attr('class', cls).attr('x', -9999).attr('y', -9999);
  let w = 0;
  strings.forEach((s) => { t.text(s); w = Math.max(w, t.node().getComputedTextLength()); });
  t.remove();
  return w;
}

let historyCache = { src: null, rows: [] };
function historyRows(data) {
  if (historyCache.src !== data) {
    historyCache = {
      src: data,
      rows: data.map((r) => ({ t: parseDay(String(r.date).slice(0, 10)), price: num(r.price), risk: num(r.risk) }))
        .filter((r) => r.t && r.price !== null && r.price > 0),
    };
  }
  return historyCache.rows;
}

// Consecutive days in the same zone become one stretch of line. Each stretch runs on to the
// first point of the next, so the line has no gaps. z = -1 means "not scored yet".
function zoneRuns(rows) {
  const out = [];
  let cur = null;
  rows.forEach((r) => {
    const z = r.risk === null ? -1 : zoneOf(r.risk);
    if (!cur || cur.z !== z) {
      if (cur) cur.pts.push(r);
      cur = { z, pts: [r] };
      out.push(cur);
    } else {
      cur.pts.push(r);
    }
  });
  return out;
}

/* ---------- the page's width decides a few layout choices ---------- */

dash.onData(() => {
  document.querySelectorAll('.brm').forEach((root) => {
    root.classList.toggle('brm-is-narrow', root.clientWidth > 0 && root.clientWidth < 640);
  });
});

/* ---------- single values ---------- */

dash.draw('val', (el) => {
  const c = cell(el);
  el.classList.toggle('dash-skeleton', c.status === 'loading');
  const fmt = F[el.dataset.fmt] || F.text;
  el.textContent = c.status === 'ok' && c.value !== null ? fmt(c.value) : '—';
});

dash.draw('edge', (el) => {
  el.textContent = d3.format('~g')(EDGES[+el.dataset.i]);
});

dash.draw('zone-dot', (el) => {
  const c = cell(el);
  el.className = 'brm-dot' + (c.status === 'ok' && c.value !== null ? ' brm-z' + (+c.value) : '');
});

dash.draw('zone-pick', (el) => {
  const c = cell(el);
  const z = c.status === 'ok' && c.value !== null ? String(+c.value) : null;
  el.parentNode.querySelectorAll('[data-zone]').forEach((p) => { p.hidden = p.dataset.zone !== z; });
});

dash.draw('meter', (el) => {
  const c = cell(el);
  el.classList.toggle('dash-skeleton', c.status === 'loading');
  const v = c.status === 'ok' ? num(c.value) : null;
  if (v === null) { el.replaceChildren(); return; }
  el.replaceChildren(...meterNodes(v, el.dataset.ticks !== undefined));
});

/* ---------- price and reading over time ---------- */

function timeline(el, opt) {
  const H = dash.data('history');
  const T = dash.data('turns');
  el.classList.toggle('dash-skeleton', H.status === 'loading');
  flagError(el, H.status === 'error');
  if (H.status !== 'ok' || !Array.isArray(H.data) || !H.data.length) { el.replaceChildren(); return; }
  const W = el.clientWidth;
  if (!W) return;

  const all = historyRows(H.data);
  const rows = opt.days ? all.slice(-opt.days) : all;
  if (rows.length < 2) { el.replaceChildren(); return; }
  const t0 = rows[0].t;
  const t1 = rows[rows.length - 1].t;
  const turns = (T.status === 'ok' && Array.isArray(T.data) ? T.data : [])
    .map((r) => ({ t: parseDay(String(r.date).slice(0, 10)), price: num(r.price), risk: num(r.risk), kind: r.kind, name: r.name, big: /^cycle/i.test(String(r.size)) }))
    .filter((r) => r.t && r.t >= t0 && r.t <= t1 && r.price !== null && r.risk !== null);

  const hp = clamp(Math.round(W * (opt.days ? 0.36 : 0.44)), 210, opt.days ? 320 : 430);
  const hr = clamp(Math.round(W * 0.17), 110, 160);
  const gap = 22;
  const mt = 18;
  const mb = 26;
  const height = mt + hp + gap + hr + mb;

  const svg = d3.create('svg').attr('width', W).attr('height', height).attr('viewBox', '0 0 ' + W + ' ' + height)
    .attr('role', 'img').attr('aria-label', el.dataset.label || '');
  const tip = node('div', 'brm-tip');
  tip.hidden = true;
  el.replaceChildren(svg.node(), tip);

  // price scale
  const pmin = d3.min(rows, (d) => d.price);
  const pmax = d3.max(rows, (d) => d.price);
  let y;
  let pTicks;
  if (opt.log) {
    const lo = pmin / 1.7;
    const hi = pmax * 2.4;
    y = d3.scaleLog().domain([lo, hi]).range([mt + hp, mt]);
    pTicks = d3.range(Math.ceil(Math.log10(lo)), Math.floor(Math.log10(hi)) + 1).map((e) => 10 ** e);
  } else {
    y = d3.scaleLinear().domain([pmin * 0.9, pmax * 1.12]).nice(5).range([mt + hp, mt]);
    pTicks = y.ticks(5);
  }
  const rTop = mt + hp + gap;
  const yr = d3.scaleLinear().domain([0, 1]).range([rTop + hr, rTop]);

  // margins from the labels as drawn
  const last = rows[rows.length - 1];
  const endP = usdShort(last.price);
  const endR = last.risk === null ? '' : F.risk(last.risk);
  const ml = Math.ceil(textWidth(svg, 'brm-tick', pTicks.map(usdTick).concat(EDGES.map((e) => d3.format('~g')(e))))) + 10;
  const mr = Math.ceil(textWidth(svg, 'brm-endlabel', [endP, endR])) + 14;
  const plotW = W - ml - mr;
  if (plotW < 60) return;
  const x = d3.scaleUtc().domain([t0, t1]).range([ml, ml + plotW]);

  // grid and axes
  const gGrid = svg.append('g');
  pTicks.forEach((v) => {
    gGrid.append('line').attr('class', 'brm-gridline').attr('x1', ml).attr('x2', ml + plotW).attr('y1', y(v)).attr('y2', y(v));
    gGrid.append('text').attr('class', 'brm-tick').attr('x', ml - 8).attr('y', y(v)).attr('dy', '0.32em').attr('text-anchor', 'end').text(usdTick(v));
  });
  EDGES.forEach((v) => {
    gGrid.append('line').attr('class', v === 0 ? 'brm-baseline' : 'brm-gridline').attr('x1', ml).attr('x2', ml + plotW).attr('y1', yr(v)).attr('y2', yr(v));
    gGrid.append('text').attr('class', 'brm-tick').attr('x', ml - 8).attr('y', yr(v)).attr('dy', '0.32em').attr('text-anchor', 'end').text(d3.format('~g')(v));
  });
  // time ticks: as many as fit without touching
  const years = (t1 - t0) / (365.25 * 864e5);
  let xTicks;
  let xFmt;
  if (years > 4) {
    const per = plotW / years;
    const step = per >= 46 ? 1 : per >= 23 ? 2 : 4;
    xTicks = x.ticks(d3.utcYear.every(step));
    xFmt = d3.utcFormat('%Y');
  } else {
    const per = plotW / (years * 12);
    const step = per >= 24 ? 3 : 6;
    xTicks = x.ticks(d3.utcMonth.every(step));
    xFmt = d3.utcFormat('%b %Y');
  }
  xTicks.forEach((d) => {
    gGrid.append('line').attr('class', 'brm-baseline').attr('x1', x(d)).attr('x2', x(d)).attr('y1', rTop + hr).attr('y2', rTop + hr + 4);
    gGrid.append('text').attr('class', 'brm-tick').attr('x', x(d)).attr('y', rTop + hr + 18).attr('text-anchor', 'middle').text(xFmt(d));
  });

  // the lines
  const lineP = d3.line().x((d) => x(d.t)).y((d) => y(d.price));
  const lineR = d3.line().x((d) => x(d.t)).y((d) => yr(d.risk));
  const gLines = svg.append('g');
  zoneRuns(rows).forEach((run) => {
    if (run.pts.length < 2) return;
    if (run.z < 0) {
      gLines.append('path').attr('class', 'brm-line-nz').attr('d', lineP(run.pts));
      return;
    }
    gLines.append('path').attr('class', 'brm-line brm-zs' + run.z).attr('d', lineP(run.pts));
    gLines.append('path').attr('class', 'brm-line brm-zs' + run.z).attr('d', lineR(run.pts.filter((d) => d.risk !== null)));
  });

  // turning points: a dot on both panels, and the reading as a label where there is room
  const gTurns = svg.append('g');
  const placed = [];
  const labelW = textWidth(svg, 'brm-ptlabel', ['0.00']) + 4;
  turns.slice().sort((a, b) => (b.big - a.big) || (a.t - b.t)).forEach((t) => {
    const cx = x(t.t);
    const cy = y(t.price);
    const z = zoneOf(t.risk);
    gTurns.append('circle').attr('class', 'brm-pt brm-zf' + z).attr('cx', cx).attr('cy', cy).attr('r', 4.5);
    gTurns.append('circle').attr('class', 'brm-pt brm-zf' + z).attr('cx', cx).attr('cy', yr(t.risk)).attr('r', 4);
    const ly = cy + (t.kind === 'top' ? -10 : 19);
    const box = { x0: cx - labelW / 2, x1: cx + labelW / 2, y0: ly - 12, y1: ly + 3 };
    const clash = placed.some((b) => box.x0 < b.x1 && box.x1 > b.x0 && box.y0 < b.y1 && box.y1 > b.y0);
    if (!clash && box.x0 > ml && box.x1 < ml + plotW + mr) {
      placed.push(box);
      gTurns.append('text').attr('class', 'brm-ptlabel').attr('x', cx).attr('y', ly).attr('text-anchor', 'middle').text(F.risk(t.risk));
    }
  });

  // the latest values, written at the end of each line
  const gEnd = svg.append('g');
  gEnd.append('text').attr('class', 'brm-endlabel').attr('x', ml + plotW + 7).attr('y', y(last.price)).attr('dy', '0.32em').text(endP);
  if (last.risk !== null) {
    gEnd.append('text').attr('class', 'brm-endlabel').attr('x', ml + plotW + 7).attr('y', yr(last.risk)).attr('dy', '0.32em').text(endR);
  }

  // crosshair and tooltip
  const cross = svg.append('g').attr('visibility', 'hidden');
  const vline = cross.append('line').attr('class', 'brm-crossline').attr('y1', mt).attr('y2', rTop + hr);
  const dotP = cross.append('circle').attr('r', 4.5);
  const dotR = cross.append('circle').attr('r', 4.5);
  const bisect = d3.bisector((d) => d.t).center;

  function show(mx) {
    let i = bisect(rows, x.invert(clamp(mx, ml, ml + plotW)));
    let named = null;
    turns.forEach((t) => { if (!named && Math.abs(x(t.t) - mx) < 7) { named = t; i = bisect(rows, t.t); } });
    const d = rows[i];
    const px = x(d.t);
    const z = d.risk === null ? -1 : zoneOf(d.risk);
    cross.attr('visibility', 'visible');
    vline.attr('x1', px).attr('x2', px);
    dotP.attr('class', 'brm-pt ' + (z < 0 ? 'brm-dot-ctx' : 'brm-zf' + z)).attr('cx', px).attr('cy', y(d.price));
    dotR.attr('class', 'brm-pt brm-zf' + Math.max(z, 0)).attr('cx', px).attr('cy', z < 0 ? -99 : yr(d.risk)).attr('visibility', z < 0 ? 'hidden' : null);

    const head = node('div', 'brm-tip-head', fDay(d.t) + (named ? ' · ' + named.name : ''));
    const l1 = node('div', 'brm-tip-line', usd(d.price));
    const l2 = node('div', 'brm-tip-line');
    if (z < 0) {
      l2.append(node('span', '', zoneName(-1)));
    } else {
      l2.append(node('i', 'brm-dot brm-z' + z), node('span', '', F.risk(d.risk) + ' · ' + zoneName(z)));
    }
    tip.replaceChildren(head, l1, l2);
    tip.hidden = false;
    const tw = tip.offsetWidth;
    tip.style.left = Math.round(px + 14 + tw > W ? px - 14 - tw : px + 14) + 'px';
    // keep it off the price line: under the line when price is in the upper half, above it otherwise
    tip.style.top = Math.round(y(d.price) < mt + hp / 2 ? mt + hp - tip.offsetHeight - 6 : mt + 4) + 'px';
  }
  function hide() {
    cross.attr('visibility', 'hidden');
    tip.hidden = true;
  }
  svg.append('rect').attr('class', 'brm-hit').attr('x', ml).attr('y', mt).attr('width', plotW + mr).attr('height', hp + gap + hr)
    .on('pointermove', (ev) => show(d3.pointer(ev)[0]))
    .on('pointerdown', (ev) => show(d3.pointer(ev)[0]))
    .on('pointerleave', hide);
}

dash.draw('history-chart', (el) => timeline(el, { log: true }));
dash.draw('recent-chart', (el) => timeline(el, { log: false, days: 730 }));

/* ---------- every indicator today, by family ---------- */

dash.draw('ind-strip', (el) => {
  const D = dash.data('indicators');
  el.classList.toggle('dash-skeleton', D.status === 'loading');
  flagError(el, D.status === 'error');
  if (D.status !== 'ok' || !Array.isArray(D.data) || !D.data.length) { el.replaceChildren(); return; }
  const W = el.clientWidth;
  if (!W) return;

  const fams = FAMILY_ORDER.map((id) => {
    const members = D.data.filter((r) => r.family === id && num(r.score) !== null)
      .map((r) => ({ label: String(r.label), score: clamp(+r.score, 0, 1), value: r.value ? String(r.value) : '', role: String(r.role || ''), why: r.why_excluded ? String(r.why_excluded) : '', status: r.status }));
    return { id, label: members.length ? String(D.data.find((r) => r.family === id).family_label) : '', members };
  }).filter((f) => f.members.length);

  const svg = d3.create('svg').attr('role', 'img').attr('aria-label', el.dataset.label || '');
  const tip = node('div', 'brm-tip');
  tip.hidden = true;
  el.replaceChildren(svg.node(), tip);

  const side = W >= 640;
  const labelW = side ? Math.ceil(textWidth(svg, 'brm-rowlabel', fams.map((f) => f.label))) + 16 : 0;
  const ml = side ? labelW : 8;
  const mr = 12;
  const plotW = W - ml - mr;
  if (plotW < 60) return;
  const rowH = side ? 44 : 68;
  const mt = 8;
  const height = mt + fams.length * rowH + 26;
  svg.attr('width', W).attr('height', height).attr('viewBox', '0 0 ' + W + ' ' + height);
  const x = d3.scaleLinear().domain([0, 1]).range([ml, ml + plotW]);

  const g = svg.append('g');
  EDGES.forEach((e) => {
    g.append('line').attr('class', 'brm-gridline').attr('x1', x(e)).attr('x2', x(e)).attr('y1', mt).attr('y2', mt + fams.length * rowH);
    g.append('text').attr('class', 'brm-tick').attr('x', x(e)).attr('y', mt + fams.length * rowH + 16)
      .attr('text-anchor', e === 0 ? 'start' : e === 1 ? 'end' : 'middle').text(d3.format('~g')(e));
  });

  const radius = (m) => (m.status === 'core' ? 6 : 4);
  let lit = null;
  function hide() {
    if (lit) lit.classed('brm-dot-on', false);
    lit = null;
    tip.hidden = true;
  }
  function show(m, cx, cy, mark) {
    hide();
    lit = mark.classed('brm-dot-on', true);
    const z = zoneOf(m.score);
    const l1 = node('div', 'brm-tip-line');
    l1.append(node('i', 'brm-dot brm-z' + z), node('span', '', F.risk(m.score) + ' · ' + zoneName(z)));
    const kids = [node('div', 'brm-tip-head', m.label), l1];
    if (m.value) kids.push(node('div', 'brm-tip-line', m.value));
    kids.push(node('div', 'brm-tip-sub', m.why ? m.role + '. ' + m.why : m.role));
    tip.replaceChildren(...kids);
    tip.hidden = false;
    const tw = tip.offsetWidth;
    const th = tip.offsetHeight;
    tip.style.left = Math.round(clamp(cx - tw / 2, 0, W - tw)) + 'px';
    tip.style.top = Math.round(cy - th - 12 < 0 ? cy + 14 : cy - th - 12) + 'px';
  }

  fams.forEach((f, i) => {
    const top = mt + i * rowH;
    const mid = side ? top + rowH / 2 : top + 16 + (rowH - 16) / 2;
    if (i > 0) g.append('line').attr('class', 'brm-gridline').attr('x1', side ? 0 : ml).attr('x2', ml + plotW).attr('y1', top).attr('y2', top);
    g.append('text').attr('class', 'brm-rowlabel').attr('x', side ? 0 : ml).attr('y', side ? mid : top + 13).attr('dy', side ? '0.32em' : null).text(f.label);
    // place the dots: the ones in the score first, each nudged off the centre line if it would overlap
    const spots = [];
    f.members.slice().sort((a, b) => (a.status === 'core' ? 0 : 1) - (b.status === 'core' ? 0 : 1) || a.score - b.score).forEach((m) => {
      const r = radius(m);
      const cx = x(m.score);
      let cy = mid;
      const offsets = [0, -9, 9, -17, 17];
      for (let k = 0; k < offsets.length; k += 1) {
        cy = mid + offsets[k];
        const yy = cy;
        if (!spots.some((s) => Math.hypot(s.cx - cx, s.cy - yy) < s.r + r + 1.5)) break;
      }
      spots.push({ cx, cy, r, m });
    });
    spots.slice().reverse().forEach((s) => {
      const cls = s.m.status === 'core' ? 'brm-dot-core brm-zf' + zoneOf(s.m.score) : s.m.status === 'excluded' ? 'brm-dot-out' : 'brm-dot-ctx';
      const mark = g.append('circle').attr('class', cls).attr('cx', s.cx).attr('cy', s.cy).attr('r', s.r);
      s.mark = mark;
    });
    spots.forEach((s) => {
      g.append('circle').attr('class', 'brm-dot-hit').attr('cx', s.cx).attr('cy', s.cy).attr('r', Math.max(9, s.r + 4))
        .on('pointerenter', () => show(s.m, s.cx, s.cy, s.mark))
        .on('pointerdown', () => show(s.m, s.cx, s.cy, s.mark))
        .on('pointerleave', hide);
    });
  });
});

/* ---------- tables ---------- */

function table(name, source, pick, cols, rowClass) {
  dash.draw(name, (tb) => {
    const D = dash.data(source);
    flagError(tb, D.status === 'error');
    if (D.status !== 'ok' || !Array.isArray(D.data)) { tb.replaceChildren(); return; }
    const key = tb.closest('table').dataset.rowKey;
    const rows = pick ? pick(D.data) : D.data;
    tb.replaceChildren(...rows.map((r) => {
      const tr = document.createElement('tr');
      tr.setAttribute('data-key', String(r[key]));
      if (rowClass) { const c = rowClass(r); if (c) tr.className = c; }
      cols.forEach((col) => {
        const td = document.createElement('td');
        if (col.cls) td.className = col.cls;
        col.fill(td, r, rows);
        tr.append(td);
      });
      return tr;
    }));
  });
}

const txt = (field, cls) => ({ cls, fill: (td, r) => { td.textContent = r[field] === null || r[field] === undefined ? '' : String(r[field]); } });
const fmt = (field, f, cls) => ({ cls: 'brm-r' + (cls ? ' ' + cls : ''), fill: (td, r) => { const v = num(r[field]); td.textContent = v === null ? '—' : F[f](v); } });
const day = (field, cls) => ({ cls, fill: (td, r) => { td.textContent = r[field] ? F.date(r[field]) : ''; } });
const reading = (field, cls) => ({
  cls: 'brm-r' + (cls ? ' ' + cls : ''),
  fill: (td, r) => {
    const v = num(r[field]);
    if (v === null) { td.textContent = '—'; return; }
    const m = node('span', 'brm-meter brm-cellmeter');
    m.append(...meterNodes(clamp(v, 0, 1), false));
    td.append(node('span', '', F.risk(v)), m);
  },
});
const labelWhat = { fill: (td, r) => { td.append(node('span', '', String(r.label)), node('span', 'brm-cell-sub', String(r.what || ''))); } };

table('core-rows', 'indicators', (rows) => rows.filter((r) => r.status === 'core')
  .sort((a, b) => FAMILY_ORDER.indexOf(a.family) - FAMILY_ORDER.indexOf(b.family)), [
  labelWhat,
  txt('family_label', 'brm-wide-only'),
  txt('value'),
  reading('score'),
  fmt('score_30d_ago', 'risk', 'brm-wide-only'),
]);

table('all-rows', 'indicators', null, [
  { fill: (td, r) => { td.append(node('span', '', String(r.label))); if (r.why_excluded) td.append(node('span', 'brm-cell-sub', String(r.why_excluded))); } },
  txt('family_label', 'brm-wide-only'),
  txt('role'),
  fmt('score', 'risk'),
  fmt('skill', 'signed'),
  day('scored_since', 'brm-r brm-wide-only'),
], (r) => (r.status === 'core' ? 'brm-row-strong' : ''));

table('turn-rows', 'turns', null, [
  txt('name'),
  txt('size', 'brm-wide-only'),
  day('date', 'brm-wide-only'),
  fmt('price', 'usd'),
  reading('risk'),
]);

table('zone-rows', 'zones', null, [
  { fill: (td, r, rows) => { td.append(node('i', 'brm-dot brm-z' + rows.indexOf(r)), document.createTextNode(' ' + String(r.zone_name))); } },
  txt('zone', 'brm-wide-only'),
  fmt('days', 'int', 'brm-wide-only'),
  {
    fill: (td, r, rows) => {
      const v = num(r.median_fwd_return);
      if (v === null) { td.textContent = '—'; return; }
      const lo = Math.min(0, d3.min(rows, (d) => num(d.median_fwd_return)));
      const hi = Math.max(0, d3.max(rows, (d) => num(d.median_fwd_return)));
      const s = d3.scaleLinear().domain([lo, hi]).range([0, 100]);
      const bar = node('span', 'brm-bar');
      const zero = node('i', 'brm-bar-zero');
      zero.style.left = s(0) + '%';
      const fill = node('i', 'brm-bar-fill brm-z' + rows.indexOf(r) + (v < 0 ? ' brm-bar-neg' : ' brm-bar-pos'));
      fill.style.left = Math.min(s(0), s(v)) + '%';
      fill.style.width = Math.abs(s(v) - s(0)) + '%';
      bar.append(fill, zero);
      td.append(bar, node('span', '', F.pctSigned(v)));
    },
  },
  fmt('share_positive', 'pct'),
  fmt('median_worst_drawdown', 'pctSigned'),
]);

table('early-rows', 'early', null, [
  txt('name'),
  day('first_entry', 'brm-wide-only'),
  fmt('days_before_turn', 'int'),
  fmt('first_entry_gap', 'pctSigned'),
  fmt('days_in_zone', 'int', 'brm-wide-only'),
  fmt('avg_gap_in_zone', 'pctSigned'),
]);

table('blind-rows', 'blind', (rows) => rows.filter((r) => !/^variant/i.test(String(r.row_kind))), [
  txt('cycle'),
  txt('row_kind'),
  txt('recipe', 'brm-wide-only'),
  fmt('reading_at_top', 'risk'),
  fmt('reading_at_bottom', 'risk'),
  fmt('tracking', 'risk'),
], (r) => (/^final/.test(String(r.id)) ? '' : ''));

table('baseline-rows', 'baselines', null, [
  txt('name'),
  fmt('tracking', 'risk'),
  fmt('top_reading_mean', 'risk'),
  fmt('bottom_reading_mean', 'risk'),
  fmt('latest', 'risk'),
], (r) => (r.id === 'metric' ? 'brm-row-strong' : ''));

table('strategy-rows', 'strategy', null, [
  day('start'),
  txt('rule_name'),
  fmt('rule_final_multiple', 'times'),
  fmt('hold_final_multiple', 'times'),
  fmt('rule_max_drawdown', 'pctSigned'),
  fmt('hold_max_drawdown', 'pctSigned'),
]);
