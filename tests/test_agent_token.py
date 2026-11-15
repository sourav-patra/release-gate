import base64
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import agent_token  # noqa: E402


@pytest.fixture(scope="module")
def keypair(tmp_path_factory):
    d = tmp_path_factory.mktemp("key")
    key, pub = d / "throwaway.pem", d / "throwaway.pub"
    subprocess.run(["openssl", "genrsa", "-out", str(key), "2048"], check=True,
                   capture_output=True)
    subprocess.run(["openssl", "rsa", "-in", str(key), "-pubout", "-out", str(pub)],
                   check=True, capture_output=True)
    return str(key), str(pub)


def unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def test_jwt_claims_and_signature_verify(keypair, tmp_path):
    key, pub = keypair
    jwt = agent_token.make_jwt(123, key, now=1000)
    head, body, sig = jwt.split(".")
    assert json.loads(unb64(head)) == {"alg": "RS256", "typ": "JWT"}
    assert json.loads(unb64(body)) == {"iat": 940, "exp": 1540, "iss": "123"}
    sigfile, msg = tmp_path / "sig", tmp_path / "msg"
    sigfile.write_bytes(unb64(sig))
    msg.write_bytes((head + "." + body).encode())
    r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", pub,
                        "-signature", str(sigfile), str(msg)], capture_output=True, text=True)
    assert r.returncode == 0 and "Verified OK" in r.stdout


def test_main_prints_only_the_token_and_scopes_to_one_repo(keypair, monkeypatch, capsys):
    key, _ = keypair
    calls = []

    def fake_http(method, path, jwt, body=None):
        calls.append((method, path, body))
        if path.endswith("/installation"):
            return {"id": 77}
        return {"token": "ghs_faketoken"}
    monkeypatch.setattr(agent_token, "http", fake_http)
    assert agent_token.main(["--repo", "o/r", "--app-id", "5", "--key", key]) == 0
    out = capsys.readouterr()
    assert out.out == "ghs_faketoken\n" and out.err == ""
    assert calls[1] == ("POST", "/app/installations/77/access_tokens", {"repositories": ["r"]})


def test_key_text_never_printed_on_failure(tmp_path, capsys):
    bad = tmp_path / "bad.pem"
    bad.write_text("-----BEGIN PRIVATE KEY-----\nSECRETLINE\n-----END PRIVATE KEY-----\n")
    assert agent_token.main(["--repo", "o/r", "--app-id", "5", "--key", str(bad)]) == 2
    out = capsys.readouterr()
    assert "SECRETLINE" not in out.out + out.err and out.out == ""


def test_missing_arguments_exit_2(monkeypatch):
    monkeypatch.delenv("AGENT_APP_ID", raising=False)
    monkeypatch.delenv("AGENT_APP_KEY_PATH", raising=False)
    assert agent_token.main(["--repo", "o/r"]) == 2
