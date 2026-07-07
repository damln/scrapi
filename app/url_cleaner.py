from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "utm_id",
    "utm_source_platform",
    "utm_creative_format",
    "utm_marketing_tactic",
    "fbclid",
    "fb_action_ids",
    "fb_action_types",
    "fb_source",
    "fb_ref",
    "fbadid",
    "fbadsetid",
    "fbcampaignid",
    "gclid",
    "gclsrc",
    "_ga",
    "_gl",
    "gbraid",
    "wbraid",
    "twclid",
    "tw_source",
    "tw_medium",
    "tw_campaign",
    "msclkid",
    "msclid",
    "mc_cid",
    "mc_eid",
    "mkt_tok",
    "ref",
    "referrer",
    "source",
    "campaign",
    "medium",
    "s_cid",
    "elqTrackId",
    "elqTrack",
    "assetType",
    "assetId",
    "campaignid",
    "adgroupid",
    "feeditemid",
    "trackingId",
    "trackingCode",
    "li_fat_id",
    "li_medium",
    "li_source",
    "igshid",
    "igsh",
    "tt_medium",
    "tt_content",
    "share",
    "fbclickid",
    "zanpid",
    "kwd",
}

TRACKING_PARAMS_LOWER = {p.lower() for p in TRACKING_PARAMS}


def clean_url(raw_url: str) -> str:
    """Remove tracking params and sort remaining params alphabetically."""
    parsed = urlparse(raw_url)
    params = parse_qs(parsed.query, keep_blank_values=True)

    filtered = {key: values for key, values in params.items() if key.lower() not in TRACKING_PARAMS_LOWER}

    sorted_query = urlencode(filtered, doseq=True) if filtered else ""

    cleaned = urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            sorted_query,
            parsed.fragment,
        )
    )

    return cleaned
