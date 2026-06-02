from coworld.cli_support import observatory_web_url


def test_observatory_web_url_strips_api_prefix_for_default_server() -> None:
    assert observatory_web_url("https://softmax.com/api", "/observatory/foo") == "https://softmax.com/observatory/foo"


def test_observatory_web_url_preserves_custom_api_host() -> None:
    assert (
        observatory_web_url("https://staging.softmax.com/api", "/observatory/foo")
        == "https://staging.softmax.com/observatory/foo"
    )
    assert (
        observatory_web_url("http://localhost:3000/api", "/observatory/foo") == "http://localhost:3000/observatory/foo"
    )


def test_observatory_web_url_strips_legacy_api_observatory_prefix() -> None:
    assert (
        observatory_web_url("https://staging.softmax.com/api/observatory", "/observatory/foo")
        == "https://staging.softmax.com/observatory/foo"
    )


def test_observatory_web_url_passes_through_absolute_urls() -> None:
    absolute = "https://api.example.com/v2/coworlds/proxy/client/global"
    assert observatory_web_url("https://softmax.com/api", absolute) == absolute
