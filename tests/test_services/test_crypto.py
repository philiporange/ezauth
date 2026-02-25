from ezauth.crypto import constant_time_compare, generate_code, generate_token, hash_token


def test_generate_token_length():
    token = generate_token(32)
    assert len(token) > 0
    # URL-safe base64 encoding of 32 bytes ~ 43 chars
    assert len(token) >= 40


def test_generate_token_uniqueness():
    tokens = {generate_token() for _ in range(100)}
    assert len(tokens) == 100


def test_generate_code_length():
    code = generate_code(6)
    assert len(code) == 6
    assert code.isdigit()


def test_generate_code_custom_length():
    code = generate_code(8)
    assert len(code) == 8


def test_hash_token():
    token = "test-token"
    h = hash_token(token)
    assert len(h) == 64  # SHA-256 hex
    assert h == hash_token(token)  # deterministic


def test_hash_token_different_input():
    assert hash_token("a") != hash_token("b")


def test_constant_time_compare():
    assert constant_time_compare("abc", "abc") is True
    assert constant_time_compare("abc", "def") is False
    assert constant_time_compare("", "") is True
