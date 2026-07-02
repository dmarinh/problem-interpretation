# To run the server: 
uvicorn app.main:app --reload

# EN swager
http://localhost:8000/docs

POST the query to
http://127.0.0.1:8000/api/v1/translate

En body: 
{
  "query": "Raw chicken left out for 3 hours at room temperature"
}

# CURL
curl -X POST "http://127.0.0.1:8000/api/v1/translate?verbose=false" ^
  -H "accept: application/json" ^
  -H "Content-Type: application/json" ^
  -d "{\"query\":\"What's the worst-case pathogen growth on raw chicken left at 25 °C for 4 hours\"}"


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

