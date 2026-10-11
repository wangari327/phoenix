# Railway deployment

Railway builds with `Dockerfile.railway`. It intentionally excludes
`config.env`, so deployment secrets and local configuration are never baked
into the image.

## Service variables

Add these values in the Railway service's **Variables** tab and mark secrets as
sealed:

- `BOT_TOKEN`
- `TELEGRAM_API`
- `TELEGRAM_HASH`
- `OWNER_ID`
- `DATABASE_URL`
- `USER_SESSION_STRING` (when the user client is required)
- `BASE_URL=https://${{RAILWAY_PUBLIC_DOMAIN}}`

Railway provides `PORT`; Phoenix now uses it automatically for its web
selector. Generate a public domain under **Settings > Networking** before
redeploying so `RAILWAY_PUBLIC_DOMAIN` is populated.

## Persistence

Attach a Railway Volume at `/usr/src/app/downloads` if downloads must survive
a redeploy. Bot/user settings and RSS subscriptions remain durable only when
the same MongoDB database and bot token are used.

## Deploy

Create a Railway project from this GitHub repository. Railway reads
`railway.toml`, builds `Dockerfile.railway`, and checks `/` for a 2xx
response before marking the deployment healthy.
