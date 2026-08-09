/* 도쿄 7구 대규모 맨션 가격추이 — 뷰어
 *
 * 의존성 없음. data/*.json 을 읽어 SVG를 직접 그린다.
 * 색 규칙: 계열 색은 '구(区)'에 고정. 필터로 계열이 줄어도 남은 구의 색은
 * 바뀌지 않는다. 라이트 모드에서 대비가 낮은 슬롯이 있으므로, 값은 항상
 * 직접 라벨 + 표 보기로도 읽을 수 있게 한다(색만으로 정보를 주지 않는다).
 */

const state = {
  wards: new Set(),
  stage: 'used',
  range: 'all',
  scale: 'abs',
  lang: 'ko',
  units: '500',
  station: null,       // 지도에서 역을 고르면 아래 매물이 그 역으로 좁혀진다
  showMapTable: false,
  hidden: new Set(),
  showTable: false,
};

const SLOTS = 7;
const NS = 'http://www.w3.org/2000/svg';

/* ------------------------------------------------------------------ 다국어
 * UI 문구·구 이름·단위만 번역한다. 물건명·역명·노선명은 원본 데이터의
 * 고유명사이므로 일본어 그대로 둔다 (한국어 이용자도 실제 검색에 그 표기를 쓴다).
 */

const WARD_KO = {
  '13101': '지요다구', '13102': '주오구', '13103': '미나토구', '13104': '신주쿠구',
  '13105': '분쿄구', '13108': '고토구', '13113': '시부야구',
};

