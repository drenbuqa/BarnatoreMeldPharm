# Cloudflare Worker Deployment — Image Upload

This Worker handles image uploads directly from the browser to R2, bypassing Fly.io entirely.
This fixes the site crashes that happened when uploading product images.

## One-time setup

### 1. Install Wrangler (Cloudflare CLI)

```bash
npm install -g wrangler
```

### 2. Log in to Cloudflare

```bash
wrangler login
```

### 3. Deploy the Worker

```bash
cd cloudflare-worker
wrangler deploy
```

After deploying, Wrangler will print the Worker URL:
```
https://meldpharm-image-upload.<YOUR_SUBDOMAIN>.workers.dev
```

### 4. Set the environment variables in Cloudflare dashboard

Go to: **Cloudflare Dashboard → Workers & Pages → meldpharm-image-upload → Settings → Variables**

Add two **Secret** variables (click "Add variable" → type/encrypt):

| Variable name    | Value                                      |
|------------------|--------------------------------------------|
| `UPLOAD_SECRET`  | A long random string you invent (e.g. 40+ chars). Keep it private — it's the password the form uses to authenticate with the Worker. |
| `R2_PUBLIC_URL`  | The public URL of your R2 bucket, e.g. `https://pub-XXXX.r2.dev` or your custom domain |

### 5. Set the environment variables in Fly.io

Add the same values to your Fly.io app so the product form template gets them:

```bash
fly secrets set WORKER_UPLOAD_URL="https://meldpharm-image-upload.<YOUR_SUBDOMAIN>.workers.dev"
fly secrets set WORKER_UPLOAD_SECRET="<same value you put in UPLOAD_SECRET above>"
```

That's it. After this:
- Image uploads go directly from the browser to Cloudflare (bypassing Fly.io)
- Fly.io is never involved in image processing
- The site will not freeze during image uploads

## How to find your R2 public URL

1. Go to Cloudflare Dashboard → R2 → meldpharm-images
2. Click "Settings"
3. Under "Public access", enable it if not already on, and copy the URL

## Notes

- The Flask route `/admin/upload-image` still exists as a fallback. If `WORKER_UPLOAD_URL` is not set, uploads still go through Flask. Set the env vars to switch to the Worker.
- The Worker does NOT resize images (no Pillow). Images are stored as-is. If the image is already 1000×1000, it stays that way.
- The Worker supports files up to 20MB.
