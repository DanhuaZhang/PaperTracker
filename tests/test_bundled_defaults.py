"""The checkout config and the packaged config must not drift apart.

A source checkout reads the repository-root ``config.toml``; an installed copy
reads ``papertracker/defaults.toml``. Nothing at runtime keeps the two in sync,
so a key added to one and not the other fails only for installed users, with a
bare ``Missing required setting``. This test is that missing guard.
"""

from papertracker import config


def test_repository_and_bundled_config_are_identical():
    repository = config.REPOSITORY_ROOT / "config.toml"
    bundled = config.BUNDLED_CONFIG_PATH
    assert repository.read_text(encoding="utf-8") == bundled.read_text(encoding="utf-8"), (
        f"{repository} and {bundled} have diverged. Edit one, then copy it over "
        "the other — a source checkout reads the first and an installed copy "
        "reads the second."
    )