const I18N = {
  ko: {
    htmlLang: 'ko',
    title: '도쿄 7구 대규모 맨션 가격추이',
    lede: '총 <strong>{units}세대 이상</strong> 맨션의 <strong>중고 호가</strong>와 <strong>신축 분양가</strong>를 구별·분기별 <strong>평당가 중앙값</strong>으로 추적합니다.',
    syntheticTitle: '지금 보이는 숫자는 전부 가상 데이터입니다',
    syntheticDetail: '실제 도쿄 시세가 아닙니다. 판단 근거로 쓰면 안 됩니다. 실제 데이터 소스를 연결하면 자동으로 교체됩니다. 출처: {source}',
    fArea: '지역', fStage: '구분', fPeriod: '기간', fScale: '표시',
    fUnits: '세대수',
    unitsOption: '{n}세대+',
    mapTitle: '역세권 지도 — 어디가 비싼가',
    mapSub: '{units}세대 이상 · {stage} · {n}개 역세권 · {from}–{to} 합산',
    mapEmpty: '{units}세대 이상 조건에서는 지도에 찍을 역세권이 부족합니다. 세대수 기준을 낮춰 보세요.',
    mapNote: '점 위치는 역 좌표(개략값)입니다. 행정 경계 지도가 아닙니다. 점을 누르면 아래 매물이 그 역세권으로 좁혀집니다.',
    mapMedian: '평당가 중앙값', mapSamples: '표본 수',
    mapLow: '저', mapHigh: '고', mapSizeKey: ' 점 크기 = 표본 수 (최대 {n})',
    mapColArea: '역세권',
    stationTitle: '역세권별 추이',
    stationSub: '{units}세대 이상 · {stage} · 최근 값이 높은 {n}곳 (반기 단위)',
    stationFilter: '{station} 만 보기 해제',
    stageUsed: '중고', stageNew: '신축 분양', stageBoth: '둘 다 비교',
    r3y: '3년', r5y: '5년', rAll: '전체',
    scaleAbs: '실제 금액', scaleIdx: '지수 =100',
    unitTsubo: '만엔/평', unitTsuboSuffix: ' 만엔/평', unitMan: '만엔',
    unitCase: '건', unitPctSign: '%',
    scopeWards: '대상 {n}개 구', scopeUnits: '총 {units}세대 이상', scopeKinds: '중고 · 신축 분양',
    tileHero: '선택 지역 중고 평당가 중앙값 · {period}',
    tileNew: '신축 분양 평당가 중앙값 · {period}',
    tilePremium: '신축 프리미엄 (중고 대비)',
    tileToday: '최근 신규 등록',
    tileSince: '{period} 대비',
    tileSub: '가격변경 {changed} · 게재종료 {removed}',
    mainTitleStage: '구별 평당가 추이 · {stage}',
    mainTitleBoth: '선택 지역 종합 — 중고 vs 신축 분양',
    mainSubIdx: '{base} = 100 지수', mainSubAbs: '만엔/평 중앙값',
    mainSubUnits: '총 {units}세대 이상', mainSubBoth: '구별 내역은 아래 상세 참조',
    tableOpen: '표로 보기', tableClose: '표 닫기', tableHeadPeriod: '분기',
    facetTitle: '구별 상세 — 중고 vs 신축 분양',
    facetSub: '각 구를 따로 떼어 보면 두 계열의 간격(신축 프리미엄)이 드러납니다. 실선 중고 · 파선 신축 분양.',
    facetMeta: '중고 {value} 만엔/평 · {period}',
    changeTitle: '기간 변동률',
    changeSub: '{from} → {to} · {stage} 평당가 중앙값 기준',
    officialTitle: '참고 — 국토교통성 성약가',
    officialSub: '실제로 거래가 성사된 가격입니다. 이 데이터에는 총세대수가 없어 <strong>세대수 필터가 적용되지 않은 구 전체 수치</strong>입니다. 호가보다 낮게 나오는 것이 정상입니다.',
    newTitle: '신규 매물',
    newSubWindow: '최근 {days}일 신규', newSubDate: '{date} 수집분',
    newSubTail: '선택 지역 · {units}세대 이상 · {n}건',
    newSubToday: '(오늘 {n}건)',
    badgeNew: '신규', badgeShinchiku: '신축 분양',
    srcTitle: '데이터 출처',
    srcSub: '각 포털에서 데이터를 받으려면 정당한 접근 경로가 필요합니다. 아래는 현재 연결 상태입니다.',
    srcOk: '연결됨 {n}건', srcErr: '오류', srcSkip: '미연결',
    emptyNoData: '표시할 데이터가 없습니다. 지역이나 기간을 넓혀 보세요.',
    emptyAllHidden: '선택한 계열이 모두 숨겨져 있습니다.',
    emptyNoChange: '변동률을 계산할 표본이 부족합니다.',
    emptyNoListings: '조건에 맞는 신규 등록 물건이 없습니다.',
    noSample: '표본 부족',
    legendNote: '실선 = 중고 · 파선 = 신축 분양',
    seriesAll: '선택 지역 {stage}',
    generated: '생성 {time} · 추이 출처: {source}',
    generatedOfficial: ' · 성약가: {source}',
    footNote: '평당가 = 가격 ÷ (전용면적 ÷ 3.30578). 각 분기 값은 <strong>중앙값</strong>이며, 표본이 기준 미만인 분기는 선을 잇지 않고 비워 둡니다.',
    bootEmpty: '추이 데이터가 아직 없습니다. 수집기를 먼저 실행하세요',
  },
  ja: {
    htmlLang: 'ja',
    title: '東京7区 大規模マンション価格推移',
    lede: '総戸数 <strong>{units}戸以上</strong> のマンションについて、<strong>中古の売出価格</strong>と<strong>新築分譲価格</strong>を、区別・四半期別の<strong>坪単価 中央値</strong>で追跡します。',
    syntheticTitle: '表示中の数値はすべて架空データです',
    syntheticDetail: '実際の東京の相場ではありません。判断材料には使えません。実データを接続すると自動的に置き換わります。出典: {source}',
    fArea: 'エリア', fStage: '種別', fPeriod: '期間', fScale: '表示',
    fUnits: '戸数',
    unitsOption: '{n}戸+',
    mapTitle: '駅エリア地図 — どこが高いか',
    mapSub: '{units}戸以上 · {stage} · {n}駅エリア · {from}–{to} 合算',
    mapEmpty: '{units}戸以上の条件では地図に出せる駅エリアが足りません。戸数の基準を下げてみてください。',
    mapNote: '点の位置は駅座標（概略値）です。行政界の地図ではありません。点を押すと下の物件がその駅エリアに絞り込まれます。',
    mapMedian: '坪単価 中央値', mapSamples: '標本数',
    mapLow: '低', mapHigh: '高', mapSizeKey: ' 点の大きさ = 標本数 (最大 {n})',
    mapColArea: '駅エリア',
    stationTitle: '駅エリア別 推移',
    stationSub: '{units}戸以上 · {stage} · 直近値の高い {n}カ所 (半期単位)',
    stationFilter: '{station} のみ表示を解除',
    stageUsed: '中古', stageNew: '新築分譲', stageBoth: '両方を比較',
    r3y: '3年', r5y: '5年', rAll: '全期間',
    scaleAbs: '実額', scaleIdx: '指数 =100',
    unitTsubo: '万円/坪', unitTsuboSuffix: ' 万円/坪', unitMan: '万円',
    unitCase: '件', unitPctSign: '%',
    scopeWards: '対象 {n}区', scopeUnits: '総戸数 {units}戸以上', scopeKinds: '中古 · 新築分譲',
    tileHero: '選択エリア 中古 坪単価 中央値 · {period}',
    tileNew: '新築分譲 坪単価 中央値 · {period}',
    tilePremium: '新築プレミアム (中古比)',
    tileToday: '直近の新着',
    tileSince: '{period} 比',
    tileSub: '価格変更 {changed} · 掲載終了 {removed}',
    mainTitleStage: '区別 坪単価 推移 · {stage}',
    mainTitleBoth: '選択エリア総合 — 中古 vs 新築分譲',
    mainSubIdx: '{base} = 100 指数', mainSubAbs: '万円/坪 中央値',
    mainSubUnits: '総戸数 {units}戸以上', mainSubBoth: '区別の内訳は下の詳細を参照',
    tableOpen: '表で見る', tableClose: '表を閉じる', tableHeadPeriod: '四半期',
    facetTitle: '区別詳細 — 中古 vs 新築分譲',
    facetSub: '区ごとに分けて見ると、två系列の差（新築プレミアム）が見えてきます。実線 中古 · 破線 新築分譲。',
    facetMeta: '中古 {value} 万円/坪 · {period}',
    changeTitle: '期間変動率',
    changeSub: '{from} → {to} · {stage} 坪単価 中央値ベース',
    officialTitle: '参考 — 国土交通省 成約価格',
    officialSub: '実際に取引が成立した価格です。このデータには総戸数が含まれないため、<strong>戸数の絞り込みを適用していない区全体の数値</strong>です。売出価格より低く出るのが正常です。',
    newTitle: '新着物件',
    newSubWindow: '直近{days}日の新着', newSubDate: '{date} 収集分',
    newSubTail: '選択エリア · {units}戸以上 · {n}件',
    newSubToday: '(本日 {n}件)',
    badgeNew: '新着', badgeShinchiku: '新築分譲',
    srcTitle: 'データ出典',
    srcSub: '各ポータルからデータを受け取るには正当なアクセス経路が必要です。以下は現在の接続状態です。',
    srcOk: '接続済み {n}件', srcErr: 'エラー', srcSkip: '未接続',
    emptyNoData: '表示できるデータがありません。エリアや期間を広げてください。',
    emptyAllHidden: '選択した系列がすべて非表示です。',
    emptyNoChange: '変動率を計算する標本が不足しています。',
    emptyNoListings: '条件に合う新着物件がありません。',
    noSample: '標本不足',
    legendNote: '実線 = 中古 · 破線 = 新築分譲',
    seriesAll: '選択エリア {stage}',
    generated: '生成 {time} · 推移の出典: {source}',
    generatedOfficial: ' · 成約価格: {source}',
    footNote: '坪単価 = 価格 ÷ (専有面積 ÷ 3.30578)。各四半期の値は<strong>中央値</strong>で、標本が基準未満の四半期は線をつながず空けています。',
    bootEmpty: '推移データがまだありません。先に収集を実行してください',
  },
};

