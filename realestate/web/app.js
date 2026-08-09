/* 도쿄 7구 대규모 맨션 가격추이 — 뷰어
 *
 * 의존성 없음. data/*.json 을 읽어 SVG를 직접 그린다.
 * 색 규칙: 계열 색은 '구(区)'에 고정. 필터로 계열이 줄어도 남은 구의 색은
 * 바뀌지 않는다. 라이트 모드에서 대비가 낮은 슬롯이 있으므로, 값은 항상
 * 직접 라벨 + 표 보기로도 읽을 수 있게 한다(색만으로 정보를 주지 않는다).
 */

const SLOTS = 7;
const NS = 'http://www.w3.org/2000/svg';
const STAGE_LABEL = { used: '중고', new: '신축 분양' };

const state = {
  wards: new Set(),
  stage: 'used',
  range: 'all',
  scale: 'abs',
  hidden: new Set(),
  showTable: false,
};

const data = { market: null, changes: null, sources: null };
let wardOrder = [];
let wardNames = {};

/* ------------------------------------------------------------------ 유틸 */

const fmt1 = (n) => (n === null || n === undefined || Number.isNaN(n) ? '—' : n.toLocaleString('ja-JP', { maximumFractionDigits: 1 }));
const fmtPct = (n) => (n === null || n === undefined ? '—' : `${n > 0 ? '+' : ''}${n.toFixed(1)}%`);

function wardColor(code) {
  const i = wardOrder.indexOf(code);
  return `var(--series-${(i < 0 ? 0 : i % SLOTS) + 1})`;
}

function svg(tag, attrs = {}) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v !== null && v !== undefined) node.setAttribute(k, String(v));
  }
  return node;
}

