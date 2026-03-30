"""
tests/test_new_endpoints.py — Targeted tests for newly added endpoint coverage.

Covers:
  REST:
    - Collaboration endpoints use user token (document/folder user + team collaborators)
    - Teams endpoints use account token
    - Audit log endpoints use account token
    - searchFolders uses user token
    - transferUserContent uses account token
    - Share link endpoints use the correct token slot

  SCIM:
    - scimDeleteUser: returns auth error when SCIM token not set
    - scimGetAllGroups: builds correct URL
    - scimServiceProviderConfig / scimResourceTypes / scimSchemas: metadata URLs

All tests exercise URL construction and token-selection logic only — they do
not make real HTTP calls to Lucid. Endpoints requiring auth return the
structured _error_result when state is empty (no real token loaded).
"""

import pytest
import app.state as state
from app.services.lucid_rest import ENDPOINT_REGISTRY as REST_REGISTRY
from app.services.lucid_scim import ENDPOINT_REGISTRY as SCIM_REGISTRY, execute_scim_call


# ── REST — helpers ─────────────────────────────────────────────────────────────

def _resolve_url(endpoint_key: str, params: dict) -> str:
    """Resolve the URL for a REST endpoint without making an HTTP call."""
    ep = REST_REGISTRY[endpoint_key]
    return ep["url"](params)


def _token_type(endpoint_key: str) -> str:
    return REST_REGISTRY[endpoint_key].get("token", "user")


# ── Priority 1: Collaboration — Document ──────────────────────────────────────

class TestDocumentCollaboratorEndpoints:
    """Document collaborator endpoints exist in the registry with correct config."""

    def test_list_document_user_collaborators_url(self):
        url = _resolve_url("listDocumentUserCollaborators", {"documentId": "doc-abc"})
        assert "/documents/doc-abc/collaborators/users" in url

    def test_list_document_user_collaborators_uses_user_token(self):
        assert _token_type("listDocumentUserCollaborators") == "user"

    def test_get_document_user_collaborator_url(self):
        url = _resolve_url("getDocumentUserCollaborator", {"documentId": "doc-abc", "userId": "42"})
        assert "/documents/doc-abc/collaborators/users/42" in url

    def test_put_document_user_collaborator_has_body(self):
        assert REST_REGISTRY["putDocumentUserCollaborator"]["has_body"] is True

    def test_delete_document_user_collaborator_method(self):
        assert REST_REGISTRY["deleteDocumentUserCollaborator"]["method"] == "DELETE"

    def test_get_document_team_collaborator_url(self):
        url = _resolve_url("getDocumentTeamCollaborator", {"documentId": "doc-abc", "teamId": "team-1"})
        assert "/documents/doc-abc/collaborators/teams/team-1" in url

    def test_put_document_team_collaborator_has_body(self):
        assert REST_REGISTRY["putDocumentTeamCollaborator"]["has_body"] is True

    def test_delete_document_team_collaborator_method(self):
        assert REST_REGISTRY["deleteDocumentTeamCollaborator"]["method"] == "DELETE"


# ── Priority 1: Collaboration — Folder ────────────────────────────────────────

class TestFolderCollaboratorEndpoints:
    """Folder collaborator endpoints exist with correct config."""

    def test_list_folder_user_collaborators_url(self):
        url = _resolve_url("listFolderUserCollaborators", {"folderId": "999"})
        assert "/folders/999/collaborators/users" in url

    def test_list_folder_user_collaborators_uses_user_token(self):
        assert _token_type("listFolderUserCollaborators") == "user"

    def test_put_folder_user_collaborator_url(self):
        url = _resolve_url("putFolderUserCollaborator", {"folderId": "999", "userId": "42"})
        assert "/folders/999/collaborators/users/42" in url

    def test_delete_folder_user_collaborator_method(self):
        assert REST_REGISTRY["deleteFolderUserCollaborator"]["method"] == "DELETE"

    def test_list_folder_group_collaborators_url(self):
        url = _resolve_url("listFolderGroupCollaborators", {"folderId": "888"})
        assert "/folders/888/collaborators/groups" in url

    def test_put_folder_group_collaborator_url(self):
        url = _resolve_url("putFolderGroupCollaborator", {"folderId": "888", "groupId": "grp-7"})
        assert "/folders/888/collaborators/groups/grp-7" in url

    def test_delete_folder_group_collaborator_method(self):
        assert REST_REGISTRY["deleteFolderGroupCollaborator"]["method"] == "DELETE"


