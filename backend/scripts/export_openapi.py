"""Write the OpenAPI schema to backend/openapi.json for the frontend client generator."""

import json
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("FASTAPI_ENV", "development")  # dist/ may not exist yet

from app.main import app  # noqa: E402

out = Path(__file__).parent.parent / "openapi.json"
out.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
print(f"wrote {out}")