function t(key, vars) {
  let text = I18N[state.lang]?.[key] ?? I18N.ko[key] ?? key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) text = text.split(`{${k}}`).join(String(v));
  }
  return text;
}

const stageLabel = (stage) => t(stage === 'new' ? 'stageNew' : 'stageUsed');

/** 구 이름 — 한국어면 한글 표기, 일본어면 원 표기. */
function wardLabel(code) {
  if (state.lang === 'ko' && WARD_KO[code]) return WARD_KO[code];
  return wardNames[code] ?? code;
}

/** 물건 데이터의 city 는 항상 일본어이므로 코드로 되짚어 번역한다. */
function wardLabelByName(name) {
  const code = Object.keys(wardNames).find((k) => wardNames[k] === name);
  return code ? wardLabel(code) : name;
}


const data = { market: null, changes: null, sources: null, recent: null };
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

/** 현재 세대수 기준의 데이터. 기준이 없으면 가장 가까운 것으로 대체한다. */
function pick(bucket) {
  if (!bucket) return null;
  if (bucket[state.units]) return bucket[state.units];
  const keys = Object.keys(bucket);
  return keys.length ? bucket[keys[keys.length - 1]] : null;
}

const trendsData = () => pick(data.market?.listing_trends);
const areaMapData = () => pick(data.market?.area_map);
const stationData = () => pick(data.market?.station_trends);

/** 보이는 기간 구간만 잘라낸다. */
function visiblePeriods() {
  const all = trendsData()?.periods ?? [];
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
  const trends = trendsData();
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
        label: t('seriesAll', { stage: stageLabel(stage) }),
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
        label: wardLabel(code),
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
    p.textContent = t('emptyNoData');
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
    p.textContent = t('emptyAllHidden');
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
    const tickLabel = svg('text', { x: x(i), y: m.t + ih + 19, 'text-anchor': 'middle', fill: 'var(--text-muted)', 'font-size': 11 });
    tickLabel.style.fontVariantNumeric = 'tabular-nums';
    tickLabel.textContent = period;
    root.appendChild(tickLabel);
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
    const endLabel = svg('text', { x: cx + 10, y: cy + 4, fill: 'var(--text-secondary)', 'font-size': 11.5 });
    endLabel.textContent = text;
    root.appendChild(endLabel);
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
      none.textContent = t('noSample');
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
    p.textContent = t('emptyNoChange');
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


/* -------------------------------------------------------------- 지도
 * 역 좌표에 점을 찍는다. 색은 '가격 수준'이라는 크기값이므로 한 색상의
 * 밝음→어두움 램프(시퀀셜)를 쓴다. 구를 구분하는 색(계열색)과는 별개다.
 * 점 크기는 표본 수 — 큰 점일수록 근거가 두텁다는 뜻.
 */

const SEQ = ['var(--seq-1)', 'var(--seq-2)', 'var(--seq-3)', 'var(--seq-4)', 'var(--seq-5)'];

function seqBins(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const at = (q) => sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))];
  return [at(0.2), at(0.4), at(0.6), at(0.8)];
}

