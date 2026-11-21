/**
 * Meld Pharm — Image Upload Worker
 *
 * Accepts image uploads (file or URL) from the admin product form,
 * saves them directly to R2, and returns the public URL.
 *
 * Environment variables (set in Cloudflare dashboard → Worker → Settings → Variables):
 *   UPLOAD_SECRET   — secret token the product form sends in Authorization header
 *   R2_PUBLIC_URL   — public base URL for your R2 bucket (e.g. https://images.barnatoremeldpharm.com)
 *
 * R2 binding (set in Cloudflare dashboard → Worker → Settings → Bindings):
 *   R2_BUCKET       — bound to your meldpharm-images bucket
 */

const ALLOWED_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/gif', 'image/avif'];
const MAX_SIZE_BYTES = 20 * 1024 * 1024; // 20 MB

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
  };
}

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders() },
  });
}

function generateKey(filename) {
  const ext = (filename.split('.').pop() || 'jpg').toLowerCase().replace(/[^a-z0-9]/g, '') || 'jpg';
  const ts = Date.now();
  const rand = Math.random().toString(36).slice(2, 10);
  return `products/${ts}-${rand}.${ext}`;
}

export default {
  async fetch(request, env) {
    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders() });
    }

    if (request.method !== 'POST') {
      return jsonResponse({ error: 'Method not allowed' }, 405);
    }

    // Auth check
    const auth = request.headers.get('Authorization') || '';
    if (!env.UPLOAD_SECRET || auth !== `Bearer ${env.UPLOAD_SECRET}`) {
      return jsonResponse({ error: 'Unauthorized' }, 401);
    }

    const contentType = request.headers.get('Content-Type') || '';

    // ── File upload (multipart/form-data) ────────────────────────────────────
    if (contentType.includes('multipart/form-data')) {
      let formData;
      try {
        formData = await request.formData();
      } catch {
        return jsonResponse({ error: 'Invalid form data' }, 400);
      }

      const file = formData.get('file');
      if (!file || typeof file === 'string') {
        return jsonResponse({ error: 'No file provided' }, 400);
      }

      if (file.size > MAX_SIZE_BYTES) {
        return jsonResponse({ error: 'File too large (max 20 MB)' }, 400);
      }

      const mimeType = file.type || 'image/jpeg';
      if (!ALLOWED_TYPES.includes(mimeType)) {
        return jsonResponse({ error: `Unsupported type: ${mimeType}` }, 400);
      }

      const key = generateKey(file.name || `image.${mimeType.split('/')[1]}`);
      await env.R2_BUCKET.put(key, file.stream(), {
        httpMetadata: { contentType: mimeType },
      });

      const publicUrl = `${(env.R2_PUBLIC_URL || '').replace(/\/$/, '')}/${key}`;
      return jsonResponse({ url: publicUrl, key });
    }

    // ── URL fetch (application/json) ─────────────────────────────────────────
    if (contentType.includes('application/json')) {
      let body;
      try {
        body = await request.json();
      } catch {
        return jsonResponse({ error: 'Invalid JSON' }, 400);
      }

      const imageUrl = (body.url || '').trim();
      if (!imageUrl) {
        return jsonResponse({ error: 'No URL provided' }, 400);
      }

      let fetchResp;
      try {
        fetchResp = await fetch(imageUrl, {
          headers: {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'image/*,*/*;q=0.8',
          },
          redirect: 'follow',
        });
      } catch (e) {
        return jsonResponse({ error: `Could not fetch URL: ${e.message}` }, 422);
      }

      if (!fetchResp.ok) {
        return jsonResponse({ error: `URL returned ${fetchResp.status}` }, 422);
      }

      const mimeType = (fetchResp.headers.get('Content-Type') || 'image/jpeg').split(';')[0].trim();
      if (!ALLOWED_TYPES.includes(mimeType)) {
        return jsonResponse({ error: `Unsupported image type: ${mimeType}` }, 422);
      }

      const buffer = await fetchResp.arrayBuffer();
      if (buffer.byteLength > MAX_SIZE_BYTES) {
        return jsonResponse({ error: 'Image too large (max 20 MB)' }, 422);
      }

      const ext = mimeType.split('/')[1] || 'jpg';
      const key = generateKey(`image.${ext}`);
      await env.R2_BUCKET.put(key, buffer, {
        httpMetadata: { contentType: mimeType },
      });

      const publicUrl = `${(env.R2_PUBLIC_URL || '').replace(/\/$/, '')}/${key}`;
      return jsonResponse({ url: publicUrl, key });
    }

    return jsonResponse({ error: 'Content-Type must be multipart/form-data or application/json' }, 400);
  },
};
