import pandas as pd
import tempfile
import os

# Define writable directory for cache and data
TEMP_DIR = tempfile.gettempdir()

import requests_cache
cache_path = os.path.join(TEMP_DIR, 'http_cache')
requests_cache.install_cache(cache_path, expire_after=3600)
import fundamentus
import yfinance as yf
import re
import numpy as np
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_PORTFOLIO_FILE = os.path.join(BASE_DIR, 'portfolios.json')
import tempfile
TEMP_PORTFOLIO_FILE = os.path.join(tempfile.gettempdir(), 'portfolios.json')

# Determine writable file
ACTIVE_PORTFOLIO_FILE = LOCAL_PORTFOLIO_FILE
try:
    # On Vercel, the app directory is read-only. 
    # Try to check if we can write to the local file.
    if os.path.exists(LOCAL_PORTFOLIO_FILE):
        with open(LOCAL_PORTFOLIO_FILE, 'a'):
            pass
    else:
        # If it doesn't exist, try creating it. This will fail on Vercel.
        with open(LOCAL_PORTFOLIO_FILE, 'w') as f:
            f.write("{}")
except (OSError, IOError, PermissionError):
    # Fallback to temp if readonly
    ACTIVE_PORTFOLIO_FILE = TEMP_PORTFOLIO_FILE
    # If temp file doesn't exist, try to seed it from local if it exists
    if not os.path.exists(TEMP_PORTFOLIO_FILE) and os.path.exists(LOCAL_PORTFOLIO_FILE):
        try:
            import shutil
            shutil.copy2(LOCAL_PORTFOLIO_FILE, TEMP_PORTFOLIO_FILE)
        except Exception:
            pass

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
        print(f"Error fetching historical financials for {ticker_symbol}: {e}")
        return pd.DataFrame()

def fetch_yf_data(tickers):
    """
    Fetches market data for a list of tickers using yfinance.
    Returns a DataFrame compatible with the fundamentus structure.
    """
    data = []
    for t in tickers:
        try:
            ticker_sa = f"{t}.SA"
            obj = yf.Ticker(ticker_sa)
            info = obj.info
            
            # Map YF fields to our schema
            # We need: cotacao, pl, pvp, dy, roe, ev_ebitda, lpa, vpa
            price = info.get('currentPrice', 0)
            
            # Basic valuation
            pl = info.get('trailingPE', 0)
            pvp = info.get('priceToBook', 0)
            dy_raw = info.get('dividendYield', 0)
            dy = dy_raw / 100 if dy_raw and dy_raw > 1 else dy_raw # Normalize if > 1 (likely %)
            
            roe = info.get('returnOnEquity', 0)
            
            # For Graham
            eps = info.get('trailingEps', 0)
            bv = info.get('bookValue', 0)
            
            # Normalize to match fundamentus scale if needed (dy is 0.12 for 12% in YF usually)
            # Fundamentus often returns percentages as decimals too, but let's verify usage.
            # In calcular_valuation: dividendos_estimados = dy * cotacao. 
            # If YF dy is 0.08 (8%), then 0.08 * 100 = 8. Correct.
            
            record = {
                'papel': t,
                'cotacao': price,
                'pl': pl if pl else 0,
                'pvp': pvp if pvp else 0,
                'dy': dy if dy else 0,
                'return_on_equity': roe if roe else 0,
                'lpa': eps if eps else 0,
                'vpa': bv if bv else 0,
                # FIIs usually don't rely on these, set 0
                'ev_ebitda': 0, 
                'cresc_rec_5a': 0, # Growth
            }
            data.append(record)
        except Exception as e:
            print(f"Error fetching YF data for {t}: {e}")
            
    if not data:
        return pd.DataFrame()
        
    df = pd.DataFrame(data)
    df = df.set_index('papel')
    return df