const seqColor = (value, cuts) => SEQ[cuts.filter((c) => value > c).length];

function renderMap() {
  const card = document.getElementById('map-card');
  const host = document.getElementById('map-chart');
  const area = areaMapData();
  const stage = state.stage === 'both' ? 'used' : state.stage;

  const points = (area?.points ?? []).filter(
    (p) => p.stage === stage && state.wards.has(p.ward_code)
  );

  document.getElementById('map-sub').textContent = t('mapSub', {
    units: state.units,
    stage: stageLabel(stage),
    n: points.length,
    from: area?.periods?.[0] ?? '',
    to: area?.periods?.[area.periods.length - 1] ?? '',
  });

  host.textContent = '';
  if (points.length < 2) {
    card.hidden = false;
    const p = document.createElement('p');
    p.className = 'empty';
    p.textContent = t('mapEmpty', { units: state.units });
    host.appendChild(p);
    document.getElementById('map-legend').textContent = '';
    return;
  }
  card.hidden = false;

  const width = Math.max(320, Math.round(host.getBoundingClientRect().width) || 720);
  const height = Math.min(560, Math.max(360, width * 0.62));
  const m = { t: 18, r: 18, b: 30, l: 18 };

  // 위경도 → 화면. 위도 35.7°에서 경도 1°는 위도 1°보다 짧으므로 cos 보정.
  const midLat = points.reduce((a, p) => a + p.lat, 0) / points.length;
  const kx = Math.cos((midLat * Math.PI) / 180);
  const xs = points.map((p) => p.lon * kx);
  const ys = points.map((p) => p.lat);
  const pad = 0.006;
  const x0 = Math.min(...xs) - pad * kx, x1 = Math.max(...xs) + pad * kx;
  const y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;

  // 종횡비를 유지해야 지리적 거리가 왜곡되지 않는다
  const iw = width - m.l - m.r, ih = height - m.t - m.b;
  const scale = Math.min(iw / (x1 - x0), ih / (y1 - y0));
  const offX = m.l + (iw - (x1 - x0) * scale) / 2;
  const offY = m.t + (ih - (y1 - y0) * scale) / 2;
  const X = (lon) => offX + (lon * kx - x0) * scale;
  const Y = (lat) => offY + (y1 - lat) * scale;

  const cuts = seqBins(points.map((p) => p.median));
  const maxSamples = Math.max(...points.map((p) => p.samples));
  const radius = (n) => 6 + 12 * Math.sqrt(n / maxSamples);

  const root = svg('svg', { viewBox: `0 0 ${width} ${height}`, width, height, role: 'img' });
  root.setAttribute('aria-label', t('mapTitle'));

  const tip = document.createElement('div');
  tip.className = 'tooltip';
  host.appendChild(tip);

  // 큰 점이 작은 점을 덮지 않도록 큰 것부터 뒤에 깔고 작은 것을 위에
  const ordered = [...points].sort((a, b) => b.samples - a.samples);
  const placed = [];
  const dots = [];

  for (const p of ordered) {
    const cx = X(p.lon), cy = Y(p.lat), r = radius(p.samples);
    const g = svg('g', { style: 'cursor:pointer' });
    g.appendChild(svg('circle', { cx, cy, r: r + 2, fill: 'var(--surface-1)' }));  // 2px 서피스 링
    const dot = svg('circle', {
      cx, cy, r, fill: seqColor(p.median, cuts),
      stroke: state.station === p.station ? 'var(--text-primary)' : 'none',
      'stroke-width': state.station === p.station ? 2 : 0,
    });
    g.appendChild(dot);
    g.appendChild(svg('circle', { cx, cy, r: Math.max(r + 2, 13), fill: 'transparent' }));  // 히트 영역

    const label = state.lang === 'ko' ? p.label_ko : p.label_ja;
    const show = () => {
      tip.innerHTML = '';
      const head = document.createElement('div');
      head.className = 'tt-period';
      head.textContent = `${label} · ${wardLabelByName(p.ward)}`;
      tip.appendChild(head);
      for (const [k, v] of [
        [t('mapMedian'), `${fmt1(p.median)}${t('unitTsuboSuffix')}`],
        [t('mapSamples'), `${p.samples}${t('unitCase')}`],
      ]) {
        const row = document.createElement('div');
        row.className = 'tt-row';
        const nm = document.createElement('span');
        nm.className = 'tt-name';
        nm.textContent = k;
        const val = document.createElement('span');
        val.className = 'tt-val';
        val.textContent = v;
        row.append(nm, val);
        tip.appendChild(row);
      }
      tip.classList.add('on');
      tip.style.left = `${Math.min(Math.max(cx - 80, 4), host.clientWidth - tip.offsetWidth - 4)}px`;
      tip.style.top = `${Math.max(4, cy - tip.offsetHeight - 14)}px`;
    };
    g.addEventListener('mouseenter', show);
    g.addEventListener('mouseleave', () => tip.classList.remove('on'));
    g.addEventListener('click', () => {
      state.station = state.station === p.station ? null : p.station;
      renderMap();
      renderNewListings();
    });
    root.appendChild(g);

    dots.push({ cx, cy, r, label });
  }

  // 라벨은 점을 전부 깔고 난 뒤 맨 위에 얹는다. 섞어 그리면 나중 점이 앞 라벨을 덮는다.
  const labelLayer = svg('g', {});
  for (const d of dots) {
    if (placed.length >= 12) break;
    const lx = d.cx, ly = d.cy - d.r - 7;
    const halfWidth = d.label.length * 5.6 + 4;

    // 다른 라벨과도, 다른 점과도 겹치면 건다
    const hitsLabel = placed.some((q) => Math.abs(q.x - lx) < q.half + halfWidth && Math.abs(q.y - ly) < 14);
    const hitsDot = dots.some((o) => o !== d && Math.abs(o.cx - lx) < o.r + halfWidth && Math.abs(o.cy - ly) < o.r + 7);
    if (hitsLabel || hitsDot) continue;
    if (lx - halfWidth < 2 || lx + halfWidth > width - 2 || ly < 12) continue;

    placed.push({ x: lx, y: ly, half: halfWidth });
    const txt = svg('text', {
      x: lx, y: ly, 'text-anchor': 'middle',
      fill: 'var(--text-secondary)', 'font-size': 11,
      stroke: 'var(--surface-1)', 'stroke-width': 3, 'paint-order': 'stroke',
    });
    txt.textContent = d.label;
    labelLayer.appendChild(txt);
  }
  root.appendChild(labelLayer);

  host.appendChild(root);

  const note = document.createElement('p');
  note.className = 'map-note';
  note.textContent = t('mapNote');
  host.appendChild(note);

  renderMapLegend(cuts, maxSamples);
  renderMapTable(points);
}

