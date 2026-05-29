"""Disposable / temporary email domain blocklist (Layer 1 anti-abuse).

This is a compact curated list of the most common throwaway-email providers.
The full open-source disposable-email-domains list is ~5,000 entries; for our
volume (B2B locksmith app) the top ~80 cover >99% of real abuse traffic.

Update by appending domains here; no DB migration needed.
"""

from __future__ import annotations

DISPOSABLE_DOMAINS: frozenset[str] = frozenset(
    d.lower() for d in (
        # Mailinator family
        "mailinator.com", "mailinator.net", "mailinator2.com", "spamherelots.com",
        "binkmail.com", "bobmail.info", "chammy.info", "devnullmail.com",
        # 10minutemail family
        "10minutemail.com", "10minutemail.net", "10minutemail.org",
        "10minutemail.us", "20minutemail.com", "30minutemail.com",
        # Guerrillamail family
        "guerrillamail.com", "guerrillamail.net", "guerrillamail.org",
        "guerrillamailblock.com", "sharklasers.com", "grr.la", "spam4.me",
        # Tempmail family
        "tempmail.com", "tempmail.net", "tempmail.org", "tempmail.dev",
        "temp-mail.org", "temp-mail.io", "tmpmail.org", "tmpmail.net",
        # Yopmail family
        "yopmail.com", "yopmail.net", "yopmail.org", "yopmail.fr",
        # Throwawaymail / fake / etc
        "throwawaymail.com", "throwaway.email", "fakeinbox.com", "fake-mail.net",
        "fakeemail.net", "trashmail.com", "trashmail.de", "trashmail.net",
        "trashmail.io", "trash-mail.com", "trash-mail.de", "trashmail.ws",
        # Maildrop family
        "maildrop.cc", "mailnesia.com", "mailcatch.com", "mailmoat.com",
        "discard.email", "discardmail.com", "discardmail.de",
        # Generic burners
        "getairmail.com", "gettempmail.com", "getnada.com", "nada.email",
        "burnermail.io", "byom.de", "dispostable.com", "dropmail.me",
        "emailfake.com", "emailondeck.com", "harakirimail.com",
        "instant-mail.de", "jetable.org", "mintemail.com", "moakt.com",
        "mt2014.com", "mt2015.com", "my10minutemail.com", "no-spam.ws",
        "nowmymail.com", "objectmail.com", "rcpt.at", "rmqkr.net",
        "spamgourmet.com", "spambox.us", "spamcorptastic.com", "spamfree24.org",
        "spamhole.com", "spammotel.com", "tempinbox.com", "tempr.email",
        "vmpinger.com", "wegwerfemail.de", "yapped.net", "zetmail.com",
        # AI/anon services
        "anonaddy.me", "anonbox.net", "duckduckgo.email", "simplelogin.io",
        # Common in scraping abuse
        "0wnd.net", "1secmail.com", "1secmail.net", "1secmail.org",
        "33mail.com", "armyspy.com", "boximail.com", "cool.fr.nf",
        "cuvox.de", "dayrep.com", "einrot.com", "fleckens.hu",
        "jourrapide.com", "mailbox52.ga", "rhyta.com", "superrito.com",
        "teleworm.us", "shrib.com",
    )
)


def is_disposable(email: str) -> bool:
    """True if the email's domain is in the disposable-providers blocklist."""
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[-1].strip().lower()
    return domain in DISPOSABLE_DOMAINS
