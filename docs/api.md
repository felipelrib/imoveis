# API Reference

The FastAPI backend exposes a REST API. Interactive docs are available at `/docs` when the server is running.

## Health Check

```
GET /health
```

Returns `{"status": "ok"}` when the API is running and connected to the database.

## Properties

### List Properties

```
GET /properties
```

Query parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `neighbourhood` | string | Filter by neighbourhood name |
| `city` | string | Filter by city name |
| `listing_type` | string | `rent` or `sale` |
| `min_price` | number | Minimum price filter |
| `max_price` | number | Maximum price filter |
| `min_area` | number | Minimum area (m²) |
| `max_area` | number | Maximum area (m²) |
| `platform` | string | Source platform filter |
| `bbox` | string | Bounding box: `minLon,minLat,maxLon,maxLat` |
| `limit` | int | Results per page (default 50) |
| `offset` | int | Pagination offset |

### Get Property

```
GET /properties/{id}
```

Returns full property details including listings, scores, and metadata.

### Price History

```
GET /properties/{id}/price-history
```

Returns ordered price history intervals with `start_ts`, `end_ts`, and `price`.

## Scraper Control

### Trigger Scrape

```
POST /scrape
```

Body:

```json
{
  "platform": "quintoandar",
  "search_url": "https://quintoandar.com.br/..."
}
```

### Get Platforms

```
GET /platforms
```

Returns list of available scraper platforms and their status.

## Admin Endpoints

### Worker Management

```
POST /admin/workers/pause    # Pause AI workers
POST /admin/workers/resume   # Resume AI workers
GET  /admin/workers/status   # Check worker status
```

### GPU Control

```
POST /admin/gpu/scale
```

Body:

```json
{
  "limit": 2
}
```

### AI Model Override

```
POST /admin/ai/model
```

Body:

```json
{
  "model": "llava",
  "backend": "ollama"
}
```

### Schedule Management

```
GET  /admin/schedule    # Get current scrape schedule
POST /admin/schedule    # Update scrape interval
```

## System

```
GET /system/pipeline     # Pipeline status and telemetry
GET /system/health       # Detailed health check
