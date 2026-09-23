"""Submit a Scrapi image job, poll it and save its images. Standard library only."""

import argparse
import base64
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

INPUT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
OUTPUT_TYPES = {value: key for key, value in INPUT_TYPES.items()} | {"image/gif": ".gif"}


class ImageClient:
    def __init__(self, base_url, token):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(self, path, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        if body and len(body) > 30 * 1024 * 1024:
            raise ValueError("Combined JSON exceeds 30 MiB")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(self.base_url + path, data=body, headers=headers)
        try:
            with urlopen(request, timeout=60) as response:
                return json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}: {exc.read(1000).decode(errors='replace')}") from None
        except (URLError, TimeoutError):
            raise RuntimeError("Connection failed. A submitted job may still run. Check before resubmitting.") from None

    @staticmethod
    def load_images(folder):
        if folder is None:
            return []
        if not folder.is_dir():
            raise ValueError(f"Not a folder: {folder}")
        files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in INPUT_TYPES)
        if len(files) > 4:
            raise ValueError("At most 4 reference images")
        images = []
        for path in files:
            if path.stat().st_size > 10 * 1024 * 1024:
                raise ValueError(f"Image exceeds 10 MiB: {path.name}")
            images.append(
                {
                    "mime_type": INPUT_TYPES[path.suffix.lower()],
                    "b64_json": base64.b64encode(path.read_bytes()).decode(),
                }
            )
        return images

    def poll(self, job_id):
        deadline, previous = time.monotonic() + 45 * 60, None
        while time.monotonic() < deadline:
            job = self.request(f"/api/v1/images/jobs/{quote(job_id, safe='')}")
            status = job["status"]
            if status != previous:
                print(f"Status: {status}", flush=True)
                previous = status
            if status == "completed":
                return job["result"]
            if status == "failed":
                raise RuntimeError(f"Generation failed: {job.get('error', 'unknown')}")
            time.sleep(3)
        raise RuntimeError(f"Polling timed out. Resume with --job {job_id}")

    @classmethod
    def main(cls):
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("prompt", nargs="?")
        parser.add_argument("--base-url", default=os.getenv("SCRAPI_BASE_URL", "http://localhost:10700"))
        parser.add_argument(
            "--session", type=Path, help="Cookie export/storage-state JSON, omitted if configured server-side"
        )
        parser.add_argument("--images", type=Path, help="Reference image folder, can be empty")
        parser.add_argument("--output", type=Path, default=Path("generated"))
        parser.add_argument("--proxy-profile", default="current")
        parser.add_argument("--job", help="Resume polling without submitting a prompt")
        args = parser.parse_args()
        client = cls(args.base_url, os.getenv("SCRAPI_API_TOKEN", ""))
        if args.job:
            job_id = args.job
        else:
            if not args.prompt or not args.prompt.strip():
                parser.error("Provide a prompt or --job")
            payload = {
                "prompt": args.prompt,
                "images": cls.load_images(args.images),
                "proxy_profile": args.proxy_profile,
            }
            if args.session:
                payload["session"] = json.loads(args.session.read_text())
            job = client.request("/api/v1/images/generations", payload)
            job_id = job["id"]
        print(f"Job ID: {job_id}", flush=True)
        print(f"Resume with --job {job_id}", flush=True)
        result = client.poll(job_id)
        images = result.get("images", [])
        if not images:
            print(result.get("text", "No images returned"))
            return
        args.output.mkdir(parents=True, exist_ok=True)
        for index, image in enumerate(images, 1):
            extension = OUTPUT_TYPES[image["mime_type"]]
            path = args.output / f"{Path(job_id).name}-{index}{extension}"
            path.write_bytes(base64.b64decode(image["b64_json"], validate=True))
            print(path.resolve())


if __name__ == "__main__":
    try:
        ImageClient.main()
    except KeyboardInterrupt:
        raise SystemExit("Polling stopped. Submitted jobs continue on the server.") from None
    except (RuntimeError, ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from None
