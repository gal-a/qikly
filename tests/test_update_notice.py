"""
What the update notice actually says.

The notice is the one line every user sees when a release lands, and it is the
only marketing surface that reaches somebody who has already installed. It had
two faults, both found by reading real output rather than the code:

  qikly 0.3.5 is available + v0.3.5 (you have 0.3.4)

The suffix is the GitHub release name, and `release.yml` titled every release
with the bare tag, so the line repeated the version it had already said.

Releases are now titled `v0.3.6: what changed in a phrase`, so the phrase is
worth quoting. These tests pin what happens to that phrase: the version prefix
comes off, a title that is only a version is dropped, and anything long is cut,
because this prints on every invocation and the title comes from a remote API
that can return whatever it likes.
"""
import pytest

from qikly import version_check as vc


@pytest.fixture
def notice(monkeypatch):
    """Drive check_for_update with a chosen latest version and release title."""
    def run(latest, title, installed="0.3.5"):
        monkeypatch.delenv(vc.NO_CHECK_ENV, raising=False)
        monkeypatch.setattr(vc, "__version__", installed)
        monkeypatch.setattr(vc, "_get_json",
                            lambda url: {"info": {"version": latest}})
        monkeypatch.setattr(vc, "_release_title", lambda: title)
        return vc.check_for_update()
    return run


def test_a_descriptive_title_is_quoted(notice):
    msg = notice("0.3.6", "v0.3.6: Marketplace listing and release automation")
    assert "Marketplace listing and release automation" in msg
    assert "0.3.6 is available" in msg
    assert "you have 0.3.5" in msg


def test_the_version_prefix_is_not_repeated(notice):
    """The sentence has already said the version; saying it twice is noise."""
    msg = notice("0.3.6", "v0.3.6: Marketplace listing and release automation")
    assert "v0.3.6:" not in msg
    assert msg.count("0.3.6") == 1


@pytest.mark.parametrize("title", ["v0.3.6", "0.3.6", "V0.3.6", "v0.3.6: ", ""])
def test_a_title_that_is_only_the_version_is_dropped(notice, title):
    """The regression. This produced 'is available + v0.3.6'."""
    msg = notice("0.3.6", title)
    assert " + " not in msg, msg


def test_no_title_at_all_still_produces_a_notice(notice):
    msg = notice("0.3.6", None)
    assert msg == "qikly 0.3.6 is available (you have 0.3.5)"


def test_a_long_title_is_cut_so_the_notice_stays_one_line(notice):
    msg = notice("0.3.6", "v0.3.6: " + "word " * 60)
    suffix = msg.split(" + ", 1)[1].split(" (you have")[0]
    assert len(suffix) <= vc.TITLE_MAX
    assert suffix.endswith("...")


def test_the_notice_is_ascii(notice):
    """
    It prints to a Windows console. A Unicode ellipsis here is exactly the kind
    of character that has already cost this project a debugging session.
    """
    msg = notice("0.3.6", "v0.3.6: " + "word " * 60)
    assert msg.isascii(), [c for c in msg if not c.isascii()]


def test_an_equal_or_older_release_says_nothing(notice):
    assert notice("0.3.5", "v0.3.5: something") is None
    assert notice("0.3.4", "v0.3.4: something") is None


def test_the_opt_out_wins_over_everything(notice, monkeypatch):
    monkeypatch.setenv(vc.NO_CHECK_ENV, "1")
    assert vc.check_for_update() is None
