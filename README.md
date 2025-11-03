# pgadmit University & Scholarship Search Agent (MVP)

## Stack
- Flask (API)
- Supabase (DB) - **User profiles are READ-ONLY to agents**
- CrewAI + OpenAI (Agent runtime)
- TavilySearchTool (AI-powered university discovery)

## Setup
1. Create and activate venv (Windows):
```
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
```

2. Update `.env` (PORT=5000, SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY, TAVILY_API_KEY)

3. Apply database schema in Supabase (SQL editor):
- Open `database_schema.sql` and run it in your Supabase project.

## API Keys Required
- **OpenAI API Key**: For CrewAI agent reasoning and responses
- **Tavily API Key**: For AI-powered university search and discovery
  - Get free API key at: https://app.tavily.com/
  - Free tier includes 1000 searches/month

## Run API (dev)

### Local Development
```
.\.venv\Scripts\python -m flask --app app.main:create_app run --port 5000 --debug
```
or
```
.\.venv\Scripts\python -m app.main
```

### Docker
```
# Build the image
docker build -t pgadmit .

# Run
docker run -d -p 5000:5000 pgadmit

# Or Run with environment file
docker run -p 5000:5000 --env-file .env pgadmit

# Or run with individual environment variables
docker run -p 5000:5000 -e SUPABASE_URL=your_url -e SUPABASE_KEY=your_key -e OPENAI_API_KEY=your_key -e TAVILY_API_KEY=your_key pgadmit
```

## API Endpoints

### University Search Agent
- `POST /search_universities` — executes university search with CrewAI agents and stores results
- `GET /results/{user_profile_id}` — returns university recommendations for a user profile

### Scholarship Search Agent
- `POST /search_scholarships` — executes scholarship search and stores results
- `GET /results/scholarships/{user_profile_id}` — returns scholarship recommendations

### Application Requirements Agent
- `POST /fetch_application_requirements` — fetches and stores application requirements for specific university/program
- `GET /application_requirements/{university}/{program}` — retrieves saved application requirements

### Visa Information Agent
- `POST /visa_info` — triggers visa information retrieval for citizenship → destination pair
- `GET /visa_info/{citizenship}/{destination}` — returns cached visa data
- `GET /visa_report/{citizenship}/{destination}` — generates visa checklist/report
- `GET /visa_alerts` — gets pending visa policy change alerts
- `POST /visa_alerts/mark_sent` — marks visa alerts as sent

### Admissions Counselor Agent
- `GET /admissions/summary/{user_id}` — returns overall admissions status, progress score, current stage, and stress flags
- `GET /admissions/next_steps/{user_id}` — returns prioritized next actions for the student
- `POST /admissions/update_stage` — updates user's admissions progress stage
- `POST /admissions/log_agent_report` — for agents to log reports and track conflicts

## Testing Flow

### 1. Activate Environment and Start Server
```cmd
.\.venv\Scripts\activate
python -m app.main
```

### 2. Test University Search (replace user_profile_id as needed)
```cmd
curl -X POST http://localhost:5000/search_universities -H "Content-Type: application/json" -d "{\"user_profile_id\": 1}"

curl -X POST http://localhost:5000/search_universities -H "Content-Type: application/json" -d "{\"user_profile_id\": 1, \"search_request\": \"Find universities that match my profile\"}"
```

### 3. Test Scholarship Search
```cmd
curl -X POST http://localhost:5000/search_scholarships -H "Content-Type: application/json" -d "{\"user_profile_id\": 1}"
```

### 4. Test Visa search agent (NEW)
```cmd
curl -X POST http://localhost:5000/visa_info `
  -H "Content-Type: application/json" `
  -d "{\"user_profile_id\": 1, \"citizenship\": \"Pakistani\", \"destination\": \"Germany\"}"
```

### 5. Test Application Requirements Fetch
```cmd
curl -X POST "https://pgadmit-232251258466.europe-west1.run.app/fetch_application_requirements" -H "Content-Type: application/json" -d "{\"user_profile_id\": 4, \"university\": \"USC\", \"program\": \"Computer Science B.S.\"}"
```

### 6. Get Saved Application Requirements
```cmd
curl -X GET "https://pgadmit-232251258466.europe-west1.run.app/application_requirements/USC/Computer%20Science%20B.S.?user_profile_id=1" -H "Content-Type: application/json"
```

### 7. Retrieve University Results
```cmd
curl -X GET http://localhost:5000/results/1
```

### 8. Retrieve Scholarship Results
```cmd
curl -X GET http://localhost:5000/results/scholarships/1
```

# Admissions Counselor Endpoints
---

## Endpoint 1: GET `/admissions/summary/{user_id}`

### Test Command:
```bash
curl -X GET "http://localhost:5000/admissions/summary/1"
```
---

## Endpoint 2: GET `/admissions/next_steps/{user_id}`

### Test Command:
```bash
curl -X GET "http://localhost:5000/admissions/next_steps/1"
```
---

## Endpoint 3: POST `/admissions/update_stage`

### Test Command:
```bash
curl -X POST "http://localhost:5000/admissions/update_stage" -H "Content-Type: application/json" -d "{\"user_id\": 1, \"current_stage\": \"Application Preparation\", \"progress_score\": 85.5, \"stress_flags\": {\"approaching_deadlines\": 3}}"
```
---

## Endpoint 4: POST `/admissions/log_agent_report`

### Test Command:
```bash
curl -X POST "http://localhost:5000/admissions/log_agent_report" -H "Content-Type: application/json" -d "{\"agent_name\": \"University Search Agent\", \"user_id\": 1, \"payload\": {\"status\": \"completed\"}}"
```
---

### Alternative: Docker Testing Flow
```cmd
# Build and run 
docker build -t pgadmit .

# Run
docker run -d -p 5000:5000 pgadmit

# Or Run with environment variables
docker run -p 5000:5000 -e SUPABASE_URL=your_url -e SUPABASE_KEY=your_key -e OPENAI_API_KEY=your_key -e TAVILY_API_KEY=your_key pgadmit

# Then test with same curl commands above
curl -X POST http://localhost:5000/search_universities -H "Content-Type: application/json" -d "{\"user_profile_id\": 1, \"search_request\": \"Find universities that match my profile\"}"
curl -X GET http://localhost:5000/results/1
```

**Note**: Replace `1` with any valid user profile ID from your database. The search will use the agent system to find universities matching that user's profile and preferences.
