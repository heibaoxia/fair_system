import html
from pathlib import Path

from fastapi.testclient import TestClient

from app import models
from tests.frontend_session_helpers import (
    assert_login_redirect,
    build_frontend_session_test_app,
    register_member_session,
)


PAGE_TITLE = "\u793e\u4ea4\u4e2d\u5fc3"
SECTION_HEADINGS = [
    "\u641c\u7d22\u8d26\u6237ID",
    "\u6211\u5173\u6ce8\u8c01",
    "\u8c01\u5173\u6ce8\u6211",
    "\u597d\u53cb",
    "\u6211\u7684\u9879\u76ee\u9080\u8bf7",
]

SECTION_MARKUP = [
    '<h2 class="social-card-title">\u641c\u7d22\u8d26\u6237ID</h2>',
    '<h2 class="social-card-title">\u6211\u5173\u6ce8\u8c01</h2>',
    '<h2 class="social-card-title">\u8c01\u5173\u6ce8\u6211</h2>',
    '<h2 class="social-card-title">\u597d\u53cb</h2>',
    '<h2 class="social-card-title">\u6211\u7684\u9879\u76ee\u9080\u8bf7</h2>',
]


def seed_social_member(testing_session_local, *, name: str) -> int:
    db = testing_session_local()
    try:
        member = models.Member(name=name, is_active=True)
        db.add(member)
        db.commit()
        db.refresh(member)
        return member.id
    finally:
        db.close()


def test_social_requires_login_and_preserves_next_url():
    harness = build_frontend_session_test_app()
    client = TestClient(harness.app)

    try:
        response = client.get('/social?tab=friends', follow_redirects=False)

        assert_login_redirect(response, '/social?tab=friends')
    finally:
        client.close()
        harness.close()


def test_social_page_renders_all_sections_for_logged_in_member():
    harness = build_frontend_session_test_app()
    member_id = seed_social_member(harness.testing_session_local, name='Social Viewer')
    client = TestClient(harness.app)

    try:
        register_member_session(
            client,
            member_id=member_id,
            login_id='social-viewer@example.com',
        )

        response = client.get('/social')
        body = html.unescape(response.text)

        assert response.status_code == 200
        assert f'<h1 class="page-title">{PAGE_TITLE}</h1>' in body
        for heading in SECTION_HEADINGS:
            assert heading in body
        assert SECTION_MARKUP[-1] in body
    finally:
        client.close()
        harness.close()


def test_social_page_exposes_search_controls_and_follow_hooks():
    harness = build_frontend_session_test_app()
    member_id = seed_social_member(harness.testing_session_local, name='Social Hooks')
    client = TestClient(harness.app)

    try:
        register_member_session(
            client,
            member_id=member_id,
            login_id='social-hooks@example.com',
        )

        response = client.get('/social')
        body = html.unescape(response.text)

        assert response.status_code == 200
        assert 'id="social-search-account-id"' in body
        assert 'id="social-search-submit"' in body
        assert 'data-social-action="${action}"' in body
        assert "const actionLabel = profile.is_following ? '\\u53d6\\u6d88\\u5173\\u6ce8' : '\\u5173\\u6ce8';" in body
    finally:
        client.close()
        harness.close()


def test_social_page_script_wires_validation_endpoints_refresh_and_errors():
    harness = build_frontend_session_test_app()
    member_id = seed_social_member(harness.testing_session_local, name='Social Script')
    client = TestClient(harness.app)

    try:
        register_member_session(
            client,
            member_id=member_id,
            login_id='social-script@example.com',
        )

        response = client.get('/social')
        body = html.unescape(response.text)

        assert response.status_code == 200
        assert 'type="text"' in body
        assert 'inputmode="numeric"' in body
        assert 'pattern="[0-9]+"' in body
        assert 'function parseExactAccountId(rawValue)' in body
        assert '/^[0-9]+$/.test(normalized)' in body
        assert '!Number.isSafeInteger(accountId) || accountId <= 0' in body
        assert '请输入正确的正整数账户ID。' in body
        assert "'/social/relationships'" in body
        assert '`/social/search?account_id=${encodeURIComponent(accountId)}`' in body
        assert '`/social/follow/${accountId}`' in body
        assert 'function renderSearchFailure(message, searchedAccountId)' in body
        assert '搜索账户失败，请稍后再试。' in body
        assert "renderSearchFailure(error.message || '搜索账户失败，请稍后再试。', accountId);" in body
        assert 'await loadRelationships();' in body
        assert 'await runSearch(socialState.lastSearchedAccountId);' in body
        assert "const successMessage = action === 'unfollow' ? '\\u5df2\\u53d6\\u6d88\\u5173\\u6ce8' : '\\u5173\\u6ce8\\u6210\\u529f';" in body
        assert "showToast(error.message || '搜索账户失败。', true);" in body
        assert "showToast(error.message || '更新关注状态失败。', true);" in body
    finally:
        client.close()
        harness.close()


def test_base_template_contains_social_nav_link():
    base_template = Path('app/templates/base.html').read_text(encoding='utf-8')

    assert 'href="/social"' in base_template
    assert 'data-path="/social"' in base_template


def test_members_page_is_not_repurposed_as_social_page():
    harness = build_frontend_session_test_app()
    client = TestClient(harness.app)

    try:
        response = client.get('/members')
        body = html.unescape(response.text)

        assert response.status_code == 200
        for section_markup in SECTION_MARKUP:
            assert section_markup not in body
        assert 'id="social-search-account-id"' not in body
    finally:
        client.close()
        harness.close()
