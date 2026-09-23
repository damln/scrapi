from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.auth import verify_token
from app.image_jobs import MAX_BODY, ImageGenerationRequest, ImageJob, prepare_payload


class ImageRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def bounded_handler(request: Request) -> Response:
            if request.method == "POST":
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_BODY:
                        raise HTTPException(413, "Request exceeds 30 MiB")
                    body.extend(chunk)
                request._body = bytes(body)
            try:
                return await handler(request)
            except RequestValidationError as exc:
                # Pydantic errors can otherwise echo cookies or entire base64 images.
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": [
                            {"loc": error["loc"], "type": error["type"], "msg": "Invalid value"}
                            for error in exc.errors()
                        ]
                    },
                )

        return bounded_handler


router = APIRouter(prefix="/api/v1/images", route_class=ImageRoute, dependencies=[Depends(verify_token)])


@router.post("/generations", status_code=202, response_model=ImageJob, response_model_exclude_none=True)
async def generate(payload: ImageGenerationRequest, request: Request):
    prepared = await prepare_payload(payload)
    job = request.app.state.image_jobs.submit(prepared)
    return JSONResponse(
        status_code=202,
        content=job.model_dump(exclude_none=True),
        headers={
            "Location": job.poll_url,
            "Retry-After": "3",
            "Cache-Control": "no-store",
        },
    )


@router.get("/jobs/{job_id}", response_model=ImageJob, response_model_exclude_none=True)
async def poll(job_id: str, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return request.app.state.image_jobs.get(job_id)


@router.delete("/jobs/{job_id}", status_code=204)
async def delete(job_id: str, request: Request):
    request.app.state.image_jobs.delete(job_id)
