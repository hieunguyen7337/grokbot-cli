import threading

import httpx

from groken import auth


def test_concurrent_refresh_reuses_rotated_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "TOKEN_FILE", tmp_path / "tokens.json")
    auth.save_tokens({"accessToken": "old-access", "refreshToken": "old"})
    calls = []

    def post(*args, **kwargs):
        calls.append(1)
        return httpx.Response(
            200, json={"access_token": "new-access", "refresh_token": "new"}
        )

    monkeypatch.setattr(auth.httpx, "post", post)
    barrier = threading.Barrier(2)
    results = []

    def worker():
        barrier.wait()
        results.append(auth.refresh_tokens("old"))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(calls) == 1
    assert all(result and result["refreshToken"] == "new" for result in results)


def test_failed_refresh_reloads_rotated_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "TOKEN_FILE", tmp_path / "tokens.json")
    auth.save_tokens({"accessToken": "old-access", "refreshToken": "old"})

    def post(*args, **kwargs):
        auth.save_tokens({"accessToken": "new-access", "refreshToken": "new"})
        return httpx.Response(401)

    monkeypatch.setattr(auth.httpx, "post", post)
    result = auth.refresh_tokens("old")
    assert result and result["refreshToken"] == "new"
