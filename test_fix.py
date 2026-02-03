
import sys
import os
import json

# Ensure path to core.py
sys.path.append(os.path.abspath('/home/kali/Antigravity/analise_fundamentalista/Analise_fundamentalista'))

import core

print(f"Initial Active File: {core.ACTIVE_PORTFOLIO_FILE}")

# 1. Test Local Save
print("\n--- Testing Local Save ---")
if core.ACTIVE_PORTFOLIO_FILE != core.LOCAL_PORTFOLIO_FILE:
    print("Warning: Not using local file (maybe running in constrained env?)")

test_name = "test_local_pf"
core.save_portfolio(test_name, ["PETR4"])
# Check persistence
pats = core.load_portfolios()
if test_name in pats:
    print("✅ Local Save success")
else:
    print("❌ Local Save failed")

# Cleanup local
if test_name in pats:
    core.delete_portfolio(test_name)

# 2. Test Vercel Mode (Mocking)
print("\n--- Testing Vercel Mode (Simulated) ---")
# Force switch
core.ACTIVE_PORTFOLIO_FILE = core.TEMP_PORTFOLIO_FILE
print(f"Switched to: {core.ACTIVE_PORTFOLIO_FILE}")

# Ensure clean state in temp
if os.path.exists(core.TEMP_PORTFOLIO_FILE):
    os.remove(core.TEMP_PORTFOLIO_FILE)

# Should load default/local data first
pats = core.load_portfolios()
# Assuming local has some data?
print(f"Initial Load from Temp (should fallback to Local): {list(pats.keys())}")

# Save new
core.save_portfolio("vercel_test", ["VALE3"])
pats2 = core.load_portfolios()
if "vercel_test" in pats2:
    print("✅ Vercel Save success")
else:
    print("❌ Vercel Save failed")

# Verify fallback still exists?
# If we saved to temp, we dump the WHOLE loaded dict. So "vercel_test" + "defaults" should be there.
# If "meus ativos" was in local return, it should be in saved temp.
if "meus ativos" in pats and "meus ativos" in pats2:
     print("✅ Fallback data preserved in new Save")
else:
    print("❌ Fallback data lost on Save")
    
# Cleanup
if os.path.exists(core.TEMP_PORTFOLIO_FILE):
    os.remove(core.TEMP_PORTFOLIO_FILE)
