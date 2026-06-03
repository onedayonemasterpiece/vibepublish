def test_google_ai_imports():
    from google_ai import GoogleAIClient, RateLimitError, SecretsProvider

    assert GoogleAIClient is not None
    assert RateLimitError is not None
    assert SecretsProvider is not None

