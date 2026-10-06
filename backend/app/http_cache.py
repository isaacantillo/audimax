from fastapi import Request


async def cache_headers(request: Request, call_next):
    """Vite names built files by content hash: cache those forever. index.html names the current
    hashes, so it must always be revalidated, or a deploy leaves browsers on a deleted bundle."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/assets/") and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif not path.startswith("/api/") and response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache"
    return response
