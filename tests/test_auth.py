def test_health(client):
    assert client.get("/health").json() == {"ok": True}


def test_first_run_redirects_to_setup(client):
    r = client.get("/accounts", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/setup"


def test_setup_then_login_and_invite(client):
    r = client.post(
        "/setup",
        data={"display_name": "Nikita", "email": "N@Example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert client.get("/accounts").status_code == 200

    # second setup is refused
    r = client.post(
        "/setup",
        data={"display_name": "x", "email": "x@x.com", "password": "password123"},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/login"

    # invite a second user
    r = client.post(
        "/settings/users",
        data={"display_name": "Sally", "email": "s@example.com"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    page = client.get("/settings").text
    import re

    token = re.search(r"/invite/([A-Za-z0-9_-]+)", page).group(1)

    client.post("/logout", follow_redirects=False)
    assert client.get("/accounts", follow_redirects=False).headers["location"] == "/login"

    r = client.post(
        f"/invite/{token}",
        data={"password": "sallypass1", "password2": "sallypass1"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "Sally" in client.get("/settings").text

    client.post("/logout")
    r = client.post("/login", data={"email": "s@example.com", "password": "wrong"})
    assert "Wrong email" in r.text
    r = client.post(
        "/login", data={"email": "s@example.com", "password": "sallypass1"}, follow_redirects=False
    )
    assert r.status_code == 303


def test_accounts_crud(logged_in):
    c = logged_in
    r = c.post(
        "/accounts/new",
        data={"name": "Apple Card", "kind": "credit", "institution": "Goldman"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "Apple Card" in c.get("/accounts").text
    r = c.post(
        "/accounts/1",
        data={"name": "Apple", "kind": "credit", "is_archived": "on"},
        follow_redirects=False,
    )
    assert "archived" in c.get("/accounts").text
    c.post("/accounts/1/delete", follow_redirects=False)
    assert "Apple" not in c.get("/accounts").text
