from ipaddress import ip_address, ip_network

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import API_TOKEN

security = HTTPBearer(auto_error=False)

LOCAL_HOSTNAMES = frozenset({"localhost", "host.docker.internal"})
DOCKER_IPV4_NETWORK = ip_network("172.16.0.0/12")


def _is_local_request(request: Request) -> bool:
    """Trust direct loopback and Docker-bridge calls to a local destination."""
    if request.client is None:
        return False

    try:
        client_address = ip_address(request.client.host)
        destination = request.url.hostname
    except ValueError:
        return False

    if destination is None:
        return False

    destination = destination.rstrip(".").lower()
    try:
        destination_address = ip_address(destination)
    except ValueError:
        destination_is_local = destination in LOCAL_HOSTNAMES
    else:
        destination_is_local = destination_address.is_loopback or destination_address in DOCKER_IPV4_NETWORK

    client_is_local = client_address.is_loopback or client_address in DOCKER_IPV4_NETWORK
    return client_is_local and destination_is_local


def verify_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    if _is_local_request(request):
        return ""
    if not API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server misconfigured: SCRAPI_API_TOKEN is not set",
        )
    if credentials is None or credentials.credentials != API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token",
        )
    return credentials.credentials
