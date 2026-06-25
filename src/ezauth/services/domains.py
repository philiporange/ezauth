import aiodns
from loguru import logger


async def verify_cname(domain: str, expected_target: str) -> bool:
    """Verify that a CNAME record points to the expected target.

    Checks for a direct CNAME match first. If no CNAME is found (e.g. when
    behind a CDN like Cloudflare that flattens CNAMEs), falls back to comparing
    A-record IPs between the domain and the expected target.
    """
    resolver = aiodns.DNSResolver()

    # 1. Direct CNAME check
    try:
        result = await resolver.query(domain, "CNAME")
        for record in result:
            canonical = record.cname.rstrip(".")
            if canonical == expected_target.rstrip("."):
                logger.info(f"CNAME verified: {domain} -> {canonical}")
                return True
        logger.warning(f"CNAME mismatch for {domain}: got {[r.cname for r in result]}")
        return False
    except aiodns.error.DNSError:
        pass

    # 2. Fallback: compare A records (handles CNAME flattening / CDN proxying)
    try:
        domain_a = await resolver.query(domain, "A")
        target_a = await resolver.query(expected_target, "A")
        domain_ips = {r.host for r in domain_a}
        target_ips = {r.host for r in target_a}
        if domain_ips and domain_ips & target_ips:
            logger.info(f"A-record verified: {domain} shares IPs with {expected_target}")
            return True
        logger.warning(
            f"A-record mismatch for {domain}: {domain_ips} vs {expected_target}: {target_ips}"
        )
    except aiodns.error.DNSError as e:
        logger.warning(f"DNS lookup failed for {domain}: {e}")

    return False
