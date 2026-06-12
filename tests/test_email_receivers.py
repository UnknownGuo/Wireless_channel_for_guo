from omegaconf import OmegaConf

from zotero_arxiv_daily.utils import get_email_receivers


def test_get_email_receivers_supports_legacy_single_receiver():
    config = OmegaConf.create({"email": {"receiver": "one@example.com"}})

    assert get_email_receivers(config) == ["one@example.com"]


def test_get_email_receivers_supports_receiver_list():
    config = OmegaConf.create({"email": {"receivers": ["one@example.com", "two@example.com"]}})

    assert get_email_receivers(config) == ["one@example.com", "two@example.com"]


def test_get_email_receivers_supports_comma_separated_string():
    config = OmegaConf.create({"email": {"receivers": "one@example.com, two@example.com"}})

    assert get_email_receivers(config) == ["one@example.com", "two@example.com"]
