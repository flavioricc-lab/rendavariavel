const API_BASE = '/api';

// State
let currentData = [];
let currentAsset = null;
let portfolios = {};

// DOM Elements
const portfolioSelect = document.getElementById('portfolioSelect');
const manualTickers = document.getElementById('manualTickers');
const tableHeader = document.getElementById('tableHeader');
const tableBody = document.getElementById('tableBody');
const assetSelect = document.getElementById('assetSelect');
const indicatorSelect = document.getElementById('indicatorSelect');
const statusBar = document.getElementById('statusBar');

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    fetchPortfolios();
});

function setStatus(msg) {
    statusBar.textContent = msg;
}

// Portfolios
async function fetchPortfolios() {
    try {
        const res = await fetch(`${API_BASE}/portfolios`);
        portfolios = await res.json();
        renderPortfolioOptions();
    } catch (e) {
        setStatus('Erro ao carregar carteiras');
        console.error(e);
    }
}

function renderPortfolioOptions() {
    portfolioSelect.innerHTML = '<option value="">Selecione...</option>';
    for (const name in portfolios) {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        portfolioSelect.appendChild(opt);
    }
}

async function fetchAndRender(tickers) {
    if (tickers.length === 0) {
        setStatus('Nenhum ativo selecionado.');
        return;
    }

    setStatus('Carregando dados...');
    try {
        const params = new URLSearchParams({ tickers: tickers.join(',') });
        const res = await fetch(`${API_BASE}/tickers?${params}`);
        if (!res.ok) throw new Error('Falha na API');

        currentData = await res.json();
        renderTable();
        updateAssetSelect();
        setStatus('Dados carregados com sucesso.');
    } catch (e) {
        setStatus('Erro ao buscar dados.');
        console.error(e);
    }
}

async function handleManualSearch() {
    // Clear others
    portfolioSelect.value = "";
    document.getElementById('fileInput').value = "";

    const manual = manualTickers.value.trim();
    if (!manual) {
        setStatus('Digite códigos de ativos.');
        return;
    }

    const tickers = manual.split(',').map(s => s.trim().toUpperCase()).filter(s => s);
    fetchAndRender([...new Set(tickers)]);
}

async function handlePortfolioLoad() {
    // Clear others
    manualTickers.value = "";
    document.getElementById('fileInput').value = "";

    const name = portfolioSelect.value;
    if (!name || !portfolios[name]) {
        setStatus('Selecione uma carteira.');
        return;
    }

    const tickers = portfolios[name];
    fetchAndRender(tickers);
}

async function uploadFile() {
    const fileInput = document.getElementById('fileInput');
    const file = fileInput.files[0];

    if (!file) {
        alert('Selecione um arquivo primeiro.');
        return;
    }

    // Clear others
    manualTickers.value = "";
    portfolioSelect.value = "";

    const formData = new FormData();
    formData.append('file', file);

    setStatus('Enviando arquivo...');

    try {
        const res = await fetch(`${API_BASE}/upload`, {
            method: 'POST',
            body: formData
        });

        if (!res.ok) {
            const errorData = await res.json().catch(() => ({}));
            throw new Error(errorData.detail || 'Falha no upload');
        }

        const data = await res.json();
        const tickers = data.tickers;

        if (tickers && tickers.length > 0) {
            manualTickers.value = tickers.join(', ');
            setStatus(`${tickers.length} ativos encontrados no arquivo.`);
            fetchAndRender(tickers);
        } else {
            setStatus('Nenhum ativo válido encontrado no arquivo.');
        }

    } catch (e) {
        setStatus(`Erro: ${e.message}`);
        console.error(e);
    }
}

async function savePortfolio() {
    const name = document.getElementById('newPortfolioName').value.trim();
    if (!name) {
        alert('Digite um nome para a carteira');
        return;
    }

    // Current valid tickers from data OR just parse the manual input?
    // Let's use the tickers currently in the View (currentData) as the source of truth for "what to save"
    // OR allow saving just the manual input?
    // Let's save the tickers currently loaded in currentData (which implies valid ones).
    if (!currentData.length) {
        alert('Carregue ativos primeiro.');
        return;
    }

    const tickers = currentData.map(d => d.ticker);

    try {
        const res = await fetch(`${API_BASE}/portfolios`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, tickers })
        });
        if (res.ok) {
            alert('Salvo!');
            fetchPortfolios(); // refresh list
        } else {
            alert('Erro ao salvar');
        }
    } catch (e) {
        console.error(e);
    }
}

async function deletePortfolio() {
    const name = portfolioSelect.value;
    if (!name) return;

    if (!confirm(`Excluir carteira ${name}?`)) return;

    try {
        const res = await fetch(`${API_BASE}/portfolios/${name}`, { method: 'DELETE' });
        if (res.ok) {
            fetchPortfolios();
            alert('Deletada');
        }
    } catch (e) {
        console.error(e);
    }
}

// Rendering
const COLUMNS = {
    'ticker': 'Ativo',
    'cotacao': 'Preço',
    'Preço Justo (Graham)': 'Graham',
    'Margem Graham %': 'Mg. Graham %',
    'Preço Teto (6%)': 'Teto (6%)',
    'Margem Barsi %': 'Mg. Barsi %',
    'dy': 'DY',
    'pl': 'P/L',
    'pvp': 'P/VP',
    'c5y': 'Cres',
    'ev_ebitda': 'EV/EBITDA',
    'return_on_equity': 'Return on Equity (ROE)'

};