# ── Priority 1: Share links ────────────────────────────────────────────────────

class TestShareLinkEndpoints:
    """Share link endpoints exist with correct methods and token types."""

    def test_get_document_share_link_url(self):
        url = _resolve_url("getDocumentShareLink", {"documentId": "doc-xyz"})
        assert "/documents/doc-xyz/sharelink" in url

    def test_get_document_share_link_uses_user_token(self):
        assert _token_type("getDocumentShareLink") == "user"

    def test_create_document_share_link_method_and_body(self):
        ep = REST_REGISTRY["createDocumentShareLink"]
        assert ep["method"] == "POST"
        assert ep["has_body"] is True

    def test_update_document_share_link_method(self):
        assert REST_REGISTRY["updateDocumentShareLink"]["method"] == "PATCH"

    def test_delete_document_share_link_method(self):
        assert REST_REGISTRY["deleteDocumentShareLink"]["method"] == "DELETE"

    def test_get_folder_share_link_url(self):
        url = _resolve_url("getFolderShareLink", {"folderId": "555"})
        assert "/folders/555/sharelink" in url

    def test_create_folder_share_link_has_body(self):
        assert REST_REGISTRY["createFolderShareLink"]["has_body"] is True

    def test_accept_share_link_url(self):
        url = _resolve_url("acceptShareLink", {})
        assert "/sharelinks/accept" in url

    def test_accept_share_link_uses_user_token(self):
        assert _token_type("acceptShareLink") == "user"


# ── Priority 2: Teams ──────────────────────────────────────────────────────────

class TestTeamEndpoints:
    """Team endpoints use account token and have correct URL patterns."""

    def test_list_teams_url(self):
        url = _resolve_url("listTeams", {})
        assert url.endswith("/teams")

    def test_list_teams_uses_account_token(self):
        assert _token_type("listTeams") == "account"

    def test_create_team_has_body(self):
        assert REST_REGISTRY["createTeam"]["has_body"] is True

    def test_create_team_uses_account_token(self):
        assert _token_type("createTeam") == "account"

    def test_get_team_url(self):
        url = _resolve_url("getTeam", {"teamId": "team-99"})
        assert "/teams/team-99" in url

    def test_update_team_method(self):
        assert REST_REGISTRY["updateTeam"]["method"] == "PATCH"

    def test_archive_team_url(self):
        url = _resolve_url("archiveTeam", {"teamId": "team-99"})
        assert "/teams/team-99/archive" in url

    def test_restore_team_url(self):
        url = _resolve_url("restoreTeam", {"teamId": "team-99"})
        assert "/teams/team-99/restore" in url

    def test_list_users_on_team_url(self):
        url = _resolve_url("listUsersOnTeam", {"teamId": "team-99"})
        assert "/teams/team-99/users" in url

    def test_add_users_to_team_has_body(self):
        assert REST_REGISTRY["addUsersToTeam"]["has_body"] is True

    def test_remove_users_from_team_url(self):
        url = _resolve_url("removeUsersFromTeam", {"teamId": "team-99"})
        assert "/teams/team-99/users/remove" in url

    def test_remove_users_from_team_uses_account_token(self):
        assert _token_type("removeUsersFromTeam") == "account"


# ── Priority 3: Audit logs ─────────────────────────────────────────────────────

class TestAuditLogEndpoints:
    """Audit log endpoints use account token."""

    def test_get_audit_logs_url(self):
        url = _resolve_url("getAuditLogs", {})
        assert url.endswith("/auditlog")

    def test_get_audit_logs_uses_account_token(self):
        assert _token_type("getAuditLogs") == "account"

    def test_query_audit_logs_method(self):
        assert REST_REGISTRY["queryAuditLogs"]["method"] == "POST"

    def test_query_audit_logs_uses_account_token(self):
        assert _token_type("queryAuditLogs") == "account"

    def test_query_audit_logs_has_body(self):
        assert REST_REGISTRY["queryAuditLogs"]["has_body"] is True