function median(values) {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/** 보이는 기간 구간만 잘라낸다. */
function visiblePeriods() {
  const all = data.market?.listing_trends?.periods ?? [];
  if (state.range === 'all') return all;
  const n = Number(state.range);
  return all.slice(Math.max(0, all.length - n));
}

/** 지수 모드면 첫 관측=100 으로 환산한다. */
function scaleSeries(points) {
  if (state.scale !== 'idx') return points;
  const base = points.find((p) => p.value !== null)?.value;
  if (!base) return points;
  return points.map((p) => (p.value === null ? p : { ...p, value: (p.value / base) * 100, raw: p.value }));
}

function clipPoints(points, periods) {
  const keep = new Set(periods);
  return points.filter((p) => keep.has(p.period));
}

/* -------------------------------------------------------- 계열 만들기 */

/** 현재 필터에 맞는 메인 차트 계열. */
function mainSeries() {
  const trends = data.market?.listing_trends;
  if (!trends) return [];
  const periods = visiblePeriods();
  const wards = wardOrder.filter((w) => state.wards.has(w));

  if (state.stage === 'both') {
    // 14개 선을 겹치면 읽을 수 없다 → 선택 지역 종합 2개 선으로 요약하고,
    // 구별 내역은 아래 소규모 다중 차트가 담당한다.
    return ['used', 'new'].map((stage, i) => {
      const rows = trends.series.filter((s) => s.stage === stage && state.wards.has(s.ward_code));
      const points = periods.map((period) => {
        const values = rows
          .map((s) => s.points.find((p) => p.period === period)?.value)
          .filter((v) => v !== null && v !== undefined);
        const samples = rows.reduce((sum, s) => sum + (s.points.find((p) => p.period === period)?.samples ?? 0), 0);
        return { period, value: values.length ? Number(median(values).toFixed(1)) : null, samples };
      });
      return {
        id: `all|${stage}`,
        label: `선택 지역 ${STAGE_LABEL[stage]}`,
        color: `var(--series-${i + 1})`,
        dashed: stage === 'new',
        points: scaleSeries(points),
      };
    }).filter((s) => s.points.some((p) => p.value !== null));
  }

  return wards
    .map((code) => {
      const row = trends.series.find((s) => s.ward_code === code && s.stage === state.stage);
      if (!row) return null;
      return {
        id: row.id,
        label: wardNames[code] ?? code,
        color: wardColor(code),
        points: scaleSeries(clipPoints(row.points, periods)),
      };
    })
    .filter((s) => s && s.points.some((p) => p.value !== null));
}

/* ------------------------------------------------------------ 선 차트 */

function renderLineChart(host, opts) {
  const { series, periods, height = 300, valueSuffix = '', endLabels = true } = opts;
  host.textContent = '';

  if (!series.length || periods.length < 2) {
    const p = document.createElement('p');
    p.className = 'empty';
    p.textContent = '표시할 데이터가 없습니다. 지역이나 기간을 넓혀 보세요.';
    host.appendChild(p);
    return;
  }

  // clientWidth 는 레이아웃 직후 0 이 나올 수 있다. 0 을 폴백값으로 오인하면
  // viewBox 가 컨테이너보다 커져 차트가 통째로 축소된다 — 실측을 우선한다.
  const measured = Math.round(host.getBoundingClientRect().width) || host.clientWidth
    || host.parentElement?.getBoundingClientRect().width || 0;
  const width = Math.max(260, Math.round(measured) || 720);
  const shown = series.filter((s) => !state.hidden.has(s.id));

  // 끝점 라벨이 들어갈 만큼만 오른쪽 여백을 준다. 잘린 라벨은 없느니만 못하다.
  const labelWidth = (text) => text.length * 6.7 + 14;
  const longest = endLabels
    ? Math.max(0, ...shown.map((s) => {
        const last = [...s.points].reverse().find((p) => p.value !== null);
        return last ? labelWidth(`${s.label} ${fmt1(last.value)}`) : 0;
      }))
    : 0;
  const rightPad = endLabels ? Math.min(Math.max(58, longest), width * 0.34) : 18;

  const m = { t: 14, r: rightPad, b: 34, l: 52 };
  const iw = width - m.l - m.r;
  const ih = height - m.t - m.b;
  const values = shown.flatMap((s) => s.points.map((p) => p.value)).filter((v) => v !== null);
  if (!values.length) {
    const p = document.createElement('p');
    p.className = 'empty';
    p.textContent = '선택한 계열이 모두 숨겨져 있습니다.';
    host.appendChild(p);
    return;
  }

  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = (hi - lo) * 0.14 || Math.max(1, hi * 0.05);
  const scaleY = niceScale(lo - pad, hi + pad, height < 220 ? 4 : 5);
  const { y0, y1 } = scaleY;

  const x = (i) => m.l + (periods.length === 1 ? iw / 2 : (iw * i) / (periods.length - 1));
  const y = (v) => m.t + ih - ((v - y0) / (y1 - y0)) * ih;

  const root = svg('svg', { viewBox: `0 0 ${width} ${height}`, width, height, role: 'img', tabindex: '0' });
  root.setAttribute('aria-label', opts.ariaLabel || '가격추이 선 그래프');

  // 격자 — 실선 헤어라인, 눈에 띄지 않게
  for (const tick of scaleY.ticks) {
    root.appendChild(svg('line', { x1: m.l, x2: m.l + iw, y1: y(tick), y2: y(tick), stroke: 'var(--gridline)', 'stroke-width': 1 }));
    const label = svg('text', { x: m.l - 9, y: y(tick) + 4, 'text-anchor': 'end', fill: 'var(--text-muted)', 'font-size': 11 });
    label.style.fontVariantNumeric = 'tabular-nums';
    label.textContent = fmt1(tick);
    root.appendChild(label);
  }

  // x축 기준선 + 라벨 (분기가 많으면 솎아낸다)
  root.appendChild(svg('line', { x1: m.l, x2: m.l + iw, y1: m.t + ih, y2: m.t + ih, stroke: 'var(--baseline)', 'stroke-width': 1 }));
  // 폭에 맞춰 눈금을 솎아낸다. 라벨 하나에 최소 58px 은 줘야 안 겹친다.
  const maxTicks = Math.max(2, Math.floor(iw / 58));
  const step = Math.max(1, Math.ceil(periods.length / maxTicks));
  const lastIndex = periods.length - 1;
  periods.forEach((period, i) => {
    const isLast = i === lastIndex;
    if (i % step && !isLast) return;
    // 마지막 눈금이 직전 눈금과 붙으면 직전 쪽을 버린다
    if (!isLast && lastIndex - i < step * 0.6) return;
    const t = svg('text', { x: x(i), y: m.t + ih + 19, 'text-anchor': 'middle', fill: 'var(--text-muted)', 'font-size': 11 });
    t.style.fontVariantNumeric = 'tabular-nums';
    t.textContent = period;
    root.appendChild(t);
  });

  // 선 — 결측 구간은 잇지 않고 끊는다
  for (const s of shown) {
    for (const run of runs(s.points)) {
      if (run.length === 1) {
        root.appendChild(svg('circle', { cx: x(run[0].i), cy: y(run[0].value), r: 2.5, fill: s.color }));
        continue;
      }
      const d = run.map((p, k) => `${k ? 'L' : 'M'}${x(p.i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ');
      root.appendChild(svg('path', {
        d, fill: 'none', stroke: s.color, 'stroke-width': 2,
        'stroke-linejoin': 'round', 'stroke-linecap': 'round',
        'stroke-dasharray': s.dashed ? '6 4' : null,
      }));
    }
  }

  // 끝점 마커 + 직접 라벨 (겹치면 생략, 최대 4개)
  const ends = shown
    .map((s) => {
      const last = [...s.points].reverse().find((p) => p.value !== null);
      if (!last) return null;
      return { s, i: s.points.indexOf(last), value: last.value };
    })
    .filter(Boolean)
    .sort((a, b) => b.value - a.value);

  const placed = [];
  for (const end of ends) {
    const cx = x(end.i);
    const cy = y(end.value);
    root.appendChild(svg('circle', { cx, cy, r: 6, fill: 'var(--surface-1)' }));  // 2px 서피스 링
    root.appendChild(svg('circle', { cx, cy, r: 4, fill: end.s.color }));

    if (!endLabels || placed.length >= 4) continue;
    if (placed.some((p) => Math.abs(p - cy) < 15)) continue;   // 겹치면 스택하지 않고 생략
    const text = `${end.s.label} ${fmt1(end.value)}`;
    if (cx + 10 + labelWidth(text) > width) continue;          // 들어갈 자리가 없으면 범례에 맡긴다
    placed.push(cy);
    const t = svg('text', { x: cx + 10, y: cy + 4, fill: 'var(--text-secondary)', 'font-size': 11.5 });
    t.textContent = text;
    root.appendChild(t);
  }

  host.appendChild(root);
  attachCrosshair(host, root, { shown, periods, x, y, m, iw, ih, valueSuffix });
}

/** 세로 크로스헤어 + 툴팁. 키보드(←→)로도 같은 값을 읽을 수 있다. */
function attachCrosshair(host, root, ctx) {
  const { shown, periods, x, m, iw, ih, valueSuffix } = ctx;

  const rule = svg('line', { y1: m.t, y2: m.t + ih, stroke: 'var(--baseline)', 'stroke-width': 1, opacity: 0 });
  root.appendChild(rule);

  const tip = document.createElement('div');
  tip.className = 'tooltip';
  host.appendChild(tip);

  const hit = svg('rect', { x: m.l, y: m.t, width: iw, height: ih, fill: 'transparent', style: 'cursor:crosshair' });
  root.appendChild(hit);

  let index = -1;

  const show = (i) => {
    index = i;
    const px = x(i);
    rule.setAttribute('x1', px);
    rule.setAttribute('x2', px);
    rule.setAttribute('opacity', 0.55);

    const rows = shown
      .map((s) => ({ s, p: s.points[i] }))
      .filter((r) => r.p && r.p.value !== null)
      .sort((a, b) => b.p.value - a.p.value);

    tip.innerHTML = '';
    const head = document.createElement('div');
    head.className = 'tt-period';
    head.textContent = periods[i];
    tip.appendChild(head);

    if (!rows.length) {
      const none = document.createElement('div');
      none.className = 'tt-row';
      none.textContent = '표본 부족';
      tip.appendChild(none);
    }

    for (const { s, p } of rows) {
      const row = document.createElement('div');
      row.className = 'tt-row';
      const name = document.createElement('span');
      name.className = 'tt-name';
      const sw = document.createElement('span');
      sw.className = 'tt-swatch';
      sw.style.background = s.color;
      name.append(sw, document.createTextNode(s.label));
      const val = document.createElement('span');
      val.className = 'tt-val';
      val.textContent = `${fmt1(p.value)}${valueSuffix}` + (p.samples ? ` (n=${p.samples})` : '');
      row.append(name, val);
      tip.appendChild(row);
    }

    tip.classList.add('on');
    const left = Math.min(Math.max(px - 84, 4), host.clientWidth - tip.offsetWidth - 4);
    tip.style.left = `${left}px`;
    tip.style.top = `${m.t + 6}px`;
  };

  const hide = () => {
    rule.setAttribute('opacity', 0);
    tip.classList.remove('on');
  };

  const nearest = (evt) => {
    const rect = root.getBoundingClientRect();
    const rel = ((evt.clientX - rect.left) / rect.width) * root.viewBox.baseVal.width;
    const t = (rel - m.l) / iw;
    return Math.min(periods.length - 1, Math.max(0, Math.round(t * (periods.length - 1))));
  };

  hit.addEventListener('mousemove', (e) => show(nearest(e)));
  hit.addEventListener('mouseleave', hide);
  root.addEventListener('blur', hide);
  root.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const next = index < 0 ? periods.length - 1 : index + (e.key === 'ArrowRight' ? 1 : -1);
    show(Math.min(periods.length - 1, Math.max(0, next)));
  });
}

function runs(points) {
  const out = [];
  let cur = [];
  points.forEach((p, i) => {
    if (p.value === null || p.value === undefined) {
      if (cur.length) out.push(cur);
      cur = [];
    } else {
      cur.push({ ...p, i });
    }
  });
  if (cur.length) out.push(cur);
  return out;
}

/** 눈금이 딱 떨어지는 수(0/200/400…)가 되도록 간격을 먼저 정하고 경계를 맞춘다. */
function niceScale(lo, hi, targetTicks = 5) {
  const span = hi - lo || Math.abs(hi) || 1;
  const raw = span / targetTicks;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((f) => f * mag).find((s) => s >= raw) ?? 10 * mag;
  const y0 = Math.floor(lo / step) * step;
  const y1 = Math.ceil(hi / step) * step;
  const out = [];
  for (let v = y0; v <= y1 + step / 2; v += step) out.push(Number(v.toFixed(6)));
  return { y0, y1, ticks: out };
}

/* ------------------------------------------------------------ 막대 차트 */

function renderChangeChart(host, rows, suffix = '%') {
  host.textContent = '';
  if (!rows.length) {
    const p = document.createElement('p');
    p.className = 'empty';
    p.textContent = '변동률을 계산할 표본이 부족합니다.';
    host.appendChild(p);
    return;
  }

  const measured = Math.round(host.getBoundingClientRect().width) || host.clientWidth || 720;
  const width = Math.max(320, measured);
  const rowH = 34;
  const m = { t: 8, r: 62, b: 8, l: 84 };
  const height = m.t + m.b + rows.length * rowH;
  const iw = width - m.l - m.r;

  // 음수 쪽에 실제 있는 만큼만 폭을 준다 (반씩 나누면 한쪽이 텅 빈다)
  const maxPos = Math.max(0, ...rows.map((r) => r.value));
  const maxNeg = Math.max(0, ...rows.map((r) => -r.value));
  const total = maxPos + maxNeg || 1;
  const zero = m.l + (iw * maxNeg) / total;
  const perUnit = (iw - 6) / total;

  const root = svg('svg', { viewBox: `0 0 ${width} ${height}`, width, height, role: 'img' });
  root.setAttribute('aria-label', '기간 변동률 막대 그래프');

  rows.forEach((r, i) => {
    const cy = m.t + i * rowH + rowH / 2;
    const len = Math.max(2, Math.abs(r.value) * perUnit);
    const barH = 18;                                  // ≤24px
    const x0 = r.value >= 0 ? zero : zero - len;

    const name = svg('text', { x: m.l - 12, y: cy + 4, 'text-anchor': 'end', fill: 'var(--text-secondary)', 'font-size': 12.5 });
    name.textContent = r.label;
    root.appendChild(name);

    // 데이터 끝은 4px 라운드, 기준선 쪽은 각지게
    const rx = 4;
    const path = r.value >= 0
      ? `M${x0},${cy - barH / 2} H${x0 + len - rx} a${rx},${rx} 0 0 1 ${rx},${rx} V${cy + barH / 2 - rx} a${rx},${rx} 0 0 1 -${rx},${rx} H${x0} Z`
      : `M${x0 + len},${cy - barH / 2} H${x0 + rx} a${rx},${rx} 0 0 0 -${rx},${rx} V${cy + barH / 2 - rx} a${rx},${rx} 0 0 0 ${rx},${rx} H${x0 + len} Z`;
    root.appendChild(svg('path', { d: path, fill: r.color }));

    const val = svg('text', {
      x: r.value >= 0 ? x0 + len + 8 : x0 - 8,
      y: cy + 4,
      'text-anchor': r.value >= 0 ? 'start' : 'end',
      fill: 'var(--text-primary)',
      'font-size': 12.5,
    });
    val.style.fontVariantNumeric = 'tabular-nums';
    val.textContent = `${r.value > 0 ? '+' : ''}${r.value.toFixed(1)}${suffix}`;
    root.appendChild(val);
  });

  root.appendChild(svg('line', { x1: zero, x2: zero, y1: m.t, y2: height - m.b, stroke: 'var(--baseline)', 'stroke-width': 1 }));
  host.appendChild(root);
}

/* -------------------------------------------------------------- 렌더 */

function renderScope() {
  const host = document.getElementById('scope-chips');
  host.textContent = '';
  const trends = data.market?.listing_trends;
  const bits = [
    `대상 ${wardOrder.length}개 구`,
    `총 ${trends?.min_total_units ?? 200}세대 이상`,
    '中古 · 新築分譲',
    trends ? `${trends.periods[0]} – ${trends.periods[trends.periods.length - 1]}` : '',
  ].filter(Boolean);
  for (const b of bits) {
    const s = document.createElement('span');
    s.className = 'scope-chip';
    s.textContent = b;
    host.appendChild(s);
  }
}

function renderWardChips() {
  const host = document.getElementById('ward-chips');
  host.textContent = '';
  for (const code of wardOrder) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'chip';
    btn.style.color = wardColor(code);
    btn.setAttribute('aria-pressed', String(state.wards.has(code)));
    const dot = document.createElement('span');
    dot.className = 'dot';
    const text = document.createElement('span');
    text.style.color = 'var(--text-primary)';
    text.textContent = wardNames[code] ?? code;
    if (!state.wards.has(code)) text.style.color = 'var(--text-secondary)';
    btn.append(dot, text);
    btn.addEventListener('click', () => {
      if (state.wards.has(code)) {
        if (state.wards.size === 1) return;      // 최소 1개는 남긴다
        state.wards.delete(code);
      } else {
        state.wards.add(code);
      }
      renderWardChips();
      renderAll();
    });
    host.appendChild(btn);
  }
}

function renderTiles() {
  const host = document.getElementById('tiles');
  host.textContent = '';
  const trends = data.market?.listing_trends;
  if (!trends) return;

  const periods = visiblePeriods();
  const latest = periods[periods.length - 1];
  const first = periods[0];

  const pick = (stage, period) => {
    const values = trends.series
      .filter((s) => s.stage === stage && state.wards.has(s.ward_code))
      .map((s) => s.points.find((p) => p.period === period)?.value)
      .filter((v) => v !== null && v !== undefined);
    return values.length ? median(values) : null;
  };

  const usedNow = pick('used', latest);
  const usedThen = pick('used', first);
  const newNow = pick('new', latest);
  const gap = usedNow && newNow ? ((newNow / usedNow - 1) * 100) : null;

  const tiles = [
    {
      hero: true,
      label: `선택 지역 중고 坪単価 중앙값 · ${latest ?? '—'}`,
      value: fmt1(usedNow),
      unit: '万円/坪',
      delta: usedNow && usedThen ? { pct: (usedNow / usedThen - 1) * 100, since: first } : null,
    },
    {
      label: `신축 분양 坪単価 중앙값 · ${latest ?? '—'}`,
      value: fmt1(newNow),
      unit: '万円/坪',
    },
    {
      label: '신축 프리미엄 (중고 대비)',
      value: gap === null ? '—' : `+${gap.toFixed(0)}`,
      unit: '%',
    },
    {
      label: '오늘 신규 등록',
      value: String(data.changes?.summary?.new ?? 0),
      unit: '件',
      sub: `가격변경 ${data.changes?.summary?.price_changed ?? 0} · 게재종료 ${data.changes?.summary?.removed ?? 0}`,
    },
  ];

  for (const t of tiles) {
    const card = document.createElement('div');
    card.className = 'tile' + (t.hero ? ' hero' : '');
    const label = document.createElement('div');
    label.className = 'label';
    label.textContent = t.label;
    const value = document.createElement('div');
    value.className = 'value';
    value.textContent = t.value;
    const unit = document.createElement('span');
    unit.className = 'unit';
    unit.textContent = t.unit;
    value.appendChild(unit);
    card.append(label, value);

    if (t.delta) {
      const d = document.createElement('div');
      d.className = 'delta';
      const span = document.createElement('span');
      span.className = t.delta.pct >= 0 ? 'up' : 'down';
      span.textContent = fmtPct(t.delta.pct);
      d.append(span, document.createTextNode(` · ${t.delta.since} 대비`));
      card.appendChild(d);
    } else if (t.sub) {
      const d = document.createElement('div');
      d.className = 'delta';
      d.textContent = t.sub;
      card.appendChild(d);
    }
    host.appendChild(card);
  }
}

function renderMain() {
  const series = mainSeries();
  const periods = visiblePeriods();
  const suffix = state.scale === 'idx' ? '' : ' 万円/坪';

  document.getElementById('main-title').textContent =
    state.stage === 'both' ? '선택 지역 종합 — 중고 vs 신축 분양' : `구별 坪単価 추이 · ${STAGE_LABEL[state.stage]}`;
  document.getElementById('main-sub').textContent =
    (state.scale === 'idx' ? `${periods[0] ?? ''} = 100 지수` : '万円/坪 중앙값')
    + ` · 총 ${data.market?.listing_trends?.min_total_units ?? 200}세대 이상`
    + (state.stage === 'both' ? ' · 구별 내역은 아래 상세 참조' : '');

  renderLineChart(document.getElementById('main-chart'), {
    series, periods, height: 330, valueSuffix: suffix,
    ariaLabel: '구별 坪単価 추이',
  });
  renderLegend(document.getElementById('main-legend'), series);
  renderTable(document.getElementById('main-table'), series, periods);
}

function renderLegend(host, series) {
  host.textContent = '';
  if (series.length < 2) return;                 // 1계열이면 제목이 곧 범례다
  for (const s of series) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'legend-item';
    btn.style.color = s.color;
    btn.setAttribute('aria-pressed', String(!state.hidden.has(s.id)));
    const key = document.createElement('span');
    key.className = 'key';
    if (s.dashed) key.style.background = `repeating-linear-gradient(90deg, currentColor 0 5px, transparent 5px 9px)`;
    const text = document.createElement('span');
    text.style.color = 'var(--text-secondary)';
    text.textContent = s.label;
    btn.append(key, text);
    btn.addEventListener('click', () => {
      if (state.hidden.has(s.id)) state.hidden.delete(s.id);
      else state.hidden.add(s.id);
      renderMain();
    });
    host.appendChild(btn);
  }
  if (state.stage === 'both') {
    const note = document.createElement('span');
    note.className = 'legend-note';
    note.textContent = '실선 = 중고 · 파선 = 신축 분양';
    host.appendChild(note);
  }
}

function renderTable(host, series, periods) {
  host.hidden = !state.showTable;
  host.textContent = '';
  if (!state.showTable || !series.length) return;

  const table = document.createElement('table');
  const thead = document.createElement('thead');
  const hr = document.createElement('tr');
  hr.appendChild(Object.assign(document.createElement('th'), { textContent: '분기' }));
  for (const s of series) hr.appendChild(Object.assign(document.createElement('th'), { textContent: s.label }));
  thead.appendChild(hr);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  periods.forEach((period, i) => {
    const tr = document.createElement('tr');
    tr.appendChild(Object.assign(document.createElement('td'), { textContent: period }));
    for (const s of series) {
      const v = s.points[i]?.value;
      tr.appendChild(Object.assign(document.createElement('td'), { textContent: v === null || v === undefined ? '—' : fmt1(v) }));
    }
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  host.appendChild(table);
}

function renderFacets() {
  const host = document.getElementById('facets');
  host.textContent = '';
  const trends = data.market?.listing_trends;
  if (!trends) return;
  const periods = visiblePeriods();
  const pending = [];

  for (const code of wardOrder) {
    if (!state.wards.has(code)) continue;
    const rows = ['used', 'new']
      .map((stage) => {
        const row = trends.series.find((s) => s.ward_code === code && s.stage === stage);
        if (!row) return null;
        return {
          id: `${code}|${stage}|facet`,
          label: STAGE_LABEL[stage],
          color: wardColor(code),
          dashed: stage === 'new',
          points: clipPoints(row.points, periods),
        };
      })
      .filter(Boolean);

    if (!rows.length) continue;

    const box = document.createElement('div');
    box.className = 'facet';
    const h = document.createElement('h3');
    h.textContent = wardNames[code] ?? code;
    const meta = document.createElement('div');
    meta.className = 'facet-meta';
    const used = rows.find((r) => r.label === STAGE_LABEL.used);
    const last = used ? [...used.points].reverse().find((p) => p.value !== null) : null;
    meta.textContent = last ? `중고 ${fmt1(last.value)} 万円/坪 · ${last.period}` : '표본 부족';
    const chart = document.createElement('div');
    chart.className = 'chart-host';
    box.append(h, meta, chart);
    host.appendChild(box);
    pending.push({ chart, rows, code });
  }

  // 그리드가 자리를 잡은 뒤에 그린다 — 붙이자마자 재면 첫 칸의 폭이 0으로 나온다
  for (const { chart, rows, code } of pending) {
    renderLineChart(chart, {
      series: rows, periods, height: 168, endLabels: false,
      valueSuffix: ' 万円/坪', ariaLabel: `${wardNames[code]} 坪単価 추이`,
    });
  }
}

function renderChange() {
  const trends = data.market?.listing_trends;
  const host = document.getElementById('change-chart');
  if (!trends) return;
  const periods = visiblePeriods();
  const stage = state.stage === 'both' ? 'used' : state.stage;

  const rows = wardOrder
    .filter((code) => state.wards.has(code))
    .map((code) => {
      const row = trends.series.find((s) => s.ward_code === code && s.stage === stage);
      if (!row) return null;
      const pts = clipPoints(row.points, periods).filter((p) => p.value !== null);
      if (pts.length < 2) return null;
      const value = (pts[pts.length - 1].value / pts[0].value - 1) * 100;
      return { label: wardNames[code] ?? code, value, color: wardColor(code) };
    })
    .filter(Boolean)
    .sort((a, b) => b.value - a.value);

  document.getElementById('change-sub').textContent =
    `${periods[0] ?? ''} → ${periods[periods.length - 1] ?? ''} · ${STAGE_LABEL[stage]} 坪単価 중앙값 기준`;
  renderChangeChart(host, rows);
}

function renderOfficial() {
  const card = document.getElementById('official-card');
  const official = data.market?.official_trends;
  if (!official) { card.hidden = true; return; }
  card.hidden = false;

  const series = official.series
    .filter((s) => state.wards.has(s.ward_code))
    .map((s) => ({ id: s.id, label: s.ward, color: wardColor(s.ward_code), points: s.points }));

  renderLineChart(document.getElementById('official-chart'), {
    series, periods: official.periods, height: 280,
    valueSuffix: ' 万円/坪', ariaLabel: '국토교통성 성약가 추이',
  });
  renderLegend(document.getElementById('official-legend'), series);
}

function renderNewListings() {
  const host = document.getElementById('new-listings');
  host.textContent = '';
  const minUnits = data.market?.listing_trends?.min_total_units ?? 200;
  const wardNameSet = new Set(wardOrder.filter((w) => state.wards.has(w)).map((w) => wardNames[w]));

  const items = (data.changes?.new ?? [])
    .filter((x) => wardNameSet.has(x.city) && (x.total_units ?? 0) >= minUnits)
    .sort((a, b) => (b.price_yen ?? 0) - (a.price_yen ?? 0))
    .slice(0, 24);

  document.getElementById('new-sub').textContent =
    `${data.changes?.date ?? ''} 수집분 · 선택 지역 · ${minUnits}세대 이상 · ${items.length}건`;

  if (!items.length) {
    const p = document.createElement('p');
    p.className = 'empty';
    p.textContent = '조건에 맞는 신규 등록 물건이 없습니다.';
    host.appendChild(p);
    return;
  }

  const grid = document.createElement('div');
  grid.className = 'listing-grid';
  for (const x of items) {
    const code = Object.keys(wardNames).find((k) => wardNames[k] === x.city);
    const card = document.createElement('div');
    card.className = 'listing';

    const row1 = document.createElement('div');
    row1.className = 'row1';
    const ward = document.createElement('span');
    ward.className = 'ward';
    ward.style.color = 'var(--text-secondary)';
    const dot = document.createElement('span');
    dot.className = 'dot';
    dot.style.background = wardColor(code);
    ward.append(dot, document.createTextNode(x.city));
    row1.appendChild(ward);
    const badge = document.createElement('span');
    badge.className = 'badge ' + (x.stage === 'new' ? 'shinchiku' : 'new');
    badge.textContent = x.stage === 'new' ? '신축 분양' : '신규';
    row1.appendChild(badge);
    card.appendChild(row1);

    const name = document.createElement('div');
    name.className = 'name';
    name.textContent = x.title;
    card.appendChild(name);

    const price = document.createElement('div');
    price.className = 'price';
    price.textContent = `${fmt1(x.price_man)} 万円`;
    card.appendChild(price);

    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = [
      x.layout, x.area_m2 ? `${x.area_m2}㎡` : null,
      x.unit_price_man_per_tsubo ? `${fmt1(x.unit_price_man_per_tsubo)} 万円/坪` : null,
    ].filter(Boolean).join(' · ');
    card.appendChild(meta);

    const meta2 = document.createElement('div');
    meta2.className = 'meta';
    meta2.textContent = [
      x.total_units ? `総戸数 ${x.total_units}` : null,
      x.built_year ? `${x.built_year}年築` : null,
      x.station_labels?.[0],
    ].filter(Boolean).join(' · ');
    card.appendChild(meta2);

    grid.appendChild(card);
  }
  host.appendChild(grid);
}

function renderSources() {
  const host = document.getElementById('sources');
  host.textContent = '';
  const notes = Object.fromEntries((data.sources?.portals ?? []).map((p) => [p.key, p]));

  for (const s of data.sources?.status ?? []) {
    const row = document.createElement('div');
    row.className = 'source-row';

    const nm = document.createElement('div');
    nm.className = 'nm';
    nm.textContent = s.name;
    const st = document.createElement('span');
    st.className = `state ${s.state}`;
    st.textContent = s.state === 'ok' ? `연결됨 ${s.count}件` : s.state === 'error' ? '오류' : '미연결';
    const rs = document.createElement('div');
    rs.className = 'rs';
    rs.textContent = s.reason || notes[s.key]?.access_note || '';

    row.append(nm, st, rs);
    host.appendChild(row);
  }
}

function renderAll() {
  renderTiles();
  renderMain();
  renderFacets();
  renderChange();
  renderOfficial();
  renderNewListings();
}

/* --------------------------------------------------------------- 부트 */

function wireSegments() {
  const bind = (id, key, cb) => {
    document.getElementById(id).addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      for (const b of e.currentTarget.querySelectorAll('button')) b.setAttribute('aria-pressed', String(b === btn));
      state[key] = btn.dataset[key];
      state.hidden.clear();
      (cb || renderAll)();
    });
  };
  bind('stage-seg', 'stage');
  bind('range-seg', 'range');
  bind('scale-seg', 'scale');

  const toggle = document.getElementById('toggle-table');
  toggle.addEventListener('click', () => {
    state.showTable = !state.showTable;
    toggle.setAttribute('aria-expanded', String(state.showTable));
    toggle.textContent = state.showTable ? '표 닫기' : '표로 보기';
    renderMain();
  });
}

async function boot() {
  const load = async (name) => {
    try {
      const res = await fetch(`data/${name}.json`, { cache: 'no-store' });
      return res.ok ? await res.json() : null;
    } catch { return null; }
  };

  [data.market, data.changes, data.sources] = await Promise.all([
    load('market'), load('latest-changes'), load('sources'),
  ]);

  const trends = data.market?.listing_trends;
  if (!trends) {
    document.getElementById('main-chart').innerHTML =
      '<p class="empty">추이 데이터가 아직 없습니다. 수집기를 먼저 실행하세요 — <code>python3 -m realestate.collector.run</code></p>';
    return;
  }

  wardOrder = trends.ward_order ?? [];
  wardNames = trends.ward_names ?? {};
  state.wards = new Set(wardOrder);

  const banner = document.getElementById('synthetic-banner');
  banner.hidden = !trends.synthetic;
  if (trends.synthetic) {
    document.getElementById('synthetic-detail').textContent =
      `현재 연결된 소스는 샘플(架空データ)뿐입니다. 실제 도쿄 시세가 아니며, 판단 근거로 쓰면 안 됩니다. 출처: ${trends.source}`;
  }

  document.getElementById('generated').textContent =
    `생성 ${data.market.generated_at ?? '—'} · 추이 출처: ${trends.source}`
    + (data.market.official_trends ? ` · 성약가: ${data.market.official_trends.source}` : '');

  renderScope();
  renderWardChips();
  renderSources();   // 필터와 무관 — 한 번만 그린다
  wireSegments();
  renderAll();

  let raf;
  new ResizeObserver(() => {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(renderAll);
  }).observe(document.body);
}

boot();
