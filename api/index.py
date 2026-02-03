from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import sys
import os
import io

# Ensure parent directory (project root) is in path so we can import 'core'
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)

import pandas as pd
import yfinance as yf
import numpy as np
import core

app = FastAPI(title="Dashboard Fundamentalista")

class PortfolioData(BaseModel):
    name: str
    tickers: List[str]

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        content = await file.read()
        
        if file.filename.endswith('.csv'):
            # Try common encodings and automatic separator detection
            try:
                # First try UTF-8 with automatic separator detection
                df = pd.read_csv(io.BytesIO(content), sep=None, engine='python', encoding='utf-8')
            except Exception:
                # Fallback to Latin-1 if UTF-8 fails (common in Brazilian Excel exports)
                df = pd.read_csv(io.BytesIO(content), sep=None, engine='python', encoding='latin-1')
        elif file.filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(io.BytesIO(content))
        else:
            raise HTTPException(status_code=400, detail="Formato inválido. Use .csv ou .xlsx")
            
        tickers = core.extrair_tickers_planilha(df)
        return {"tickers": tickers}
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        # Return the error message to help the user identify the issue
        msg = f"Erro ao processar {file.filename}: {str(e)}"
        raise HTTPException(status_code=500, detail=msg)

@app.get("/api/portfolios")
def get_portfolios():
    return core.load_portfolios()

@app.post("/api/portfolios")
def save_portfolio(data: PortfolioData):
    success, msg = core.save_portfolio(data.name, data.tickers)
    if not success:
        raise HTTPException(status_code=500, detail=msg)
    return {"message": msg}

@app.delete("/api/portfolios/{name}")
def delete_portfolio(name: str):
    success, msg = core.delete_portfolio(name)
    if not success:
        raise HTTPException(status_code=404, detail=msg)
    return {"message": msg}

@app.get("/api/tickers")
def get_analysis(tickers: Optional[str] = Query(None)):
    """
    Returns market analysis. 
    If 'tickers' param provided (comma separated), filters results.
    """
    target_tickers = []
    if tickers:
        raw_tickers = tickers.split(',')
        target_tickers = [t.strip().upper() for t in raw_tickers if t.strip()]

    df = core.get_market_data(target_tickers if target_tickers else None)
    if df.empty:
        return []

    if not target_tickers:
         # If no filter, return all (but maybe too large? valid for now)
         pass 

    df_analise = df.copy()
    if target_tickers:
        df_analise = df[df.index.isin(target_tickers)].copy()
    if df_analise.empty:
        return []

    # Calculate Valuation
    df_valuation = df_analise.apply(core.calcular_valuation, axis=1)
    df_final = pd.concat([df_analise, df_valuation], axis=1)

    # Format for JSON
    df_final = df_final.reset_index().rename(columns={'papel': 'ticker'})
    df_final = df_final.replace([np.inf, -np.inf], 0).fillna(0)
    
    return df_final.to_dict(orient='records')

@app.get("/api/history/{ticker}")
def get_history(ticker: str, indicator: Optional[str] = None, indicator_value: Optional[float] = 0.0):
    """
    Returns chart data: 5y stock price + optional indicator line.
    """
    try:
        stock = yf.Ticker(f"{ticker}.SA")
        hist = stock.history(period="5y")
        
        if hist.empty:
            raise HTTPException(status_code=404, detail="No history found")
        
        # Base chart data
        close_prices = hist['Close']
        dates = hist.index.strftime('%Y-%m-%d').tolist()
        prices = close_prices.tolist()
        
        response = {
            "dates": dates,
            "prices": prices,
            "indicator_series": []
        }

        if indicator and indicator != "Preço Atual":
            hist_inds = core.get_historical_financials(ticker)
            
            series_data = []
            if not hist_inds.empty and indicator in hist_inds.columns:
                aligned = hist_inds[indicator].reindex(hist.index).ffill()
                aligned = aligned.fillna(indicator_value)
                series_data = aligned.tolist()
            else:
                series_data = [indicator_value] * len(dates)
            
            series_data = [0 if (pd.isna(x) or np.isinf(x)) else x for x in series_data]

            response["indicator_series"] = series_data
            response["indicator_name"] = indicator

        return response
        
    except Exception as e:
        print(f"Error in history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Mount static files. 
# On Vercel, it's better to point to the correct static path relative to the root.
static_path = os.path.join(ROOT_DIR, "static")
if os.path.exists(static_path):
    app.mount("/", StaticFiles(directory=static_path, html=True), name="static")
