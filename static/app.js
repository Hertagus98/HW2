const colors = ['#5ee1b2', '#6ca7ff', '#ffb86b', '#d98cff', '#ff718d', '#77d6e8'];
const $ = (selector) => document.querySelector(selector);
let selected = ['VOO', 'QQQ', 'SCHD'];
let latestData = null;
let logarithmic = false;
let details = {};
let tickers = [];
const weightState = {};
const dateNow = new Date();
$('#end').value = new Date(dateNow.getTime() - dateNow.getTimezoneOffset() * 60000).toISOString().slice(0, 10);

function message(text) {
  $('#message').textContent = text;
  $('#message').classList.toggle('hidden', !text);
}

function renderTickers() {
  $('#ticker-list').replaceChildren();
  tickers.forEach((ticker) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'ticker' + (selected.includes(ticker) ? ' selected' : '');
    button.textContent = ticker;
    button.title = details[ticker];
    button.setAttribute('aria-pressed', String(selected.includes(ticker)));
    const description = document.createElement('small');
    description.textContent = details[ticker];
    button.append(description);
    button.onclick = () => {
      if (selected.includes(ticker)) selected = selected.filter((item) => item !== ticker);
      else if (selected.length < 6) selected.push(ticker);
      else { message('최대 6개 ETF를 선택할 수 있습니다.'); return; }
      renderTickers();
      renderWeights();
    };
    $('#ticker-list').append(button);
  });
}

function renderWeights() {
  const container = $('#weight-inputs');
  container.replaceChildren();
  const heading = document.createElement('div');
  heading.className = 'weight-row';
  ['ETF', 'A (%)', 'B (%)'].forEach((label) => {
    const span = document.createElement('span');
    span.textContent = label;
    heading.append(span);
  });
  container.append(heading);
  selected.forEach((ticker, index) => {
    if (!weightState[ticker]) {
      const even = Math.floor(100 / Math.max(selected.length, 1));
      weightState[ticker] = [even, index === 0 ? 100 : 0];
    }
    const row = document.createElement('div');
    row.className = 'weight-row';
    const label = document.createElement('span');
    label.textContent = ticker;
    row.append(label);
    [0, 1].forEach((column) => {
      const input = document.createElement('input');
      Object.assign(input, {type: 'number', min: '0', max: '100', step: 'any', value: weightState[ticker][column]});
      input.setAttribute('aria-label', ticker + ' 포트폴리오 ' + (column === 0 ? 'A' : 'B') + ' 비중');
      input.oninput = () => { weightState[ticker][column] = Number(input.value); updateWeightTotals(); };
      row.append(input);
    });
    container.append(row);
  });
  updateWeightTotals();
}

function updateWeightTotals() {
  const totals = [0, 1].map((column) => selected.reduce((sum, ticker) => sum + weightState[ticker][column], 0));
  $('#weight-totals').textContent = '비중 합계 · A ' + totals[0].toFixed(2) + '% / B ' + totals[1].toFixed(2) + '% (각 100% 필요)';
}

$('#compare-weights').onchange = () => $('#weight-panel').classList.toggle('hidden', !$('#compare-weights').checked);
document.querySelectorAll('[data-start]').forEach((button) => {
  button.onclick = () => { $('#start').value = button.dataset.start; };
});

async function loadEtfs() {
  try {
    const response = await fetch('/api/etfs');
    if (!response.ok) throw Error('ETF 목록 조회 실패');
    const data = await response.json();
    tickers = data.etfs;
    details = data.details;
    renderTickers();
    renderWeights();
    // Provide exact 100% starting allocations.
    const even = Math.floor(100 / selected.length);
    selected.forEach((ticker, index) => {
      weightState[ticker][0] = index === selected.length - 1 ? 100 - even * (selected.length - 1) : even;
    });
    renderWeights();
  } catch (error) { message(error.message); }
}
loadEtfs();

$('#conditions').onsubmit = async (event) => {
  event.preventDefault();
  const button = $('#run');
  if (!selected.length) { message('ETF를 하나 이상 선택해주세요.'); return; }
  const payload = {
    tickers: selected,
    initial_investment: Number($('#initial').value),
    monthly_contribution: Number($('#monthly').value),
    start_date: $('#start').value,
    end_date: $('#end').value,
    compare_strategies: $('#compare-strategies').checked,
    portfolios: []
  };
  if ($('#compare-weights').checked) {
    payload.portfolios = [0, 1].map((column) => ({
      name: '포트폴리오 ' + (column === 0 ? 'A' : 'B'),
      weights: Object.fromEntries(selected.map((ticker) => [ticker, weightState[ticker][column]]))
    }));
    if (payload.portfolios.some((portfolio) => Math.abs(Object.values(portfolio.weights).reduce((a, b) => a + b, 0) - 100) > 0.001)) {
      message('포트폴리오 A와 B의 비중 합계를 각각 100%로 설정하세요.');
      return;
    }
  }
  button.disabled = true;
  button.textContent = '데이터 조회 중…';
  latestData = null;
  $('#download-csv').disabled = true;
  message('');
  try {
    const response = await fetch('/api/backtest', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    const data = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map((item) => item.msg).join(' / ') : data.detail;
      throw Error(detail || '백테스트 실행 실패');
    }
    latestData = data;
    await show(data);
    message(data.warnings.join(' '));
  } catch (error) {
    message(error.message);
    $('#subtitle').textContent = '이번 조회는 실패했습니다. 표시된 그래프가 있으면 이전 결과입니다.';
  } finally {
    button.disabled = false;
    button.textContent = '백테스트 실행';
  }
};