function renderMapLegend(cuts, maxSamples) {
  const host = document.getElementById('map-legend');
  host.textContent = '';
  const wrap = document.createElement('div');
  wrap.className = 'scale-legend';

  const lo = document.createElement('span');
  lo.textContent = t('mapLow');
  const sw = document.createElement('span');
  sw.className = 'swatches';
  for (const c of SEQ) {
    const b = document.createElement('span');
    b.className = 'sw';
    b.style.background = c;
    sw.appendChild(b);
  }
  const hi = document.createElement('span');
  hi.textContent = t('mapHigh');
  wrap.append(lo, sw, hi);

  const size = document.createElement('span');
  size.className = 'size-key';
  for (const n of [0.25, 1]) {
    const b = document.createElement('span');
    b.className = 'bub';
    const r = 6 + 12 * Math.sqrt(n);
    b.style.width = `${r}px`;
    b.style.height = `${r}px`;
    size.appendChild(b);
  }
  size.append(document.createTextNode(t('mapSizeKey', { n: maxSamples })));
  wrap.appendChild(size);

  host.appendChild(wrap);
}

function renderMapTable(points) {
  const host = document.getElementById('map-table');
  host.hidden = !state.showMapTable;
  host.textContent = '';
  if (!state.showMapTable) return;

  const table = document.createElement('table');
  const thead = document.createElement('thead');
  const hr = document.createElement('tr');
  for (const label of [t('mapColArea'), t('fArea'), t('mapMedian'), t('mapSamples')]) {
    hr.appendChild(Object.assign(document.createElement('th'), { textContent: label }));
  }
  thead.appendChild(hr);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  for (const p of [...points].sort((a, b) => b.median - a.median)) {
    const tr = document.createElement('tr');
    const cells = [
      state.lang === 'ko' ? p.label_ko : p.label_ja,
      wardLabelByName(p.ward),
      fmt1(p.median),
      String(p.samples),
    ];
    cells.forEach((c) => tr.appendChild(Object.assign(document.createElement('td'), { textContent: c })));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  host.appendChild(table);
}

/* ------------------------------------------------- 역세권별 추이 */

function renderStationFacets() {
  const host = document.getElementById('station-facets');
  const card = document.getElementById('station-card');
  host.textContent = '';
  const st = stationData();
  const stage = state.stage === 'both' ? 'used' : state.stage;

  if (!st) { card.hidden = true; return; }
  card.hidden = false;

  const rows = st.series
    .filter((x) => x.stage === stage && state.wards.has(x.ward_code))
    .sort((a, b) => (b.latest ?? 0) - (a.latest ?? 0))
    .slice(0, 12);

  document.getElementById('station-sub').textContent = t('stationSub', {
    units: state.units, stage: stageLabel(stage), n: rows.length,
  });

  if (!rows.length) {
    const p = document.createElement('p');
    p.className = 'empty';
    p.textContent = t('mapEmpty', { units: state.units });
    host.appendChild(p);
    return;
  }

  const pending = [];
  for (const row of rows) {
    const box = document.createElement('div');
    box.className = 'facet';
    const h = document.createElement('h3');
    h.textContent = state.lang === 'ko' ? row.label_ko : row.label_ja;
    const meta = document.createElement('div');
    meta.className = 'facet-meta';
    meta.textContent = `${wardLabelByName(row.ward)} · ${fmt1(row.latest)}${t('unitTsuboSuffix')}`
      + (row.change_pct === null ? '' : ` · ${fmtPct(row.change_pct)}`);
    const chart = document.createElement('div');
    chart.className = 'chart-host';
    box.append(h, meta, chart);
    host.appendChild(box);
    pending.push({ chart, row });
  }

  for (const { chart, row } of pending) {
    renderLineChart(chart, {
      series: [{
        id: row.id,
        label: state.lang === 'ko' ? row.label_ko : row.label_ja,
        color: wardColor(row.ward_code),
        points: row.points,
      }],
      periods: st.periods,
      height: 150,
      endLabels: false,
      valueSuffix: t('unitTsuboSuffix'),
      ariaLabel: `${row.label_ja} ${t('unitTsubo')}`,
    });
  }
}

/* -------------------------------------------------------------- 렌더 */

function renderScope() {
  const host = document.getElementById('scope-chips');
  host.textContent = '';
  const trends = trendsData();
  const bits = [
    t('scopeWards', { n: wardOrder.length }),
    t('scopeUnits', { units: trends?.min_total_units ?? 500 }),
    t('scopeKinds'),
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
    text.textContent = wardLabel(code);
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
  const trends = trendsData();
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
      label: t('tileHero', { period: latest ?? '—' }),
      value: fmt1(usedNow),
      unit: t('unitTsubo'),
      delta: usedNow && usedThen ? { pct: (usedNow / usedThen - 1) * 100, since: first } : null,
    },
    {
      label: t('tileNew', { period: latest ?? '—' }),
      value: fmt1(newNow),
      unit: t('unitTsubo'),
    },
    {
      label: t('tilePremium'),
      value: gap === null ? '—' : `+${gap.toFixed(0)}`,
      unit: '%',
    },
    {
      label: t('tileToday'),
      value: String(data.recent?.count ?? data.changes?.summary?.new ?? 0),
      unit: t('unitCase'),
      sub: t('tileSub', {
        changed: data.changes?.summary?.price_changed ?? 0,
        removed: data.changes?.summary?.removed ?? 0,
      }),
    },
  ];

  // 반복 변수 이름은 t 를 피한다 — 번역 함수 t() 를 가려버린다
  for (const tile of tiles) {
    const card = document.createElement('div');
    card.className = 'tile' + (tile.hero ? ' hero' : '');
    const label = document.createElement('div');
    label.className = 'label';
    label.textContent = tile.label;
    const value = document.createElement('div');
    value.className = 'value';
    value.textContent = tile.value;
    const unit = document.createElement('span');
    unit.className = 'unit';
    unit.textContent = tile.unit;
    value.appendChild(unit);
    card.append(label, value);

    if (tile.delta) {
      const d = document.createElement('div');
      d.className = 'delta';
      const span = document.createElement('span');
      span.className = tile.delta.pct >= 0 ? 'up' : 'down';
      span.textContent = fmtPct(tile.delta.pct);
      d.append(span, document.createTextNode(` · ${t('tileSince', { period: tile.delta.since })}`));
      card.appendChild(d);
    } else if (tile.sub) {
      const d = document.createElement('div');
      d.className = 'delta';
      d.textContent = tile.sub;
      card.appendChild(d);
    }
    host.appendChild(card);
  }
}

