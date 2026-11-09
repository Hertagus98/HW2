const tickers = ['VOO', 'QQQ', 'QLD', 'SCHD', 'SPY', 'VTI', 'IWM', 'BND'];
const colors = ['#5ee1b2', '#6ca7ff', '#ffb86b', '#d98cff', '#ff718d', '#77d6e8'];
let selected = ['VOO', 'QQQ', 'SCHD'];
let latestData = null;

const $ = (selector) => document.querySelector(selector);
const list = $('#ticker-list');
const end = $('#end');
end.value = new Date().toISOString().slice(0, 10);

function renderTickers() {
  list.innerHTML = tickers.map((ticker) => `<button class="ticker ${selected.includes(ticker) ? 'selected' : ''}" data-t="${ticker}">${ticker}</button>`).join('');
  document.querySelectorAll('.ticker').forEach((button) => {
    button.onclick = () => {
      const ticker = button.dataset.t;
      if (selected.includes(ticker)) selected = selected.filter((item) => item !== ticker);
      else if (selected.length < 6) selected.push(ticker);
      renderTickers();
    };
  });
}
renderTickers();

$('#run').onclick = async () => {
  const button = $('#run');
  const message = $('#message');
  if (!selected.length) {
    message.textContent = 'ETF를 하나 이상 선택해주세요.';
    message.classList.remove('hidden');
    return;
  }
  button.disabled = true;
  button.textContent = '데이터 조회 중...';
  $('#download-csv').disabled = true;
  message.classList.add('hidden');
  try {
    const response = await fetch('/api/backtest', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({tickers: selected, initial_investment: +$('#initial').value, monthly_contribution: +$('#monthly').value, start_date: $('#start').value, end_date: $('#end').value})
    });
    const data = await response.json();
    if (!response.ok) throw Error(data.detail || '백테스트에 실패했습니다.');
    latestData = data;
    show(data);
    if (data.warnings.length) { message.textContent = data.warnings.join(' '); message.classList.remove('hidden'); }
  } catch (error) {
    message.textContent = error.message;
    message.classList.remove('hidden');
  } finally {
    button.disabled = false;
    button.textContent = '백테스트 실행';
  }
};

function won(value) { return new Intl.NumberFormat('ko-KR', {style: 'currency', currency: 'KRW', maximumFractionDigits: 0}).format(value); }

function show(data) {
  const traces = data.results.map((result, index) => ({x: result.dates, y: result.value, name: result.ticker, mode: 'lines', line: {color: colors[index], width: 2}}));
  traces.push({x: data.results[0].dates, y: data.results[0].invested, name: '투자 원금', mode: 'lines', line: {color: '#738198', dash: 'dot', width: 1.5}});
  Plotly.newPlot('chart', traces, {paper_bgcolor: 'transparent', plot_bgcolor: 'transparent', font: {color: '#91a0b6'}, margin: {l: 55, r: 20, t: 10, b: 40}, hovermode: 'x unified', xaxis: {gridcolor: '#203047'}, yaxis: {gridcolor: '#203047', tickprefix: '₩', tickformat: '.2s'}, legend: {orientation: 'h', y: 1.12, x: 0}}, {responsive: true, displayModeBar: false});
  $('#subtitle').textContent = `${data.results[0].dates[0]} ~ ${data.results[0].dates.at(-1)} 기간별 투자 성과`;
  $('#metrics').innerHTML = data.results.map((result) => `<div class="metric"><p>${result.ticker} 최종 평가액</p><b>${won(result.final_value)}</b><em>${result.return_pct >= 0 ? '+' : ''}${result.return_pct}%</em><p>현금흐름 반영 수익률 ${result.money_weighted_return_pct}% · 납입금 제거 MDD ${result.mdd_pct}%</p></div>`).join('');
  $('#download-csv').disabled = false;
}

function csvCell(value) { return `"${String(value).replaceAll('"', '""')}"`; }

function downloadCsv() {
  if (!latestData) return;
  const results = latestData.results;
  const headers = ['날짜', ...results.flatMap((result) => [`${result.ticker} 평가액`, `${result.ticker} 누적 투자원금`])];
  const rowCount = Math.max(...results.map((result) => result.dates.length));
  const rows = [headers, ...Array.from({length: rowCount}, (_, index) => [
    results[0].dates[index] || '',
    ...results.flatMap((result) => [result.value[index] ?? '', result.invested[index] ?? ''])
  ])];
  const csv = '\ufeff' + rows.map((row) => row.map(csvCell).join(',')).join('\r\n');
  const blob = new Blob([csv], {type: 'text/csv;charset=utf-8;'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `etf-backtest-${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

$('#download-csv').onclick = downloadCsv;
