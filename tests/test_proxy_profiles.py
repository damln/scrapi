import pytest

from app.proxy_profiles import ProxyProfileError, available_proxy_profiles, load_proxy_profiles, resolve_proxy_profile


def test_load_proxy_profiles_adds_named_profiles():
    env = {
        "PROXY_URL": "socks5://proxy.example:1080",
        "SCRAPI_PROXY_PROFILES_JSON": '{"residential_backup":"http://user:pass@example.com:8000"}',
    }

    profiles = load_proxy_profiles(env)

    assert profiles["current"] == "socks5://proxy.example:1080"
    assert profiles["direct"] == ""
    assert profiles["residential_backup"] == "http://user:pass@example.com:8000"
    assert available_proxy_profiles(env) == ["current", "direct", "residential_backup"]
    assert resolve_proxy_profile("residential_backup", env) == "http://user:pass@example.com:8000"


def test_proxy_profile_names_are_validated():
    env = {"SCRAPI_PROXY_PROFILES_JSON": '{"bad name":"http://example.com:8000"}'}

    with pytest.raises(ProxyProfileError, match="Invalid proxy profile name"):
        load_proxy_profiles(env)


def test_reserved_proxy_profile_names_are_rejected():
    env = {"SCRAPI_PROXY_PROFILES_JSON": '{"current":"http://example.com:8000"}'}

    with pytest.raises(ProxyProfileError, match="reserved"):
        load_proxy_profiles(env)