function renderMain() {
  const series = mainSeries();
  const periods = visiblePeriods();
  const suffix = state.scale === 'idx' ? '' : t('unitTsuboSuffix');

  document.getElementById('main-title').textContent =
    state.stage === 'both' ? t('mainTitleBoth') : t('mainTitleStage', { stage: stageLabel(state.stage) });
  document.getElementById('main-sub').textContent =
    (state.scale === 'idx' ? t('mainSubIdx', { base: periods[0] ?? '' }) : t('mainSubAbs'))
    + ' · ' + t('mainSubUnits', { units: trendsData()?.min_total_units ?? 500 })
    + (state.stage === 'both' ? ' · ' + t('mainSubBoth') : '');

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
    note.textContent = t('legendNote');
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
  hr.appendChild(Object.assign(document.createElement('th'), { textContent: t('tableHeadPeriod') }));
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
  const trends = trendsData();
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
          stage,
          label: stageLabel(stage),
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
    h.textContent = wardLabel(code);
    const meta = document.createElement('div');
    meta.className = 'facet-meta';
    const used = rows.find((r) => r.stage === 'used');
    const last = used ? [...used.points].reverse().find((p) => p.value !== null) : null;
    meta.textContent = last
      ? t('facetMeta', { value: fmt1(last.value), period: last.period })
      : t('noSample');
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
      valueSuffix: t('unitTsuboSuffix'), ariaLabel: `${wardLabel(code)} ${t('unitTsubo')}`,
    });
  }
}

