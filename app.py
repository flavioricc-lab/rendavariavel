import streamlit as st
import pandas as pd
import fundamentus
import yfinance as yf
import re
import numpy as np
import json
import os

PORTFOLIO_FILE = 'portfolios.json'

def get_historical_financials(ticker_symbol):
    """
    Attempts to fetch historical fundamentals from yfinance to build time-series for Graham and Barsi.
    Returns a DataFrame with columns: ['Preço Justo (Graham)', 'Preço Teto (6%)'] indexed by Date.
    """
    try:
        stock = yf.Ticker(f"{ticker_symbol}.SA")
        
        # 1. Get Price History (for index)
        hist = stock.history(period="5y")
        if hist.empty:
            return pd.DataFrame()
        
        dates = hist.index
        df_indicators = pd.DataFrame(index=dates)
        
        # 2. Graham: Sqrt(22.5 * LPA * VPA)
        # Try fetching financials
        fin = stock.quarterly_income_stmt
        bal = stock.quarterly_balance_sheet
        
        if not fin.empty and not bal.empty:
            # Transpose
            fin = fin.T.sort_index()
            bal = bal.T.sort_index()
            
            # Extract EPS (LPA)
            lpa_series = None
            if "Basic EPS" in fin.columns:
                lpa_series = fin["Basic EPS"]
            elif "Diluted EPS" in fin.columns:
                lpa_series = fin["Diluted EPS"]
                
            # Extract VPA (Equity / Shares)
            vpa_series = None
            if "Stockholders Equity" in bal.columns and "Ordinary Shares Number" in bal.columns:
                equity = bal["Stockholders Equity"]
                shares = bal["Ordinary Shares Number"]
                vpa_series = equity / shares
            
            if lpa_series is not None and vpa_series is not None:
                # Merge and ffill
                fund_df = pd.concat([lpa_series.rename("LPA"), vpa_series.rename("VPA")], axis=1)
                fund_df = fund_df.sort_index()
                
                # Reindex to dates.tz
                if fund_df.index.tz is None and dates.tz is not None:
                     fund_df.index = fund_df.index.tz_localize(dates.tz)
                elif fund_df.index.tz is not None and dates.tz is None:
                     fund_df.index = fund_df.index.tz_convert(None)
                elif fund_df.index.tz != dates.tz:
                     fund_df.index = fund_df.index.tz_convert(dates.tz)

                combined = fund_df.reindex(dates.union(fund_df.index)).sort_index().ffill()
                combined = combined.loc[dates]
                
                # Graham
                lpa_daily = combined['LPA']
                vpa_daily = combined['VPA']
                product = 22.5 * lpa_daily * vpa_daily
                graham_daily = np.sqrt(product.where(product > 0, 0))
                
                df_indicators['Preço Justo (Graham)'] = graham_daily
        
        # 3. Barsi: Dividends / 6%
        divs = stock.dividends
        if not divs.empty:
            if divs.index.tz is None and dates.tz is not None:
                divs.index = divs.index.tz_localize(dates.tz)
            elif divs.index.tz is not None and dates.tz is None:
                divs.index = divs.index.tz_convert(None)
            elif divs.index.tz != dates.tz:
                divs.index = divs.index.tz_convert(dates.tz)
                
            all_days = pd.date_range(start=dates.min() - pd.Timedelta(days=365), end=dates.max(), tz=dates.tz)
            div_daily = divs.reindex(all_days).fillna(0)
            rolling_divs = div_daily.rolling('365D').sum()
            rolling_divs_subset = rolling_divs.reindex(dates).ffill()
            
            df_indicators['Preço Teto (6%)'] = rolling_divs_subset / 0.06
            
        return df_indicators
        
    except Exception as e:
        return pd.DataFrame() # Fail silently/gracefully

# 1. Configuração Inicial
st.set_page_config(page_title="Dashboard Fundamentalista Pro", layout="wide")

@st.cache_data(ttl=600)
def get_market_data():
    try:
        df = fundamentus.get_resultado()
        df.columns = [c.strip().lower() for c in df.columns]
        return df
    except Exception as e:
        st.error(f"Erro ao acessar dados do mercado: {e}")
        return pd.DataFrame()

def extrair_tickers_planilha(df):
    todos_valores = df.astype(str).values.flatten()
    regex = re.compile(r'^[A-Z]{4}[0-9]{1,2}$')
    return list(set([v.strip().upper() for v in todos_valores if regex.match(v.strip().upper())]))