# ── Priority 3: Folder search and content transfer ────────────────────────────

class TestFolderSearchAndTransfer:

    def test_search_folders_url(self):
        url = _resolve_url("searchFolders", {})
        assert url.endswith("/folders/search")

    def test_search_folders_uses_user_token(self):
        assert _token_type("searchFolders") == "user"

    def test_transfer_user_content_url(self):
        url = _resolve_url("transferUserContent", {"userId": "42"})
        assert "/users/42/transfercontent" in url

    def test_transfer_user_content_uses_account_token(self):
        assert _token_type("transferUserContent") == "account"

    def test_transfer_user_content_has_body(self):
        assert REST_REGISTRY["transferUserContent"]["has_body"] is True


# ── SCIM: delete user ──────────────────────────────────────────────────────────

class TestScimDeleteUser:
    """scimDeleteUser is in registry and returns auth error without a token."""

    def test_delete_user_in_registry(self):
        assert "scimDeleteUser" in SCIM_REGISTRY

    def test_delete_user_method(self):
        assert SCIM_REGISTRY["scimDeleteUser"]["method"] == "DELETE"

    def test_delete_user_url(self):
        url = SCIM_REGISTRY["scimDeleteUser"]["url"]({"userId": "scim-user-abc"})
        assert "/Users/scim-user-abc" in url

    @pytest.mark.asyncio
    async def test_delete_user_returns_auth_error_without_token(self):
        """When SCIM token is absent, returns a structured 401 dict, not an exception."""
        # state.scim_bearer_token is None after reset_state autouse fixture
        result = await execute_scim_call("scimDeleteUser", {"userId": "scim-user-abc"})
        assert isinstance(result, dict)
        assert result["status_code"] == 401
        assert "error" in result["body"]


# ── SCIM: groups ───────────────────────────────────────────────────────────────

class TestScimGroupEndpoints:
    """SCIM group endpoints exist in registry with correct config."""

    def test_get_group_in_registry(self):
        assert "scimGetGroup" in SCIM_REGISTRY

    def test_get_all_groups_url(self):
        url = SCIM_REGISTRY["scimGetAllGroups"]["url"]({})
        assert url.endswith("/Groups")

    def test_create_group_has_body(self):
        assert SCIM_REGISTRY["scimCreateGroup"]["has_body"] is True

    def test_modify_group_patch_method(self):
        assert SCIM_REGISTRY["scimModifyGroupPatch"]["method"] == "PATCH"

    def test_delete_group_method(self):
        assert SCIM_REGISTRY["scimDeleteGroup"]["method"] == "DELETE"

    def test_delete_group_url(self):
        url = SCIM_REGISTRY["scimDeleteGroup"]["url"]({"groupId": "grp-99"})
        assert "/Groups/grp-99" in url

    @pytest.mark.asyncio
    async def test_get_all_groups_returns_auth_error_without_token(self):
        result = await execute_scim_call("scimGetAllGroups", {})
        assert result["status_code"] == 401


# ── SCIM: metadata endpoints ───────────────────────────────────────────────────

class TestScimMetadataEndpoints:
    """SCIM metadata endpoints exist and build correct URLs."""

    def test_service_provider_config_in_registry(self):
        assert "scimServiceProviderConfig" in SCIM_REGISTRY

    def test_service_provider_config_url(self):
        url = SCIM_REGISTRY["scimServiceProviderConfig"]["url"]({})
        assert url.endswith("/ServiceProviderConfig")

    def test_resource_types_url(self):
        url = SCIM_REGISTRY["scimResourceTypes"]["url"]({})
        assert url.endswith("/ResourceTypes")

    def test_schemas_url(self):
        url = SCIM_REGISTRY["scimSchemas"]["url"]({})
        assert url.endswith("/Schemas")

    def test_all_metadata_endpoints_are_get(self):
        for key in ("scimServiceProviderConfig", "scimResourceTypes", "scimSchemas"):
            assert SCIM_REGISTRY[key]["method"] == "GET", f"{key} should be GET"

    @pytest.mark.asyncio
    async def test_service_provider_config_returns_auth_error_without_token(self):
        result = await execute_scim_call("scimServiceProviderConfig", {})
        assert result["status_code"] == 401