def get_market_data(tickers_filter=None):
    try:
        # 1. Fetch from Fundamentus (Stocks)
        df = fundamentus.get_resultado()
        df.columns = [c.strip().lower() for c in df.columns]
        
        rename_map = {
            'evebitda': 'ev_ebitda',
            'roe': 'return_on_equity'
        }
        df = df.rename(columns=rename_map)

        # Force float conversion for numeric columns
        cols_to_float = ['cotacao', 'pl', 'pvp', 'dy', 'lpa', 'vpa', 'ev_ebitda', 'return_on_equity']
        for col in cols_to_float:
            if col in df.columns:
                # If column is object type (strings), replace ',' with '.'
                if df[col].dtype == object:
                   df[col] = df[col].astype(str).str.replace(',', '.')
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        if not tickers_filter:
            return df
            
        # 2. Check for missing tickers (Potential FIIs)
        # tickers_filter should be list of strings
        requested = set([t.upper() for t in tickers_filter])
        available = set(df.index.str.upper())
        
        missing = list(requested - available)
        
        if missing:
            print(f"Fetching missing tickers from YF: {missing}")
            df_yf = fetch_yf_data(missing)
            if not df_yf.empty:
                # Align columns - ensuring minimal schema matches
                df = pd.concat([df, df_yf], axis=0)
                # Fill NaNs created by concatenation
                df = df.fillna(0)
        
        # 3. Update 'cotacao' from YF for the requested tickers to get the last close/current price
        if tickers_filter:
            for t in tickers_filter:
                try:
                    t_upper = t.upper()
                    if t_upper in df.index:
                        ticker_sa = f"{t_upper}.SA"
                        obj = yf.Ticker(ticker_sa)
                        price = obj.info.get('currentPrice') or obj.info.get('regularMarketPrice')
                        if price:
                            df.at[t_upper, 'cotacao'] = float(price)
                except Exception:
                    pass
                
        return df

    except Exception as e:
        print(f"Erro ao acessar dados do mercado: {e}")
        return pd.DataFrame()

def extrair_tickers_texto(texto):
    """
    Extracts tickers (e.g. PETR4, VALE3) from raw text using regex.
    """
    regex = re.compile(r'\b[A-Z]{4}[0-9]{1,2}\b')
    return list(set([t.upper() for t in regex.findall(texto)]))

def extrair_tickers_planilha(df):
    todos_valores = df.astype(str).values.flatten()
    regex = re.compile(r'^[A-Z]{4}[0-9]{1,2}$')
    return list(set([v.strip().upper() for v in todos_valores if regex.match(v.strip().upper())]))

def load_portfolios():
    # Strategy: using ACTIVE_PORTFOLIO_FILE logic
    # If using TEMP (Vercel), try loading it. If empty/missing, fallback to LOCAL (read-only seed).
    
    if ACTIVE_PORTFOLIO_FILE == TEMP_PORTFOLIO_FILE:
        if os.path.exists(TEMP_PORTFOLIO_FILE):
            try:
                with open(TEMP_PORTFOLIO_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                pass 
        
        # Fallback to local (read-only)
        if os.path.exists(LOCAL_PORTFOLIO_FILE):
            try:
                with open(LOCAL_PORTFOLIO_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Erro ao carregar carteira base (read-only): {e}")
                pass
        return {}
    
    else:
        # Normal local behavior
        if not os.path.exists(ACTIVE_PORTFOLIO_FILE):
            return {}
        try:
            with open(ACTIVE_PORTFOLIO_FILE, 'r') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"Erro ao carregar carteiras: {e}")
            return {}

def save_portfolio(name, tickers):
    portfolios = load_portfolios()
    portfolios[name] = tickers
    try:
        with open(ACTIVE_PORTFOLIO_FILE, 'w') as f:
            json.dump(portfolios, f)
        return True, f"Carteira '{name}' salva com sucesso!"
    except Exception as e:
        return False, f"Erro ao salvar carteira: {e}"

def delete_portfolio(name):
    portfolios = load_portfolios()
    if name in portfolios:
        del portfolios[name]
        try:
            with open(ACTIVE_PORTFOLIO_FILE, 'w') as f:
                json.dump(portfolios, f)
            return True, f"Carteira '{name}' excluída com sucesso!"
        except Exception as e:
            return False, f"Erro ao excluir carteira: {e}"
    return False, "Carteira não encontrada."

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
