# n8n workflows

## Files

- `document-processing-pipeline.json` — webhook-triggered ingestion + extraction status pipeline. Posts the uploaded document to `/api/documents`, waits for the background extraction to settle, fetches the extracted controls and missing gaps, then sends a Slack-formatted summary. Branches to a failure-notification path when the upload step errors.

## Importing

1. Open n8n at http://localhost:5678 (admin / admin).
2. **Workflows** → **Import from File** → choose the JSON.
3. In the Webhook node, click "Test step" once to register the URL.
4. Set the env vars used by the HTTP Request nodes:
   - `BACKEND_BASE_URL` → `http://backend:8080` (default works inside the docker network)
   - `SLACK_WEBHOOK_URL` → your Slack incoming webhook (or `https://httpbin.org/post` for the demo)

## Triggering for the Loom demo

```bash
curl -X POST 'http://localhost:5678/webhook/ingest-regulatory-document' \
     -F 'data=@./backend/app/seed/data/soc2_excerpt.txt'
```

## Screenshots (TODO — candidate to add)

Place each canvas screenshot here:

- `screenshot-canvas.png` — full workflow canvas
- `screenshot-execution.png` — a successful execution log

The brief specifies the screenshots are graded artifacts.