def load_portfolios():
    if not os.path.exists(PORTFOLIO_FILE):
        return {}
    try:
        with open(PORTFOLIO_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Erro ao carregar carteiras: {e}")
        return {}

def save_portfolio(name, tickers):
    portfolios = load_portfolios()
    portfolios[name] = tickers
    try:
        with open(PORTFOLIO_FILE, 'w') as f:
            json.dump(portfolios, f)
        st.success(f"Carteira '{name}' salva com sucesso!")
    except Exception as e:
        st.error(f"Erro ao salvar carteira: {e}")

def delete_portfolio(name):
    portfolios = load_portfolios()
    if name in portfolios:
        del portfolios[name]
        try:
            with open(PORTFOLIO_FILE, 'w') as f:
                json.dump(portfolios, f)
            st.success(f"Carteira '{name}' excluída com sucesso!")
            return True
        except Exception as e:
            st.error(f"Erro ao excluir carteira: {e}")
            return False
    return False

def calcular_valuation(row):
    cotacao = row.get('cotacao', 0)
    pl = row.get('pl', 0)
    pvp = row.get('pvp', 0)
    dy = row.get('dy', 0)

    lpa = cotacao / pl if pl != 0 else 0
    vpa = cotacao / pvp if pvp != 0 else 0

    if lpa > 0 and vpa > 0:
        preco_graham = np.sqrt(22.5 * vpa * lpa)
        margem_graham = ((preco_graham / cotacao) - 1) * 100 if cotacao > 0 else 0
    else:
        preco_graham = 0
        margem_graham = 0
    
    dividendos_estimados = dy * cotacao
    preco_teto_6 = dividendos_estimados / 0.06
    margem_barsi = ((preco_teto_6 / cotacao) - 1) * 100 if cotacao > 0 else 0
    
    return pd.Series([preco_graham, margem_graham, preco_teto_6, margem_barsi, lpa, vpa], 
                     index=['Preço Justo (Graham)', 'Margem Graham %', 'Preço Teto (6%)', 'Margem Barsi %', 'LPA', 'VPA'])

# 2. Dados
dados_mercado = get_market_data()

# 3. Sidebar
st.sidebar.header("📥 Entrada de Ativos")

# --- Portfolio Logic ---
st.sidebar.markdown("### 💾 Carteiras")
portfolios = load_portfolios()
selected_portfolio_name = st.sidebar.selectbox("Carregar Carteira:", [""] + list(portfolios.keys()))

todos_tickers_disponiveis = dados_mercado.index.tolist() if not dados_mercado.empty else []

if st.sidebar.button("Carregar"):
    if selected_portfolio_name and selected_portfolio_name in portfolios:
        loaded = portfolios[selected_portfolio_name]
        valid_loaded = [t for t in loaded if t in todos_tickers_disponiveis]
        st.session_state['selected_tickers'] = valid_loaded
        st.rerun()

if st.sidebar.button("Excluir Carteira"):
    if selected_portfolio_name and selected_portfolio_name in portfolios:
        if delete_portfolio(selected_portfolio_name):
            st.rerun()
    elif not selected_portfolio_name:
        st.sidebar.warning("Selecione uma carteira para excluir.")

if 'selected_tickers' not in st.session_state:
    st.session_state['selected_tickers'] = []

tickers_manuais = st.sidebar.multiselect(
    "1. Seleção Manual:", 
    options=todos_tickers_disponiveis,
    key='selected_tickers'
)

uploaded_file = st.sidebar.file_uploader("2. Carregar planilha CSV", type=["csv"])

ativos_da_planilha = []
if uploaded_file:
    # Método robusto: ler texto bruto e usar regex (ignora colunas/linhas quebradas)
    content = uploaded_file.read()
    text = ""
    try:
        text = content.decode('utf-8')
    except:
        try:
            text = content.decode('latin1')
        except:
            text = content.decode('utf-8', errors='ignore')
            
    # Procura por padrões de Ticker (ex: PETR4, VIVT3) no texto inteiro
    regex = re.compile(r'\b[A-Z]{4}[0-9]{1,2}\b')
    ativos_da_planilha = list(set(regex.findall(text.upper())))
    
    if not ativos_da_planilha:
        st.sidebar.warning("Nenhum código de ativo encontrado.")

lista_final_ativos = sorted(list(set(ativos_da_planilha + tickers_manuais)))

# Save Logic
st.sidebar.divider()
save_name = st.sidebar.text_input("Nome nova carteira:")
if st.sidebar.button("Salvar Carteira"):
    if not lista_final_ativos:
        st.sidebar.error("Selecione ativos antes de salvar.")
    elif save_name:
        save_portfolio(save_name, lista_final_ativos)
    else:
        st.sidebar.error("Digite um nome.")

# 4. Painel Principal
st.title("📊 Dashboard Fundamentalista")

indicadores_map = {
    'cotacao': 'Preço Atual',
    'Preço Justo (Graham)': 'Preço Justo (Graham)',
    'Margem Graham %': 'Margem Graham %',
    'Preço Teto (6%)': 'Preço Teto ',
    'Margem Barsi %': 'Margem Barsi %',
    'pl': 'P/L',
    'pvp': 'P/VP',
    'dy': 'Div. Yield',
    'roe': 'ROE',
    'liqcor': 'Liq. Corrente',
    'LPA': 'LPA',
    'VPA': 'VPA',
    'c5y': 'Cresc. últimos 5 anos'
}

if lista_final_ativos and not dados_mercado.empty:
    df_analise = dados_mercado[dados_mercado.index.isin(lista_final_ativos)].copy()
    df_valuation = df_analise.apply(calcular_valuation, axis=1)
    df_final = pd.concat([df_analise, df_valuation], axis=1)
    
    # Tabela Transposta (Indicadores na Esquerda, Ativos no Topo)
    st.subheader("📋 Comparativo de Ativos")
    
    colunas_finais = [c for c in indicadores_map.keys() if c in df_final.columns]
    df_tab = df_final[colunas_finais].rename(columns=indicadores_map).T

    # Função de cor para a tabela transposta
    def color_negative_red(val):
        if isinstance(val, (int, float)):
            color = 'green' if val > 0 else 'red'
            return f'color: {color}'
        return None

    # Exibição
    st.dataframe(
        df_tab.style.format(precision=2)
        .map(color_negative_red, subset=pd.IndexSlice[['Margem Graham %', 'Margem Barsi %'], :]),
        use_container_width=True
    )

    # Gráfico e Detalhes
    st.divider()
    col_graf, col_info = st.columns([2, 1])

    # 1. Select Asset (Define ativo_sel first)
    with col_graf:
        st.subheader("📈 Histórico")
        ativo_sel = st.selectbox("Selecione o ativo:", lista_final_ativos)

    # 2. Show Info & Select Indicator (Uses ativo_sel)
    with col_info:
        st.subheader("ℹ️ Info (Selecione para ver no gráfico)")
        selected_indicator_val = None
        selected_indicator_name = None
        
        if ativo_sel and ativo_sel in df_final.index:
            row = df_final.loc[ativo_sel]
            
            options = []
            values = {}
            for k, v in indicadores_map.items():
                if k in row:
                    val = row[k]
                    label = f"{v}: {val:.2f}" if isinstance(val, (float, int)) else f"{v}: {val}"
                    options.append(label)
                    values[label] = (v, val)
            
            # Use unique key per asset to reset selection or keep distinctive state
            selection = st.radio("Indicadores:", options, key=f"radio_{ativo_sel}")
            
            if selection:
                selected_indicator_name = values[selection][0]
                selected_indicator_val = values[selection][1]

# ... (rest of code)

    # 3. Show Chart (Uses ativo_sel and selected_indicator)
    with col_graf:
        if ativo_sel:
            h = yf.Ticker(f"{ativo_sel}.SA").history(period="5y") # Increased to 5y
            if not h.empty:
                df_chart = h[['Close']].copy()
                
                if selected_indicator_name and selected_indicator_val is not None:
                    
                    # Attempt to fetch historical data for plotting
                    hist_inds = get_historical_financials(ativo_sel)
                    
                    # Logic: 
                    # If we have historical data for the selected indicator, use it.
                    # Else, fallback to constant line.
                    
                    col_name = selected_indicator_name.split(':')[0].strip() # Remove value if present "Label: Value" -> "Label"
                    # Actually, selected_indicator_name coming from session state might just be the clean name "Preço Justo (Graham)"
                    # Let's verify what we stored. 
                    # value stored was: values[label] = (v, val) -> (friendly_name, numeric_value)
                    # So selected_indicator_name is "Preço Justo (Graham)"
                    
                    if not hist_inds.empty and selected_indicator_name in hist_inds.columns:
                        # Align indexes just in case
                        series_hist = hist_inds[selected_indicator_name]
                        # Join
                        df_chart = df_chart.join(series_hist, how='left')
                        # Fill NaNs with the current scalar value as fallback step (or just ffill)
                        df_chart[selected_indicator_name] = df_chart[selected_indicator_name].fillna(selected_indicator_val)
                    else:
                        # Fallback to constant
                        df_chart[selected_indicator_name] = selected_indicator_val
                
                st.line_chart(df_chart)

else:
    st.info("Aguardando ativos...")