function won(value) {
  return new Intl.NumberFormat('ko-KR', {style: 'currency', currency: 'KRW', maximumFractionDigits: 0}).format(value);
}

async function show(data) {
  if (typeof Plotly === 'undefined') throw Error('차트 라이브러리를 불러오지 못했습니다. 인터넷 연결 후 새로고침하세요.');
  const traces = [];
  const principals = new Set();
  data.results.forEach((result, index) => {
    traces.push({x: result.dates, y: result.value, name: result.label, mode: 'lines',
      line: {color: colors[index % colors.length], width: 2, dash: result.strategy === 'lump_sum' ? 'dash' : 'solid'}});
    const signature = JSON.stringify([result.dates, result.invested]);
    if (!principals.has(signature)) {
      principals.add(signature);
      traces.push({x: result.dates, y: result.invested, name: result.strategy === 'lump_sum' ? '일시금 원금' : '적립식 원금',
        mode: 'lines', line: {color: '#738198', dash: 'dot', width: 1}});
    }
  });
  await Plotly.react('chart', traces, {
    paper_bgcolor: 'transparent', plot_bgcolor: 'transparent', font: {color: '#91a0b6'},
    margin: {l: 65, r: 20, t: 10, b: 70}, hovermode: 'x unified',
    xaxis: {gridcolor: '#203047', autorange: true},
    yaxis: {gridcolor: '#203047', tickprefix: '₩', tickformat: '.2s', type: logarithmic ? 'log' : 'linear', autorange: true},
    legend: {orientation: 'h', y: -0.18}, uirevision: JSON.stringify([data.requested_start, data.requested_end, data.results.map((r) => r.label)])
  }, {responsive: true, displayModeBar: false});
  $('#subtitle').textContent = '요청 기간 ' + data.requested_start + ' ~ ' + data.requested_end;
  $('#request-summary').textContent = '실제 계산 기간 · ' + data.results.map((r) => r.label + ' ' + r.dates[0] + ' ~ ' + r.dates.at(-1)).join(' / ');
  $('#metrics').replaceChildren();
  data.results.forEach((result) => {
    const card = document.createElement('div');
    card.className = 'metric';
    const label = document.createElement('p');
    label.textContent = result.label;
    const value = document.createElement('b');
    value.textContent = won(result.final_value);
    const description = document.createElement('p');
    description.textContent = '원금 ' + won(result.total_invested) + ' · 누적 ' + result.return_pct + '%';
    const metrics = document.createElement('p');
    metrics.textContent = 'XIRR ' + result.money_weighted_return_pct + '% · MDD ' + result.mdd_pct + '%';
    card.append(label, value, description, metrics);
    if (result.weights) {
      const weights = document.createElement('p');
      weights.textContent = Object.entries(result.weights).map(([ticker, weight]) => ticker + ' ' + weight + '%').join(' / ');
      card.append(weights);
    }
    $('#metrics').append(card);
  });
  $('#download-csv').disabled = false;
}

$('#scale-toggle').onclick = () => {
  logarithmic = !logarithmic;
  $('#scale-toggle').textContent = logarithmic ? '선형 축' : '로그 축';
  $('#scale-toggle').setAttribute('aria-pressed', String(logarithmic));
  if (latestData) Plotly.relayout('chart', {'yaxis.type': logarithmic ? 'log' : 'linear', 'yaxis.autorange': true});
};

function csvCell(value) {
  return '"' + String(value).replaceAll('"', '""') + '"';
}

$('#download-csv').onclick = () => {
  if (!latestData) return;
  const results = latestData.results;
  const dates = [...new Set(results.flatMap((r) => r.dates))].sort();
  const lookup = results.map((r) => new Map(r.dates.map((date, index) => [date, [r.value[index], r.invested[index]]])));
  const rows = [
    ['날짜', ...results.flatMap((r) => [r.label + ' 평가액', r.label + ' 누적 투자원금'])],
    ...dates.map((date) => [date, ...lookup.flatMap((map) => map.get(date) || ['', ''])])
  ];
  const csv = '\ufeff' + rows.map((row) => row.map(csvCell).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob([csv], {type: 'text/csv;charset=utf-8;'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'etf-backtest-' + latestData.requested_start + '.csv';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
