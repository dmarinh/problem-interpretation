# To run the server: 
uvicorn app.main:app --reload


# On Linux:
curl http://localhost:8000/health/live

# On Windows:
# 1. PowerShell with real curl
curl.exe http://localhost:8000/health/live 
# 2. PowerShell  with Invoke-WebRequest:
Invoke-WebRequest -Uri http://localhost:8000/health/live
# 3. PowerShell with Invoke-WebRequest and Select-Object:
Invoke-WebRequest http://localhost:8000/health/live -UseBasicParsing |
Select-Object -ExpandProperty Content

