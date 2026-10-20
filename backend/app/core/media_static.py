"""Static file serving for generated media (audio + timeline) with Range support."""

import os
from typing import Any

from starlette.responses import Response
from starlette.staticfiles import StaticFiles


class MediaStaticFiles(StaticFiles):
    """Starlette already answers Range requests (audio/video seeking); we only add caching.
    Files are regenerated under the same names, so API URLs carry a `?v=` version."""

    def file_response(
        self, full_path: Any, stat_result: os.stat_result, scope: Any, status_code: int = 200
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        # A cover version's files never change (a new version gets a new name).
        immutable = "/covers/" in str(full_path).replace(os.sep, "/")
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if immutable else "public, max-age=3600"
        )
        return response