function renderTable() {
    tableHeader.innerHTML = '';
    tableBody.innerHTML = '';

    if (currentData.length === 0) return;

    // Headers
    const headers = Object.keys(COLUMNS);
    headers.forEach(key => {
        const th = document.createElement('th');
        th.textContent = COLUMNS[key];
        tableHeader.appendChild(th);
    });

    // Body
    currentData.forEach(row => {
        const tr = document.createElement('tr');
        headers.forEach(key => {
            const td = document.createElement('td');
            let val = row[key];

            if (key === 'ticker') {
                val = val || '-';
            } else {
                // Convert to number if it's a string (e.g. "10,50")
                let num = val;
                if (typeof val === 'string' && val.includes(',')) {
                    num = parseFloat(val.replace(',', '.'));
                } else if (typeof val === 'string') {
                    num = parseFloat(val);
                }

                // Formatting
                if (num !== null && !isNaN(num) && typeof num === 'number') {
                    // Prioritize explicit BRL columns
                    if (['cotacao', 'Preço Justo (Graham)', 'Preço Teto (6%)'].includes(key)) {
                        val = num.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
                    } else if (key.includes('%') || key === 'dy') {
                        if (key === 'dy') val = (num * 100).toFixed(2) + '%';
                        else val = num.toFixed(2) + '%';
                    } else {
                        val = num.toFixed(2);
                    }

                    // Color Logic
                    if (key.includes('Margem') || key.includes('Mg.')) {
                        if (num > 0) td.classList.add('val-positive');
                        else if (num < 0) td.classList.add('val-negative');
                    }
                } else {
                    val = '-';
                }
            }

            td.textContent = val;
            tr.appendChild(td);
        });

        // Click to Select
        tr.style.cursor = 'pointer';
        tr.onclick = () => selectAsset(row.ticker);

        tableBody.appendChild(tr);
    });
}

function updateAssetSelect() {
    assetSelect.innerHTML = '<option value="">Selecione um ativo...</option>';
    currentData.forEach(d => {
        const opt = document.createElement('option');
        opt.value = d.ticker;
        opt.textContent = d.ticker;
        assetSelect.appendChild(opt);
    });
}

function selectAsset(ticker) {
    if (!ticker) return;
    assetSelect.value = ticker;
    currentAsset = ticker;
    updateDetails();
    updateChart();
}

function updateDetails() {
    const row = currentData.find(d => d.ticker === currentAsset);
    if (!row) return;

    // Build detail view
    let html = `<h4>${row.ticker}</h4><ul>`;
    for (const [key, label] of Object.entries(COLUMNS)) {
        let val = row[key];

        if (key === 'ticker') {
            val = val || '-';
        } else {
            let num = val;
            if (typeof val === 'string') num = parseFloat(val.replace(',', '.'));

            if (num !== null && !isNaN(num) && typeof num === 'number') {
                if (['cotacao', 'Preço Justo (Graham)', 'Preço Teto (6%)'].includes(key)) {
                    val = num.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
                } else if (key.includes('%') || key === 'dy') {
                    if (key === 'dy') val = (num * 100).toFixed(2) + '%';
                    else val = num.toFixed(2) + '%';
                } else {
                    val = num.toFixed(2);
                }
            } else {
                val = val || '-';
            }
        }

        html += `<li><strong>${label}:</strong> ${val}</li>`;
    }
    html += '</ul>';
    document.getElementById('assetDetails').innerHTML = html;
}

async function updateChart() {
    currentAsset = assetSelect.value;
    if (!currentAsset) return;

    const indicator = indicatorSelect.value;

    // Find current indicator value from data to pass if needed (or backend handles it?)
    // Backend takes optional indicator_value to forward fill if history missing
    const row = currentData.find(d => d.ticker === currentAsset);
    let indVal = 0.0;
    if (row && row[indicator] !== undefined) indVal = row[indicator];

    // If indicator is "Preço Atual", we just show price.
    // Actually backend handles "Preço Atual" exclusion or we just don't pass indicator params.

    setStatus(`Carregando gráfico de ${currentAsset}...`);
    try {
        let url = `${API_BASE}/history/${currentAsset}?indicator=${encodeURIComponent(indicator)}`;
        if (indVal) url += `&indicator_value=${indVal}`;

        const res = await fetch(url);
        if (!res.ok) throw new Error('Erro no gráfico');

        const data = await res.json();
        renderPlot(data);
        setStatus('Pronto');
    } catch (e) {
        setStatus('Erro ao carregar gráfico');
        console.error(e);
    }
}

function renderPlot(data) {
    const trace1 = {
        x: data.dates,
        y: data.prices,
        type: 'scatter',
        mode: 'lines',
        name: 'Preço',
        line: { color: '#ffffff', width: 1 }
    };

    const traces = [trace1];

    if (data.indicator_series && data.indicator_series.length > 0) {
        const trace2 = {
            x: data.dates,
            y: data.indicator_series,
            type: 'scatter',
            mode: 'lines',
            name: data.indicator_name,
            line: { color: '#ff4b4b', width: 2, dash: 'dot' }
        };
        traces.push(trace2);
    }

    const layout = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: '#fafafa' },
        margin: { t: 20, l: 40, r: 20, b: 40 },
        height: 400,
        xaxis: { showgrid: false },
        yaxis: { showgrid: true, gridcolor: '#333' }
    };

    Plotly.newPlot('chartDiv', traces, layout);
}
