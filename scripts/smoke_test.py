"""Smoke-test a running local, container or public deployment without third-party packages."""

import argparse
import json
import time
import urllib.error
import urllib.request


def request(base, path, payload=None):
    body = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(
        base.rstrip("/") + path, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=35) as response:
        assert response.status == 200
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--attempts", type=int, default=1)
    args = parser.parse_args()
    for attempt in range(args.attempts):
        try:
            health = request(args.base_url, "/health")
            break
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if attempt + 1 == args.attempts:
                raise
            time.sleep(2)
    assert health["status"] == "ok", health
    overview = request(args.base_url, "/api/overview")
    assert len(overview["series"]) >= 4
    series_id = overview["series"][0]["id"]
    assert request(args.base_url, f"/api/data/{series_id}")["observations"]
    forecast = request(args.base_url, "/api/forecast")
    assert forecast["lower"] <= forecast["value"] <= forecast["upper"]
    answer = request(args.base_url, "/api/ask", {"question": "What is the UK inflation target?"})
    assert not answer["abstained"], answer
    assert answer["sources"] and answer["answer"]
    negative = request(
        args.base_url, "/api/ask", {"question": "Give me a recipe for chocolate cake."}
    )
    assert negative["abstained"], negative
    print(
        json.dumps(
            {
                "status": "passed",
                "base_url": args.base_url,
                "version": health["version"],
                "model_version": forecast["model_version"],
                "answer_mode": answer["mode"],
                "checks": 7,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
