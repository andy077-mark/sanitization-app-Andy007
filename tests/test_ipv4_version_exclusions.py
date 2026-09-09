from sanitization_v2 import rules as rules_module
from sanitization_v2.sanitize import sanitize_content


def _ipv4_rule() -> str:
    patterns = rules_module.load_bad_patterns()
    return next(pattern for pattern in patterns if "ipv4" in pattern.lower())


def _sanitize(value: str):
    return sanitize_content(value, [_ipv4_rule()])


def test_real_ipv4_addresses_are_still_masked():
    sanitized, count, counts = _sanitize("src=10.20.30.40 dst=8.8.8.8")

    assert "10.20.30.40" not in sanitized
    assert "8.8.8.8" not in sanitized
    assert count == 2
    assert counts == {"IPv4 Address": 2}


def test_common_version_contexts_are_not_masked_as_ipv4():
    samples = [
        "version=1.2.3.4",
        "Version 7.4.2.1",
        "ver:10.2.3.4",
        "build=3.12.4.1",
        "release:2.5.6.7",
        "firmware=4.3.2.1",
        "fw:6.5.4.3",
        "v1.2.3.4",
    ]

    for sample in samples:
        sanitized, count, counts = _sanitize(sample)
        assert sanitized == sample
        assert count == 0
        assert counts == {}


def test_invalid_ipv4_like_values_are_not_masked():
    for sample in ("999.999.999.999", "256.1.1.1", "10.20.30.999"):
        sanitized, count, counts = _sanitize(sample)
        assert sanitized == sample
        assert count == 0
        assert counts == {}


def test_bare_dotted_quad_remains_masked_for_security():
    # Without context, 1.2.3.4 is both a valid IPv4 address and a possible
    # software version. The sanitizer intentionally treats the ambiguous bare
    # value as an IP so it does not create a data-leak exception.
    sanitized, count, counts = _sanitize("1.2.3.4")

    assert sanitized == "XXXXXXX"
    assert count == 1
    assert counts == {"IPv4 Address": 1}