function renderChange() {
  const trends = trendsData();
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
      return { label: wardLabel(code), value, color: wardColor(code) };
    })
    .filter(Boolean)
    .sort((a, b) => b.value - a.value);

  document.getElementById('change-sub').textContent = t('changeSub', {
    from: periods[0] ?? '', to: periods[periods.length - 1] ?? '', stage: stageLabel(stage),
  });
  renderChangeChart(host, rows);
}

function renderOfficial() {
  const card = document.getElementById('official-card');
  const official = data.market?.official_trends;
  if (!official) { card.hidden = true; return; }
  card.hidden = false;

  const series = official.series
    .filter((s) => state.wards.has(s.ward_code))
    .map((s) => ({ id: s.id, label: wardLabel(s.ward_code), color: wardColor(s.ward_code), points: s.points }));

  renderLineChart(document.getElementById('official-chart'), {
    series, periods: official.periods, height: 280,
    valueSuffix: t('unitTsuboSuffix'), ariaLabel: t('officialTitle'),
  });
  renderLegend(document.getElementById('official-legend'), series);
}

function renderNewListings() {
  const host = document.getElementById('new-listings');
  host.textContent = '';
  const minUnits = trendsData()?.min_total_units ?? 500;
  const wardNameSet = new Set(wardOrder.filter((w) => state.wards.has(w)).map((w) => wardNames[w]));

  // 신규가 0건인 날에도 섹션이 비지 않도록 최근 며칠치를 굴려서 보여준다
  const pool = data.recent?.items?.length ? data.recent.items : (data.changes?.new ?? []);
  const windowDays = data.recent?.window_days;

  const items = pool
    .filter((x) => wardNameSet.has(x.city) && (x.total_units ?? 0) >= minUnits)
    .filter((x) => !state.station || x.sub_area === state.station)
    .sort((a, b) => (b.found_on ?? '').localeCompare(a.found_on ?? '') || (b.price_yen ?? 0) - (a.price_yen ?? 0))
    .slice(0, 24);

  document.getElementById('new-sub').textContent =
    (windowDays ? t('newSubWindow', { days: windowDays }) : t('newSubDate', { date: data.changes?.date ?? '' }))
    + ' · ' + t('newSubTail', { units: minUnits, n: items.length })
    + (data.changes?.summary ? ' ' + t('newSubToday', { n: data.changes.summary.new }) : '');

  const clear = document.getElementById('station-clear');
  if (clear) clear.remove();
  if (state.station) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'station-clear';
    btn.className = 'linkish';
    btn.style.marginBottom = '10px';
    btn.textContent = t('stationFilter', { station: state.station });
    btn.addEventListener('click', () => { state.station = null; renderMap(); renderNewListings(); });
    host.appendChild(btn);
  }

  if (!items.length) {
    const p = document.createElement('p');
    p.className = 'empty';
    p.textContent = t('emptyNoListings');
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
    ward.append(dot, document.createTextNode(wardLabelByName(x.city)));
    row1.appendChild(ward);
    const badge = document.createElement('span');
    badge.className = 'badge ' + (x.stage === 'new' ? 'shinchiku' : 'new');
    badge.textContent = x.stage === 'new' ? t('badgeShinchiku') : t('badgeNew');
    row1.appendChild(badge);
    card.appendChild(row1);

    const name = document.createElement('div');
    name.className = 'name';
    name.textContent = x.title;
    card.appendChild(name);

    const price = document.createElement('div');
    price.className = 'price';
    price.textContent = `${fmt1(x.price_man)} ${t('unitMan')}`;
    card.appendChild(price);

    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = [
      x.layout, x.area_m2 ? `${x.area_m2}㎡` : null,
      x.unit_price_man_per_tsubo ? `${fmt1(x.unit_price_man_per_tsubo)} ${t('unitTsubo')}` : null,
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
    st.textContent = s.state === 'ok' ? t('srcOk', { n: s.count }) : s.state === 'error' ? t('srcErr') : t('srcSkip');
    const rs = document.createElement('div');
    rs.className = 'rs';
    rs.textContent = s.reason || notes[s.key]?.access_note || '';

    row.append(nm, st, rs);
    host.appendChild(row);
  }
}

