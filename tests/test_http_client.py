"""The HTTP layer: cache, retries, rate limiting and robots.txt.

Everything here runs against a fake session, so no test touches the network.
"""

import pytest
import requests

from goya_scraper.http_client import (
    HttpClient,
    HttpError,
    RobotsDisallowed,
    cache_filename,
)


class FakeResponse:
    def __init__(self, status=200, text="", encoding="utf-8"):
        self.status_code = status
        self.text = text
        self.encoding = encoding
        self.apparent_encoding = "utf-8"


class FakeSession:
    """A requests.Session stand-in that replays a scripted list of outcomes."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.headers = {}
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append({"url": url, "timeout": timeout})
        outcome = self.outcomes.pop(0) if self.outcomes else FakeResponse(200, "<html/>")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_client(outcomes, tmp_path, **kwargs):
    kwargs.setdefault("min_interval", 0)        # no sleeping in tests
    kwargs.setdefault("retry_delays", (0, 0, 0))
    kwargs.setdefault("respect_robots", False)   # tested on its own
    kwargs.setdefault("cache_dir", tmp_path / "cache")
    session = FakeSession(outcomes)
    client = HttpClient(session=session, **kwargs)
    return client, session


class TestCacheFilename:
    def test_simple_path(self):
        assert cache_filename("/36-edicion/nominaciones/") == "36-edicion_nominaciones.html"

    def test_movie_path(self):
        assert cache_filename("/pelicula/el-buen-patron/") == "pelicula_el-buen-patron.html"

    def test_real_urls_never_collide(self):
        """The two URL shapes this site actually uses must not clash."""
        paths = [
            "/1-edicion/nominaciones/", "/2-edicion/nominaciones/",
            "/pelicula/amor/", "/pelicula/bella/", "/pelicula/blue_malone/",
        ]
        assert len({cache_filename(p) for p in paths}) == len(paths)

    def test_cannot_escape_the_cache_directory(self, tmp_path):
        cache_dir = tmp_path / "cache"
        for path in ["/../../etc/passwd", "/pelicula/../../x", "//..//..//y"]:
            name = cache_filename(path)
            assert "/" not in name
            assert "\\" not in name
            # The important property: the file lands directly in the cache dir.
            assert (cache_dir / name).resolve().parent == cache_dir.resolve()


class TestCache:
    def test_second_call_makes_no_request(self, tmp_path):
        client, session = make_client([FakeResponse(200, "<html>primero</html>")], tmp_path)
        first = client.get("/36-edicion/nominaciones/")
        second = client.get("/36-edicion/nominaciones/")
        assert first == second == "<html>primero</html>"
        assert len(session.calls) == 1

    def test_cache_file_is_written(self, tmp_path):
        client, _ = make_client([FakeResponse(200, "<html>x</html>")], tmp_path)
        client.get("/pelicula/abc/")
        written = tmp_path / "cache" / "pelicula_abc.html"
        assert written.exists()
        assert written.read_text(encoding="utf-8") == "<html>x</html>"

    def test_cache_is_kept_across_client_instances(self, tmp_path):
        """This is the whole point: a new run must reuse the old downloads."""
        first, session = make_client([FakeResponse(200, "<html>x</html>")], tmp_path)
        first.get("/pelicula/abc/")

        second, session2 = make_client([], tmp_path)
        assert second.get("/pelicula/abc/") == "<html>x</html>"
        assert session2.calls == []

    def test_cache_can_be_disabled(self, tmp_path):
        client, session = make_client(
            [FakeResponse(200, "a"), FakeResponse(200, "b")], tmp_path, cache_dir=None
        )
        client.get("/x/")
        client.get("/x/")
        assert len(session.calls) == 2

    def test_utf8_content_survives_the_round_trip(self, tmp_path):
        client, _ = make_client([FakeResponse(200, "<p>El buen patrón</p>")], tmp_path)
        client.get("/x/")
        assert "El buen patrón" in client.get("/x/")


class TestRetries:
    def test_server_error_is_retried_then_succeeds(self, tmp_path):
        outcomes = [
            FakeResponse(503),
            FakeResponse(500),
            FakeResponse(200, "<html>al final</html>"),
        ]
        client, session = make_client(outcomes, tmp_path)
        assert client.get("/x/") == "<html>al final</html>"
        assert len(session.calls) == 3

    def test_network_error_is_retried(self, tmp_path):
        outcomes = [
            requests.ConnectionError("reset"),
            FakeResponse(200, "<html>ok</html>"),
        ]
        client, _ = make_client(outcomes, tmp_path)
        assert client.get("/x/") == "<html>ok</html>"

    def test_gives_up_after_the_configured_retries(self, tmp_path):
        client, session = make_client([FakeResponse(500)] * 5, tmp_path, retries=3)
        with pytest.raises(HttpError) as info:
            client.get("/x/")
        assert info.value.status == 500
        assert len(session.calls) == 3

    def test_delay_grows_between_retries(self, tmp_path, monkeypatch):
        slept = []
        monkeypatch.setattr("time.sleep", lambda s: slept.append(s))
        client, _ = make_client(
            [FakeResponse(500)] * 5, tmp_path, retries=3, retry_delays=(2, 4, 8)
        )
        with pytest.raises(HttpError):
            client.get("/x/")
        assert slept == [2, 4]   # no wait after the last attempt


class TestNoRetry:
    """404 means it is not there. 403 and 429 mean we are not welcome."""

    @pytest.mark.parametrize("status", [404, 403, 429, 401])
    def test_not_retried(self, tmp_path, status):
        client, session = make_client([FakeResponse(status)] * 4, tmp_path)
        with pytest.raises(HttpError) as info:
            client.get("/x/")
        assert info.value.status == status
        assert len(session.calls) == 1

    def test_a_404_is_not_cached(self, tmp_path):
        client, _ = make_client([FakeResponse(404)], tmp_path)
        with pytest.raises(HttpError):
            client.get("/x/")
        assert not (tmp_path / "cache" / "x.html").exists()


class TestPoliteness:
    def test_identifiable_user_agent(self, tmp_path):
        client, session = make_client([FakeResponse(200, "x")], tmp_path)
        client.get("/x/")
        assert session.headers["User-Agent"].startswith("goya-scraper/")

    def test_timeout_is_always_passed(self, tmp_path):
        client, session = make_client([FakeResponse(200, "x")], tmp_path)
        client.get("/x/")
        assert session.calls[0]["timeout"] == (10, 30)

    def rate_limited_client(self, tmp_path, monkeypatch, outcomes, min_interval=1.2):
        """A client whose clock only moves when something sleeps."""
        slept = []
        clock = {"now": 1000.0}

        def fake_sleep(seconds):
            slept.append(seconds)
            clock["now"] += seconds

        monkeypatch.setattr("time.sleep", fake_sleep)
        monkeypatch.setattr("time.monotonic", lambda: clock["now"])
        return make_client(outcomes, tmp_path, min_interval=min_interval) + (slept, clock)

    def test_rate_limit_spaces_requests(self, tmp_path, monkeypatch):
        client, _, slept, _ = self.rate_limited_client(
            tmp_path, monkeypatch, [FakeResponse(200, "a"), FakeResponse(200, "b")]
        )
        client.get("/a/")
        client.get("/b/")
        assert sum(slept) == pytest.approx(1.2)

    def test_a_timeout_still_costs_us_the_pause(self, tmp_path, monkeypatch):
        """A read timeout means 30 seconds went by. The retry has to wait too,
        otherwise a struggling server gets hammered from our retries."""
        client, _, slept, _ = self.rate_limited_client(
            tmp_path,
            monkeypatch,
            [requests.ReadTimeout("too slow"), FakeResponse(200, "ok")],
        )
        assert client.get("/x/") == "ok"
        # The retry delay (0 in tests) plus the rate-limit pause.
        assert sum(slept) == pytest.approx(1.2)

    def test_cache_hits_do_not_sleep(self, tmp_path, monkeypatch):
        """Serving from disk does not touch the server, so there is nothing to
        be polite about. Sleeping here would make a cached rerun take 35 minutes
        for no reason."""
        monkeypatch.setattr("time.sleep", lambda s: pytest.fail("should not sleep"))
        client, _ = make_client([FakeResponse(200, "x")], tmp_path, min_interval=60)
        client.get("/x/")
        client.get("/x/")


class TestRobots:
    def robots_client(self, tmp_path, robots=None, pages=1, **kwargs):
        outcomes = [robots if robots is not None else FakeResponse(404)]
        outcomes += [FakeResponse(200, f"<html>página {i}</html>") for i in range(pages)]
        return make_client(outcomes, tmp_path, respect_robots=True, **kwargs)

    def test_missing_robots_means_no_restrictions(self, tmp_path):
        client, _ = self.robots_client(tmp_path)
        assert client.get("/x/") == "<html>página 0</html>"

    def test_disallowed_url_is_not_requested(self, tmp_path):
        rules = "User-agent: *\nDisallow: /"
        client, session = self.robots_client(tmp_path, FakeResponse(200, rules))
        with pytest.raises(RobotsDisallowed):
            client.get("/pelicula/secreto/")
        assert not any("secreto" in c["url"] for c in session.calls)

    def test_allowed_url_is_requested(self, tmp_path):
        rules = "User-agent: *\nDisallow: /privado"
        client, _ = self.robots_client(tmp_path, FakeResponse(200, rules))
        assert client.get("/pelicula/abc/") == "<html>página 0</html>"

    def test_robots_is_read_only_once(self, tmp_path):
        rules = "User-agent: *\nDisallow: /privado"
        client, session = self.robots_client(tmp_path, FakeResponse(200, rules), pages=3)
        client.get("/a/")
        client.get("/b/")
        client.get("/c/")
        assert sum(1 for c in session.calls if c["url"].endswith("robots.txt")) == 1

    def test_robots_allows_everything_when_disabled(self, tmp_path):
        # With respect_robots=False the robots body is never read, so the first
        # scripted response is the page itself.
        client, _ = make_client(
            [FakeResponse(200, "<html>x</html>")], tmp_path, respect_robots=False
        )
        assert client.get("/lo-que-sea/") == "<html>x</html>"

    def test_unreachable_robots_does_not_block_the_run(self, tmp_path):
        # We should not stop scraping because we could not read robots.txt.
        outcomes = [requests.ConnectionError("down"), FakeResponse(200, "<html>x</html>")]
        client, _ = make_client(outcomes, tmp_path, respect_robots=True)
        assert client.get("/x/") == "<html>x</html>"

    def test_error_status_robots_does_not_block_the_run(self, tmp_path):
        outcomes = [FakeResponse(503, "nope"), FakeResponse(200, "<html>x</html>")]
        client, _ = make_client(outcomes, tmp_path, respect_robots=True)
        assert client.get("/x/") == "<html>x</html>"