"""
`server.json`, the MCP Registry listing.

The registry is what VS Code's own gallery reads, so this file is a public
claim about qikly that a machine validates and a stranger installs from. Three
things can rot without anyone noticing, and each is checked here rather than
at publish time, when the fix costs a release.

**It carries a version.** The listing points at a PyPI version, so a listing
naming a version nobody published is worse than no listing at all. The version
lives in three files now, and a missed bump should fail the suite rather than
the registry.

**It carries an ownership marker.** The registry proves the publisher owns the
PyPI package by finding `mcp-name: <name>` in the README that PyPI serves. If
the marker and the name in this file ever disagree, publishing is refused.

**Its install block has to carry the `[mcp]` extra.** A bare `uvx qikly`
would install without it and produce exactly the server-that-will-not-start
this project spent two releases fixing, and the console script is named
`qikly-mcp` while the package is named `qikly`. Both are expressed in the
arguments: `--from qikly[mcp]==<version>` as a runtime argument, and
`qikly-mcp` as a positional. Verified with uv 0.12.13, and the same shape a
live registry entry already uses. The version therefore appears three times
in this one file, which is what most of the checks below are about.
"""
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name):
    with io.open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _server_json():
    return json.loads(_load("server.json"))


def test_it_is_valid_json_with_the_three_required_fields():
    doc = _server_json()
    for field in ("name", "description", "version"):
        assert doc.get(field), field


def test_the_name_is_the_github_namespace_we_can_prove_we_own():
    assert _server_json()["name"] == "io.github.gal-a/qikly"


def test_the_description_fits_the_registry_limit():
    """100 characters, enforced by the registry at publish time."""
    assert len(_server_json()["description"]) <= 100


def test_the_readme_carries_the_ownership_marker_for_this_exact_name():
    """
    PyPI serves the README as the package description, and the registry looks
    for this line in it. A rename on one side alone means a refused publish.
    """
    assert ("mcp-name: " + _server_json()["name"]) in _load("README.md")


def test_the_listed_version_is_the_version_being_released():
    doc = _server_json()
    assert ('version = "%s"' % doc["version"]) in _load("pyproject.toml")
    assert ('__version__ = "%s"' % doc["version"]) in _load("src/qikly/__init__.py")


def test_the_install_block_carries_the_extra_and_the_script_name():
    """
    Two things a bare `uvx qikly` gets wrong: no `[mcp]`, and the wrong
    command name. Both are fixed in the arguments rather than by publishing a
    second package.
    """
    pkg = _server_json()["packages"][0]
    assert pkg["identifier"] == "qikly"
    assert pkg["registryType"] == "pypi"
    assert pkg["transport"]["type"] == "stdio"
    assert pkg["runtimeHint"] == "uvx"
    args = pkg["runtimeArguments"]
    assert [a for a in args if a.get("name") == "--from"], (
        "without --from the extra is lost and the server cannot start")
    # Both the extra and the script name live in runtimeArguments, and the
    # positional comes last, so a client composing them in order produces
    # `uvx --from qikly[mcp]==X qikly-mcp`. Putting the script name in
    # packageArguments instead composes to `uvx --from ... qikly qikly-mcp`,
    # which fails with "unrecognized arguments: qikly-mcp". This is the shape
    # the live ai.gateco/gateco listing uses, checked 2026-09-12.
    assert args[-1] == {"type": "positional", "value": "qikly-mcp"}
    assert "packageArguments" not in pkg


def test_the_version_agrees_everywhere_it_appears_in_the_listing():
    """
    Three places in one file: the server version, the package version, and
    the pin inside --from. A release-day bump that misses one publishes a
    listing that installs a different version than it advertises.
    """
    doc = _server_json()
    pkg = doc["packages"][0]
    assert pkg["version"] == doc["version"]
    pin = [a["value"] for a in pkg["runtimeArguments"] if a.get("name") == "--from"][0]
    assert pin == "qikly[mcp]==%s" % doc["version"]


def test_the_project_root_can_be_set_from_the_listing():
    """
    The other half of the install problem: a host starts the server in the
    folder the editor has open, which is often not the project.
    """
    env = _server_json()["packages"][0]["environmentVariables"]
    assert [e["name"] for e in env] == ["QIKLY_PROJECT_ROOT"]
    assert env[0]["isRequired"] is False


# ------------------------------------------------------------------ icons ---

def _icons():
    return _server_json().get("icons") or []


def test_every_icon_is_served_from_our_own_domain_over_https():
    """
    The schema requires HTTPS and tells clients to prefer icons from a domain
    they can trust. These are the landing page's own files.
    """
    assert _icons(), "the listing should carry an icon"
    for icon in _icons():
        assert icon["src"].startswith("https://test.qikly.com/images/"), icon["src"]


def test_every_icon_url_points_at_a_file_that_exists_in_docs():
    """
    The URLs are GitHub Pages serving docs/, so a missing file here is a
    broken image in the registry listing, visible to everyone and to nobody
    who could fix it quickly.
    """
    for icon in _icons():
        name = icon["src"].rsplit("/", 1)[-1]
        assert os.path.isfile(os.path.join(ROOT, "docs", "images", name)), name


def test_a_png_is_offered_because_clients_only_have_to_support_png():
    """
    The schema: clients MUST support image/png and image/jpeg, and only
    SHOULD support image/svg+xml. An SVG-only listing may render as nothing.
    """
    assert any(i["mimeType"] == "image/png" for i in _icons())


def test_each_theme_has_both_formats():
    pairs = {(i["mimeType"], i.get("theme")) for i in _icons()}
    for theme in ("dark", "light"):
        assert ("image/png", theme) in pairs
        assert ("image/svg+xml", theme) in pairs


def test_the_published_icons_have_not_drifted_from_the_packaged_ones():
    """
    The same mark ships twice: inside the wheel for MCP hosts, and under
    docs/ for the registry. Two copies of an image drift silently, so they
    are compared rather than trusted.
    """
    for name in ("qikly_icon.svg", "qikly_icon_light.svg"):
        packaged = os.path.join(ROOT, "src", "qikly", "assets", name)
        published = os.path.join(ROOT, "docs", "images", name)
        with open(packaged, "rb") as a, open(published, "rb") as b:
            assert a.read() == b.read(), name


def test_the_pngs_are_really_pngs():
    """They are rendered from the SVGs, and a failed render leaves a file."""
    for name in ("qikly_icon.png", "qikly_icon_light.png"):
        with open(os.path.join(ROOT, "docs", "images", name), "rb") as handle:
            assert handle.read(4)[1:4] == b"PNG", name