function renderAll() {
  applyLang();   // 세대수 기준이 바뀌면 안내 문구의 숫자도 같이 바뀌어야 한다
  renderTiles();
  renderMain();
  renderFacets();
  renderMap();
  renderStationFacets();
  renderChange();
  renderOfficial();
  renderNewListings();
}

/* --------------------------------------------------------------- 부트 */

function renderUnitsSeg() {
  const host = document.getElementById('units-seg');
  host.textContent = '';
  const options = data.market?.thresholds ?? [Number(state.units)];
  for (const n of options) {
    const b = document.createElement('button');
    b.type = 'button';
    b.dataset.units = String(n);
    b.setAttribute('aria-pressed', String(String(n) === state.units));
    b.textContent = t('unitsOption', { n });
    b.addEventListener('click', () => {
      state.units = String(n);
      state.station = null;
      state.hidden.clear();
      renderUnitsSeg();
      renderAll();
    });
    host.appendChild(b);
  }
}

/** 사전에 있는 문구를 화면에 바른다. */
function applyLang() {
  document.documentElement.lang = t('htmlLang');
  document.title = t('title');
  for (const el of document.querySelectorAll('[data-i18n]')) {
    el.textContent = t(el.dataset.i18n);
  }
  for (const el of document.querySelectorAll('[data-i18n-html]')) {
    el.innerHTML = t(el.dataset.i18nHtml, { units: trendsData()?.min_total_units ?? state.units });
  }
  for (const btn of document.querySelectorAll('#lang-seg button')) {
    btn.setAttribute('aria-pressed', String(btn.dataset.lang === state.lang));
  }
  document.getElementById('toggle-table').textContent = t(state.showTable ? 'tableClose' : 'tableOpen');
  document.getElementById('toggle-map-table').textContent = t(state.showMapTable ? 'tableClose' : 'tableOpen');
}

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
    toggle.textContent = t(state.showTable ? 'tableClose' : 'tableOpen');
    renderMain();
  });

  const mapToggle = document.getElementById('toggle-map-table');
  mapToggle.addEventListener('click', () => {
    state.showMapTable = !state.showMapTable;
    mapToggle.setAttribute('aria-expanded', String(state.showMapTable));
    mapToggle.textContent = t(state.showMapTable ? 'tableClose' : 'tableOpen');
    renderMap();
  });

  document.getElementById('lang-seg').addEventListener('click', (e) => {
    const btn = e.target.closest('button');
    if (!btn || btn.dataset.lang === state.lang) return;
    state.lang = btn.dataset.lang;
    try { localStorage.setItem('re-lang', state.lang); } catch { /* 저장 못해도 동작에는 지장 없다 */ }
    applyLang();
    renderScope();
    renderWardChips();
    renderUnitsSeg();
    renderSources();
    renderAll();
  });
}

async function boot() {
  // 단일 파일로 묶은 배포본은 데이터를 페이지 안에 심어 둔다 (fetch 불가 환경 대응).
  const embedded = window.__REALESTATE_DATA__;

  const load = async (name) => {
    if (embedded) return embedded[name] ?? null;
    try {
      const res = await fetch(`data/${name}.json`, { cache: 'no-store' });
      return res.ok ? await res.json() : null;
    } catch { return null; }
  };

  [data.market, data.changes, data.sources, data.recent] = await Promise.all([
    load('market'), load('latest-changes'), load('sources'), load('recent-new'),
  ]);

  const trends = trendsData();
  if (!trends) {
    document.getElementById('main-chart').innerHTML =
      '<p class="empty">추이 데이터가 아직 없습니다. 수집기를 먼저 실행하세요 — <code>python3 -m realestate.collector.run</code></p>';
    return;
  }

  wardOrder = trends.ward_order ?? [];
  wardNames = trends.ward_names ?? {};
  state.wards = new Set(wardOrder);

  applyLang();

  const banner = document.getElementById('synthetic-banner');
  banner.hidden = !trends.synthetic;
  if (trends.synthetic) {
    document.getElementById('synthetic-detail').textContent = t('syntheticDetail', { source: trends.source });
  }

  document.getElementById('generated').textContent =
    t('generated', { time: data.market.generated_at ?? '—', source: trends.source })
    + (data.market.official_trends ? t('generatedOfficial', { source: data.market.official_trends.source }) : '');

  renderScope();
  renderWardChips();
  renderUnitsSeg();
  renderSources();   // 필터와 무관 — 언어 바뀔 때만 다시 그린다
  wireSegments();
  renderAll();

  let raf;
  new ResizeObserver(() => {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(renderAll);
  }).observe(document.body);
}

boot();
