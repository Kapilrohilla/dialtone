def assert_isolated(client, url):
    """`url` points at an object owned by another workspace: a member must get 404, not 403/200."""
    response = client.get(url)
    assert response.status_code == 404, f"expected 404 for cross-workspace object, got {response.status_code}"
