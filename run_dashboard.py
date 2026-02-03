import uvicorn
import os
import sys

# Ensure the current directory is in sys.path so 'analise_acoes' module can be found
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    print("Launching Dashboard Fundamentalista...")
    print("Open http://localhost:8000 in your browser")
    
    # Run Uvicorn
    # We use "analise_acoes.web:app" string to enable reload support if needed,
    # but programmatically we can pass the app object if reload is False.
    # For reload=True, we must use the import string.
    # Run Uvicorn - loading as module 'web' since we added path
    uvicorn.run("web:app", host="0.0.0.0", port=8000, reload=True)
