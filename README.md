# Querying LLM Service

FastAPI service that orchestrates prompt resolution and LLM text generation for insights summarization.

## Overview

The Querying LLM Service acts as an orchestrator between prompt configurations and LLM text generation. It receives insights data, fetches prompt configurations from the Prompt Service, renders templates, and calls the LLM Service to generate summaries.

## Technology Stack

- **Python**: 3.11
- **Framework**: FastAPI 0.115.12
- **Server**: Uvicorn 0.34.0
- **Validation**: Pydantic 2.11.1
- **HTTP Client**: httpx 0.28.1

## API Endpoints

### Health Check
```
GET /health
```

### Configuration
```
GET /api/v1/querying-llm/config/current-prompt-id
```

### Summary Generation
```
POST /api/v1/querying-llm/summary:generate
```

## Request/Response Examples

### Get Current Prompt ID
```bash
GET /api/v1/querying-llm/config/current-prompt-id
```

Response:
```json
{
  "promptId": "summary-v2.1",
  "version": "2.1.0",
  "lastUpdated": "2026-03-16T10:00:00Z"
}
```

### Generate Summary
```bash
POST /api/v1/querying-llm/summary:generate
```

Request:
```json
{
  "clubId": "WhiteHatSociety",
  "eventIds": ["WH27", "WH28"],
  "insights": [
    {
      "id": "insight-1",
      "body": {
        "whatHappened": "Great turnout for the security workshop",
        "whatWentWell": "Interactive demos were engaging",
        "whatCouldImprove": "Need more advanced topics"
      }
    }
  ]
}
```

Response:
```json
{
  "summaryText": "The security workshop had excellent attendance with engaging interactive demonstrations. Future sessions should include more advanced topics to meet participant expectations.",
  "modelName": "llama3.2",
  "temperature": 0.2,
  "clubId": "WhiteHatSociety",
  "eventIds": ["WH27", "WH28"],
  "insightCount": 1,
  "generatedAt": "2026-03-16T10:00:00Z"
}
```

## Environment Variables

### Service URLs
- `QUERYING_LLM_PROMPT_BASE_URL` - Prompt Service URL (default: `http://localhost:8091`)
- `QUERYING_LLM_LLM_BASE_URL` - LLM Service URL (default: `http://localhost:8093`)

### Configuration
- `QUERYING_LLM_DEFAULT_PROMPT_ID` - Default prompt ID (default: `summary-v2.1`)
- `QUERYING_LLM_PROMPT_VERSION` - Prompt version (default: `2.1.0`)
- `QUERYING_LLM_TIMEOUT_MS` - Request timeout in milliseconds (default: `15000`)

## Service Dependencies

### Prompt Service
- Fetches prompt configurations including templates and model parameters
- Endpoint: `GET /api/v1/prompts/{promptId}`

### LLM Service
- Generates text using configured models and prompts
- Endpoint: `POST /api/v1/llm/generate`

## Processing Flow

1. **Receive Request**: Accept clubId, eventIds, and insights array
2. **Canonicalize Event IDs**: Trim, deduplicate, and sort event IDs
3. **Fetch Prompt Config**: Get prompt template and model parameters from Prompt Service
4. **Handle Empty Insights**: Return default message if no insights provided
5. **Build User Prompt**: Render template with insights data and metadata
6. **Call LLM Service**: Generate text using configured model and parameters
7. **Return Response**: Format and return summary with metadata

## Prompt Template Rendering

The service builds a structured user prompt:

```
Club ID: {clubId}
Event IDs: {eventId1}, {eventId2}
Using only the supplied insights, produce a concise summary of the most important themes, issues, and actionable follow-ups. Do not invent facts. If evidence is mixed, say so.

Insights JSON:
{formatted_insights_json}
```

## Development

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Run Locally
```bash
# Set environment variables (optional, defaults provided)
export QUERYING_LLM_PROMPT_BASE_URL="http://localhost:8084"
export QUERYING_LLM_LLM_BASE_URL="http://localhost:8086"

# Start the service
uvicorn app.main:app --host 0.0.0.0 --port 8085 --reload
```

### Docker
```bash
# Build
docker build -t querying-llm-service .

# Run
docker run -p 8085:8085 \
  -e QUERYING_LLM_PROMPT_BASE_URL="http://prompt-service:8084" \
  -e QUERYING_LLM_LLM_BASE_URL="http://llm-service:8086" \
  querying-llm-service
```

## API Documentation

- **Swagger UI**: http://localhost:8085/docs
- **OpenAPI JSON**: http://localhost:8085/openapi.json

## Health Check

```bash
curl http://localhost:8085/health
```

Response:
```json
{
  "status": "ok",
  "service": "querying-llm"
}
```

## Error Handling

The service handles various error scenarios:
- **404**: Prompt not found in Prompt Service
- **400**: Invalid request (empty eventIds, validation errors)
- **502**: Downstream service errors (Prompt Service, LLM Service unavailable)
- **Timeout**: Configurable timeout for downstream calls

## Internal Configuration

The service uses internal prompt configuration rather than accepting promptId in requests:
- Prompt ID is determined by `QUERYING_LLM_DEFAULT_PROMPT_ID`
- This ensures consistent caching behavior in the manage-insights service
- The current prompt ID is exposed via the `/config/current-prompt-id` endpoint for cache fingerprinting