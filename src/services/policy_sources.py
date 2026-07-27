# Registry of live policy URLs to fetch and index.
# Each entry: id (used as blob cache key), platform, url, name.
# platform must be in policy_store._ALLOWED_PLATFORMS.

POLICY_SOURCES: list[dict] = [
    # YouTube / Google Ads — leaf pages
    {"id": "yt-prohibited-content", "platform": "youtube", "name": "YouTube Prohibited Content", "url": "https://support.google.com/adspolicy/answer/6023676"},
    {"id": "yt-prohibited-practices", "platform": "youtube", "name": "YouTube Prohibited Practices", "url": "https://support.google.com/adspolicy/answer/6020954"},
    {"id": "yt-restricted-content", "platform": "youtube", "name": "YouTube Restricted Content Overview", "url": "https://support.google.com/adspolicy/answer/6023698"},
    {"id": "yt-health-unapproved", "platform": "youtube", "name": "Healthcare: Unapproved Substances", "url": "https://support.google.com/adspolicy/answer/15595718"},
    {"id": "yt-misleading", "platform": "youtube", "name": "Misleading Representation", "url": "https://support.google.com/adspolicy/answer/6020955"},
    {"id": "yt-editorial", "platform": "youtube", "name": "Editorial and Technical Requirements", "url": "https://support.google.com/adspolicy/answer/6088505"},
    {"id": "yt-financial", "platform": "youtube", "name": "Financial Products and Services", "url": "https://support.google.com/adspolicy/answer/2464998"},
    {"id": "yt-adult-content", "platform": "youtube", "name": "Adult Content Policy", "url": "https://support.google.com/adspolicy/answer/6023989"},
    {"id": "yt-dangerous-products", "platform": "youtube", "name": "Dangerous Products or Services", "url": "https://support.google.com/adspolicy/answer/6023649"},
    {"id": "yt-trademark", "platform": "youtube", "name": "Trademark Policy", "url": "https://support.google.com/adspolicy/answer/6118256"},
    {"id": "yt-ad-format", "platform": "youtube", "name": "YouTube Ad Format Requirements", "url": "https://support.google.com/adspolicy/answer/10249050"},
    {"id": "yt-alcohol", "platform": "youtube", "name": "Alcohol Policy", "url": "https://support.google.com/adspolicy/answer/6023644"},
    {"id": "yt-copyright", "platform": "youtube", "name": "Copyright Policy", "url": "https://support.google.com/adspolicy/answer/6020956"},
    {"id": "yt-gambling", "platform": "youtube", "name": "Gambling Policy", "url": "https://support.google.com/adspolicy/answer/6023605"},
    {"id": "yt-political", "platform": "youtube", "name": "Political Content Policy", "url": "https://support.google.com/adspolicy/answer/6023676"},
    # FTC
    {"id": "ftc-endorsement", "platform": "generic", "name": "FTC Endorsement Guides", "url": "https://www.ftc.gov/business-guidance/resources/ftcs-endorsement-guides-what-people-are-asking"},
    {"id": "ftc-health-claims", "platform": "generic", "name": "FTC Health Claims Guidance", "url": "https://www.ftc.gov/business-guidance/resources/dietary-supplements-advertising-guide-industry"},
    {"id": "ftc-testimonials", "platform": "generic", "name": "FTC Testimonials and Before/After Results", "url": "https://www.ftc.gov/business-guidance/resources/ftcs-endorsement-guides-what-people-are-asking#typicalresults"},
    # Meta / Facebook
    {"id": "meta-ad-standards", "platform": "facebook", "name": "Meta Advertising Standards", "url": "https://transparency.meta.com/en-us/policies/ad-standards/"},
    {"id": "meta-prohibited", "platform": "facebook", "name": "Meta Prohibited Content", "url": "https://www.facebook.com/policies/ads/prohibited_content"},
    {"id": "meta-restricted", "platform": "facebook", "name": "Meta Restricted Content", "url": "https://www.facebook.com/policies/ads/restricted_content"},
    {"id": "meta-health", "platform": "facebook", "name": "Meta Health and Wellness Ads", "url": "https://www.facebook.com/business/help/2005074656298868"},
    {"id": "meta-financial", "platform": "facebook", "name": "Meta Financial Services Policy", "url": "https://www.facebook.com/business/help/438252513416690"},
    {"id": "meta-misleading", "platform": "facebook", "name": "Meta Misleading Claims Policy", "url": "https://www.facebook.com/policies/ads/prohibited_content/misinformation"},
    {"id": "meta-drugs", "platform": "facebook", "name": "Meta Drugs and Pharmaceuticals Policy", "url": "https://transparency.meta.com/en-us/policies/ad-standards/restricted-goods-services/drugs-pharmaceuticals/"},
    {"id": "meta-personal-attributes", "platform": "facebook", "name": "Meta Personal Attributes Policy", "url": "https://transparency.meta.com/policies/ad-standards/objectionable-content/personal-attributes"},
    # TikTok
    {"id": "tiktok-ad-policy", "platform": "tiktok", "name": "TikTok Advertising Policies", "url": "https://ads.tiktok.com/help/article/tiktok-advertising-policies-industry-entry"},
    {"id": "tiktok-prohibited", "platform": "tiktok", "name": "TikTok Prohibited Content", "url": "https://ads.tiktok.com/help/article/prohibited-content-general-policy-for-ad-content-targeting"},
    {"id": "tiktok-community", "platform": "tiktok", "name": "TikTok Community Guidelines", "url": "https://www.tiktok.com/community-guidelines/en/ads-and-branded-content"},
    {"id": "tiktok-health", "platform": "tiktok", "name": "TikTok Health Products Policy", "url": "https://ads.tiktok.com/help/article/health-and-wellness-products-and-services"},
    {"id": "tiktok-financial", "platform": "tiktok", "name": "TikTok Financial Services Policy", "url": "https://ads.tiktok.com/help/article/financial-services-industry-policy"},
    # X / Twitter
    {"id": "x-ad-policy", "platform": "x", "name": "X Advertising Policies", "url": "https://business.x.com/en/help/ads-policies/ads-content-policies.html"},
    {"id": "x-prohibited", "platform": "x", "name": "X Prohibited Content", "url": "https://business.x.com/en/help/ads-policies/prohibited-content-policies.html"},
    {"id": "x-restricted", "platform": "x", "name": "X Restricted Content", "url": "https://business.x.com/en/help/ads-policies/restricted-content-policies.html"},
    {"id": "x-health", "platform": "x", "name": "X Healthcare Advertising", "url": "https://business.x.com/en/help/ads-policies/ads-content-policies/healthcare-and-pharmaceutical-advertising.html"},
    {"id": "x-financial", "platform": "x", "name": "X Financial Services Policy", "url": "https://business.x.com/en/help/ads-policies/ads-content-policies/financial-services-advertising.html"},
]
