"""Config behaviour, pinned against the TypeScript it replaces.

JQ-303 swapped the language, not the contract: every default and every
validation rule below is the one `api/src/config.ts` had. A developer moving
between the JoinQuest reference games should find the same knobs behaving the
same way, so these read as a specification rather than as characterisation.
"""

import pytest

from app.config import DEFAULT_API_PORT, DEFAULT_CORS_ORIGINS, Config


class TestApiPort:
    def test_defaults_when_unset(self) -> None:
        assert Config.from_env({}).api_port == DEFAULT_API_PORT

    def test_reads_the_environment(self) -> None:
        assert Config.from_env({"API_PORT": "9999"}).api_port == 9999

    @pytest.mark.parametrize("raw", ["0", "65536", "-1", "not-a-port", "3002.5", ""])
    def test_rejects_anything_that_is_not_a_port(self, raw: str) -> None:
        # An unparseable port must fail loudly at startup. Falling back to the
        # default would bind a port the Lobby's launch URLs do not point at,
        # and the game would look merely unreachable.
        if raw == "":
            # Empty is "unset" rather than invalid, matching the TypeScript.
            assert Config.from_env({"API_PORT": raw}).api_port == DEFAULT_API_PORT
            return
        with pytest.raises(ValueError, match="API_PORT"):
            Config.from_env({"API_PORT": raw})


class TestCorsOrigins:
    def test_defaults_cover_the_lobby_and_this_game(self) -> None:
        assert Config.from_env({}).cors_allowed_origins == DEFAULT_CORS_ORIGINS

    def test_splits_trims_and_drops_blanks(self) -> None:
        config = Config.from_env({"CORS_ALLOWED_ORIGINS": " https://a.test , ,https://b.test "})
        assert config.cors_allowed_origins == ("https://a.test", "https://b.test")

    def test_falls_back_when_the_value_is_only_separators(self) -> None:
        # " , , " parses to zero origins. Zero allowed origins blocks every
        # browser request, so the defaults are safer than honouring it.
        assert Config.from_env({"CORS_ALLOWED_ORIGINS": " , , "}).cors_allowed_origins == DEFAULT_CORS_ORIGINS


class TestDatabaseUrl:
    def test_assembles_from_the_postgres_parts(self) -> None:
        config = Config.from_env({})
        assert config.database_url == "postgres://goforth:goforth_dev_password@localhost:5434/go_forth"

    def test_honours_the_parts(self) -> None:
        config = Config.from_env(
            {
                "POSTGRES_USER": "u",
                "POSTGRES_PASSWORD": "p",
                "POSTGRES_HOST": "db",
                "POSTGRES_PORT": "6000",
                "POSTGRES_DB": "d",
            }
        )
        assert config.database_url == "postgres://u:p@db:6000/d"

    def test_an_explicit_dsn_wins(self) -> None:
        # Kubernetes mounts one secret key, not five — so the whole DSN given
        # directly must take precedence over the assembled parts.
        config = Config.from_env({"DATABASE_URL": "postgres://real/dsn", "POSTGRES_USER": "ignored"})
        assert config.database_url == "postgres://real/dsn"

    def test_a_blank_dsn_is_not_a_dsn(self) -> None:
        assert Config.from_env({"DATABASE_URL": "   "}).database_url.endswith("/go_forth")

    def test_credentials_are_percent_encoded(self) -> None:
        # A password with a '@' or '/' in it would otherwise silently produce a
        # DSN pointing at the wrong host.
        config = Config.from_env({"POSTGRES_PASSWORD": "p@ss/word"})
        assert "p%40ss%2Fword" in config.database_url
        assert config.database_url.endswith("@localhost:5434/go_forth")
