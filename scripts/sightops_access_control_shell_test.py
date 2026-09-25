from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "frontend" / "index.html"
CORE_JS = ROOT / "frontend" / "js" / "core.js"
BOOTSTRAP_JS = ROOT / "frontend" / "js" / "bootstrap.js"
ACCESS_JS = ROOT / "frontend" / "js" / "accessControl.js"
AUTH_STORE = ROOT / "app" / "services" / "auth_store.py"
MAIN_PY = ROOT / "app" / "main.py"
ENDPOINTS_INIT = ROOT / "app" / "api" / "endpoints" / "__init__.py"
STYLES = ROOT / "frontend" / "styles.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _access_control_section() -> str:
    html = _read(INDEX_HTML)
    section = html.split('id="viewAccessControl"', 1)[1]
    return section.split("<!-- --- VIEW: OLT --- -->", 1)[0]


def test_access_control_menu_has_own_sidebar_section() -> None:
    html = _read(INDEX_HTML)
    analysis_marker = '<!-- Analise -->'
    access_marker = '<!-- Controle de Acesso -->'
    assert analysis_marker in html
    assert access_marker in html
    analysis = html.split(analysis_marker, 1)[1].split(access_marker, 1)[0]
    access = html.split(access_marker, 1)[1].split('<div id="navOwnerMode"', 1)[0]
    assert 'data-view="ia-nvr"' in analysis
    assert 'data-view="access-control"' not in analysis
    assert '<div class="nav-section-label">Controle de Acesso</div>' in access
    assert "<span>Controle de Acesso</span>" in access


def test_access_control_view_exists_and_is_routable() -> None:
    html = _read(INDEX_HTML)
    core = _read(CORE_JS)
    assert 'id="viewAccessControl"' in html
    assert "'access-control': { title: 'Controle de Acesso'" in core
    assert "'access-control':  'viewAccessControl'" in core
    assert "case 'access-control': loadAccessControl();" in core


def test_access_control_layout_uses_sightops_components() -> None:
    section = _access_control_section()
    styles = _read(STYLES)

    assert 'class="metrics access-control-kpis"' in section
    kpis = section.split('class="metrics access-control-kpis"', 1)[1].split('class="tabs access-control-tabs"', 1)[0]
    assert kpis.count('dash-kpi-card') == 4
    assert kpis.count('class="metric-icon') == 4
    assert 'id="accessKpiStudentsCard"' in kpis
    assert 'id="accessKpiDevicesCard"' in kpis
    assert 'id="accessKpiEventsCard"' in kpis
    assert 'role="button"' in kpis
    assert 'id="btnAccessPrimaryAction"' in section
    assert 'id="accessPrimaryActionLabel"' in section
    assert 'data-access-primary-action="people"' in section
    assert 'id="accessPeopleTable"' in section
    assert 'class="access-people-heading"' in section
    assert 'class="filters access-people-filters"' in section
    assert 'id="btnAccessPeopleClearFilters"' in section
    assert 'id="btnAccessPeopleRefresh"' not in section
    assert 'class="panel access-people-panel"' in section
    people_panel_before_table = section.split('class="access-tab-panel" data-access-panel="people"', 1)[1].split('id="accessPeopleTable"', 1)[0]
    assert 'class="panel-header"' not in people_panel_before_table
    assert 'class="search-box"' in people_panel_before_table
    assert '<p id="accessPeopleCount"' not in section
    assert 'class="table-footer access-people-footer"' in section
    assert '<span id="accessPeopleCount">0 pessoas</span>' in section
    assert 'id="btnAccessPeopleFooterRefresh"' in section
    assert 'id="btnAccessPersonFooterNew"' in section
    assert 'id="btnAccessPeopleFooterEdit"' in section
    assert 'id="btnAccessPeopleFooterDeleteSelected"' in section
    assert 'id="btnAccessPeopleFooterDeleteAll"' in section
    assert 'id="modalAccessPerson"' in section
    access_person_open = section.split('id="modalAccessPerson"', 1)[1].split('>', 1)[0]
    assert "onclick=" not in access_person_open
    assert 'class="dashboard-grid"' not in section
    assert 'class="kpi-card"' not in section
    assert 'class="quick-actions-grid"' not in section
    assert ".access-control-kpis" in styles
    assert ".access-people-heading" in styles
    assert ".access-people-filters" in styles
    assert ".filters.access-people-filters" in styles
    assert "padding: 14px 0 12px;" in styles
    assert "flex: 1 1 760px;" in styles
    assert "min-width: 520px;" in styles
    assert ".access-people-filters .ghost-action" in styles
    assert ".access-people-panel" in styles
    assert ".access-control-toolbar" in styles
    assert ".access-person-modal" in styles


def test_access_control_planned_flow_panel_is_removed() -> None:
    section = _access_control_section()

    assert "Fluxo planejado" not in section
    assert "Cadastro central do SightOps com drivers por fabricante." not in section
    assert '<span class="pill neutral">planejado</span>' not in section


def test_access_control_frontend_is_bound() -> None:
    html = _read(INDEX_HTML)
    bootstrap = _read(BOOTSTRAP_JS)
    access_js = _read(ACCESS_JS)
    styles = _read(STYLES)

    assert 'js/accessControl.js' in html
    assert "bindAccessControl();" in bootstrap
    assert "function bindAccessControl()" in access_js
    assert "/api/access-control/people" in access_js
    assert "btnAccessPrimaryAction" in access_js
    assert "function updateAccessPrimaryAction" in access_js
    assert "function handleAccessPrimaryAction" in access_js
    assert "Novo dispositivo" in access_js
    assert "accessKpiStudentsCard" in access_js
    assert "accessKpiDevicesCard" in access_js
    assert "function openAccessStudentsDrawer" in access_js
    assert "function focusAccessPersonFromDrawer" in access_js
    assert "function openAccessDevicesDrawer" in access_js
    assert "function showAccessControlTab" in access_js
    assert "function focusAccessDeviceFromDrawer" in access_js
    assert "_drawerFilterBar" in access_js
    assert ".access-device-drawer-item" in styles
    assert ".access-people-table tbody tr.selected" in styles
    assert "person_type=student" in access_js
    assert "data-access-student-id" in access_js
    assert "data-access-person-row" in access_js
    student_click_body = access_js.split("document.querySelectorAll('[data-access-student-id]')", 1)[1].split("\n  });\n}", 1)[0]
    assert "focusAccessPersonFromDrawer(person.id)" in student_click_body
    assert "openAccessPersonModal(person)" not in student_click_body
    assert "data-access-drawer-device-id" in access_js
    drawer_click_body = access_js.split("document.querySelectorAll('[data-access-drawer-device-id]')", 1)[1].split("\n  });\n}", 1)[0]
    assert "focusAccessDeviceFromDrawer(device.id)" in drawer_click_body
    assert "openAccessDeviceModal(device)" not in drawer_click_body
    assert "Local', count: counts.local" in access_js
    assert "Conector', count: counts.connector" in access_js
    assert "btnAccessPeopleClearFilters" in access_js
    assert "function clearAccessPeopleFilters" in access_js
    assert "btnAccessPeopleFooterRefresh" in access_js
    assert "btnAccessPersonFooterNew" in access_js
    assert "btnAccessPeopleFooterEdit" in access_js
    assert "btnAccessPeopleFooterDeleteSelected" in access_js
    assert "btnAccessPeopleFooterDeleteAll" in access_js
    assert "function syncAccessPeopleFooterActions" in access_js
    assert "function deleteSelectedAccessPeople" in access_js
    assert "function deleteAllVisibleAccessPeople" in access_js


def test_access_events_kpi_opens_today_report() -> None:
    html = _read(INDEX_HTML)
    access_js = _read(ACCESS_JS)

    assert 'id="accessKpiEventsCard"' in html
    assert 'title="Ver eventos de hoje"' in html
    assert 'onclick="openAccessTodayEventsReport()"' in html
    assert "handleAccessKpiKeydown('events', event)" in html
    assert "accessKpiEventsCard" in access_js
    assert "function openAccessTodayEventsReport" in access_js
    assert "function handleAccessKpiKeydown" in access_js

    body = access_js.split("function openAccessTodayEventsReport", 1)[1].split("\nfunction ", 1)[0]
    assert "accessReportPeriod" in body
    assert "'today'" in body
    assert "accessReportType" in body
    assert "showAccessControlTab('reports')" in body
    assert "loadAccessControlSummary(true)" in body
    assert "loadAccessReports(true)" in body
    assert "startAccessReportAutoRefresh()" in body


def test_access_whatsapp_kpi_opens_connections() -> None:
    html = _read(INDEX_HTML)
    access_js = _read(ACCESS_JS)

    assert 'id="accessKpiWhatsappCard"' in html
    assert 'title="Configurar WhatsApp"' in html
    assert 'onclick="openAccessWhatsappConnections()"' in html
    assert "handleAccessKpiKeydown('whatsapp', event)" in html
    assert "accessKpiWhatsappCard" in access_js
    assert "function openAccessWhatsappConnections" in access_js
    assert "function handleAccessKpiKeydown" in access_js

    body = access_js.split("function openAccessWhatsappConnections", 1)[1].split("\nfunction ", 1)[0]
    assert "showAccessControlTab('connections')" in body
    assert "loadAccessWhatsappConfig(true)" in body
    assert "stopAccessReportAutoRefresh()" in body


def test_access_whatsapp_kpi_shows_connection_status_not_fake_queue() -> None:
    html = _read(INDEX_HTML)
    access_js = _read(ACCESS_JS)

    assert 'id="accessKpiWhatsappSub"' in html
    assert "fila aguardando homologacao" not in html
    assert "summary.whatsapp_queue" not in access_js
    assert "function renderAccessWhatsappKpiStatus" in access_js
    assert "function loadAccessWhatsappKpiStatus" in access_js
    assert "/api/access-control/whatsapp/connection" in access_js
    assert "loadAccessWhatsappKpiStatus(force)" in access_js


def test_access_control_load_rebinds_kpi_actions() -> None:
    access_js = _read(ACCESS_JS)

    body = access_js.split("async function loadAccessControl(", 1)[1].split("\nasync function loadAccessPeopleSiteOptions", 1)[0]
    assert "bindAccessControl()" in body


def test_access_control_module_can_be_enabled_per_tenant() -> None:
    auth = _read(AUTH_STORE)
    assert '{"key": "access-control", "label": "Controle de Acesso", "section": "Controle de Acesso"}' in auth


def test_access_control_backend_router_is_registered() -> None:
    main = _read(MAIN_PY)
    endpoints = _read(ENDPOINTS_INIT)

    assert "access_control_router" in endpoints
    assert "app.include_router(access_control_router)" in main


def test_access_devices_tab_exists() -> None:
    html = _read(INDEX_HTML)
    access_js = _read(ACCESS_JS)
    assert 'id="accessTabDevices"' in html
    assert 'id="accessDevicesTable"' in html
    assert 'id="accessDevicesSelectAll"' in html
    assert 'id="accessDeviceConnector"' in html
    assert "<th>Conector</th>" in html
    assert '<tr class="empty-row"><td colspan="7">Nenhum dispositivo cadastrado.</td></tr>' in html
    devices_table = html.split('id="accessDevicesTable"', 1)[1].split('</table>', 1)[0]
    assert "<th>Acoes</th>" not in devices_table
    assert 'id="accessDevicesCount"' in html
    assert 'id="accessDevicesFooterHint"' in html
    assert 'id="btnAccessDevicesFooterRefresh"' in html
    assert 'id="btnAccessDevicesFooterTest"' in html
    assert 'id="btnAccessDevicesFooterOpenDoor"' in html
    assert 'id="btnAccessDevicesFooterEdit"' in html
    assert 'id="btnAccessDevicesFooterDelete"' in html
    assert 'id="btnAccessDeviceNew"' not in html
    assert 'id="btnAccessDevicesRefresh"' not in html
    assert "updateAccessPrimaryAction(tab)" in access_js
    assert "openAccessDeviceModal();" in access_js
    assert "function loadAccessDevices" in access_js
    assert "function loadAccessConnectors" in access_js
    assert "/api/connectors" in access_js
    assert "connector_id: document.getElementById('accessDeviceConnector')" in access_js
    assert "function renderAccessDevices" in access_js
    assert "data-access-device-check" in access_js
    assert "function toggleAccessDeviceMasterCheck" in access_js
    assert "data-access-device-row" in access_js
    assert "function syncAccessDevicesFooterActions" in access_js
    assert "function selectedAccessDevice" in access_js
    assert "function openSelectedAccessDeviceDoor" in access_js
    assert "btnAccessDevicesFooterOpenDoor" in access_js


def test_access_devices_can_test_connection_from_table() -> None:
    access_js = _read(ACCESS_JS)
    assert "btnAccessDevicesFooterTest" in access_js
    assert "function testSelectedAccessDevice" in access_js
    assert "/api/access-control/devices/${encodeURIComponent(device.id)}/test" in access_js
    assert "Conexao testada." in access_js


def test_access_device_save_preserves_vendor_and_model() -> None:
    # save_device() no backend faz UPDATE completo (ON CONFLICT DO UPDATE SET
    # vendor=excluded.vendor, model=excluded.model), entao o payload de edicao
    # precisa sempre carregar vendor/model do registro atual -- senao editar um
    # dispositivo apaga o model salvo e reseta o vendor pro default "dahua".
    html = _read(INDEX_HTML)
    access_js = _read(ACCESS_JS)
    assert 'id="accessDeviceVendor"' in html
    assert 'id="accessDeviceModel"' in html
    assert "item.vendor" in access_js
    assert "item.model" in access_js
    assert "vendor: document.getElementById('accessDeviceVendor')" in access_js
    assert "model: document.getElementById('accessDeviceModel')" in access_js


def test_access_device_default_vendor_is_intelbras() -> None:
    html = _read(INDEX_HTML)
    access_js = _read(ACCESS_JS)
    assert 'id="accessDeviceVendor" type="hidden" value="intelbras"' in html
    assert "item.vendor || 'intelbras'" in access_js


def test_access_person_save_preserves_site() -> None:
    # save_person() no backend faz UPDATE completo (ON CONFLICT DO UPDATE SET
    # site=excluded.site) e AccessPersonRequest.site tem default "" -- sem um
    # campo de site no modal, toda pessoa salva/editada pela UI ficava com
    # site="" (apagando o valor que existisse). Mesmo bug ja corrigido em
    # vendor/model no modal de dispositivo.
    html = _read(INDEX_HTML)
    access_js = _read(ACCESS_JS)
    assert 'id="accessPersonSite"' in html
    assert '<label for="accessPersonSite">Site</label>' in html
    assert "document.getElementById('accessPersonSite').value = item.site" in access_js
    assert "site: document.getElementById('accessPersonSite')" in access_js


def test_access_person_modal_collects_controller_id_and_face_photo() -> None:
    html = _read(INDEX_HTML)
    access_js = _read(ACCESS_JS)

    assert 'id="accessPersonControllerId"' in html
    assert '<label for="accessPersonControllerId">ID na controladora</label>' in html
    assert 'id="accessPersonFacePhoto"' in html
    assert 'class="access-file-control"' in html
    assert 'class="secondary-action access-file-picker"' in html
    assert 'class="access-file-input"' in html
    assert 'accept="image/jpeg,image/png,image/webp"' in html
    assert "document.getElementById('accessPersonControllerId').value = item.controller_user_id" in access_js
    assert "controller_user_id: document.getElementById('accessPersonControllerId')" in access_js
    assert "const faceFile = document.getElementById('accessPersonFacePhoto')?.files?.[0]" in access_js
    assert "new FormData()" in access_js
    assert "/api/access-control/people/${encodeURIComponent(person.id)}/face-photo" in access_js
    assert "function loadAccessPersonSavedFacePreview" in access_js
    assert "await fetch(`${API_BASE}/api/access-control/people/${encodeURIComponent(person.id)}/face-photo`" in access_js
    assert "URL.createObjectURL(blob)" in access_js
    assert "accessPersonFacePhotoStatus" in access_js
    assert "Foto facial salva." not in access_js
    assert "Sem foto facial salva." not in access_js
    assert "face_photo_path" in access_js


def test_access_people_table_shows_sync_status_and_save_syncs_person() -> None:
    html = _read(INDEX_HTML)
    access_js = _read(ACCESS_JS)

    assert '<th class="access-head-sync">Sync</th>' in html
    assert "function accessProvisionStatusBadge" in access_js
    assert "person.provision_summary" in access_js
    assert 'id="accessPersonProvisionStatus"' in html
    assert 'id="btnAccessPersonSync"' not in html
    assert "function renderAccessPersonProvisionStatus" in access_js
    assert "syncAccessPersonAfterSave(person)" in access_js
    assert "function syncAccessPersonAfterSave" in access_js
    assert "btnAccessPersonSync" not in access_js
    assert "/api/access-control/people/${encodeURIComponent(person.id)}/sync" in access_js
    assert "Pessoa salva e sincronizada." in access_js
    assert "data-access-sync-person" not in access_js


def test_access_people_table_has_loading_state() -> None:
    access_js = _read(ACCESS_JS)
    assert "function renderAccessPeopleLoading" in access_js
    assert "Carregando pessoas..." in access_js
    body = access_js.split("async function loadAccessControl(", 1)[1].split("\nasync function loadAccessPeopleSiteOptions", 1)[0]
    assert "renderAccessPeopleLoading()" in body
    assert "Promise.all" in body


def test_access_person_modal_has_access_planning_inside_form() -> None:
    html = _read(INDEX_HTML)
    access_js = _read(ACCESS_JS)
    styles = _read(STYLES)

    assert 'class="access-person-hero"' in html
    assert 'id="accessPersonHeroPhoto"' in html
    assert 'class="tabs access-control-tabs access-person-tabs"' in html
    assert 'data-access-person-tab="details"' in html
    assert 'data-access-person-tab="guardian"' in html
    assert 'data-access-person-tab="access"' in html
    assert 'data-access-person-tab="notes"' in html
    assert 'id="accessPersonGroupsChecklist"' in html
    assert 'id="accessPersonDoorAccessSummary"' in html
    assert 'id="accessPersonDeviceAccessSummary"' in html
    assert "Salvar e sincronizar" in html

    assert "function bindAccessPersonModal" in access_js
    assert "event.stopPropagation()" in access_js
    assert ".access-control-tabs [data-access-tab]" in access_js
    assert "function ensureAccessPersonAccessData" in access_js
    assert "function renderAccessPersonAccessPanel" in access_js
    assert "function saveAccessPersonGroupMembership" in access_js
    assert "await saveAccessPersonGroupMembership(person.id)" in access_js
    assert "syncAccessPersonAfterSave(person)" in access_js
    assert "/api/access-control/groups" in access_js
    assert "/api/access-control/door-groups" in access_js
    assert "/api/access-control/rules" in access_js
    assert "/api/access-control/devices" in access_js
    assert "member_ids" in access_js

    assert ".access-person-tabs" in styles
    assert ".access-person-tab-panel" in styles
    assert ".access-person-hero-photo" in styles
    assert ".access-person-access-grid" in styles
    assert ".access-person-form::-webkit-scrollbar" in styles
    assert "scrollbar-width: none" in styles
    assert "max-height: calc(100vh - 32px)" in styles


def test_access_people_table_has_stable_column_layout() -> None:
    html = _read(INDEX_HTML)
    access_js = _read(ACCESS_JS)
    styles = _read(STYLES)

    assert 'class="data-table responsive-data-table access-people-table" id="accessPeopleTable"' in html
    assert '<col class="access-col-check">' in html
    assert '<col class="access-col-name">' in html
    assert '<col class="access-col-photo">' in html
    assert '<col class="access-col-sync">' in html
    assert 'class="access-head-name"' in html
    assert 'class="access-head-photo"' in html
    assert 'class="access-head-document"' in html
    assert '<col class="access-col-actions">' not in html
    assert '<col style="width:' not in html.split('id="accessPeopleTable"', 1)[1].split('</colgroup>', 1)[0]
    assert '<th class="access-head-photo">Foto</th>' in html
    assert 'colspan="11"' in html
    assert ".access-people-table {" in styles
    assert "min-width: 1120px" in styles
    assert "table-layout: fixed" in styles
    assert '.access-tab-panel[data-access-panel="people"] .access-people-table th {' in styles
    assert "text-align: left" in styles
    assert ".access-people-table .access-col-photo { width: 68px; }" in styles
    assert ".access-people-table .access-col-status { width: 78px; }" in styles
    assert ".access-people-table .access-col-sync { width: 86px; }" in styles
    assert '.access-tab-panel[data-access-panel="people"] .access-people-table .access-head-photo' in styles
    assert '.access-tab-panel[data-access-panel="people"] .access-people-table .access-cell-photo .pill' in styles
    assert ".access-people-table .access-head-name" in styles
    assert ".access-people-table .access-cell-check" in styles
    assert "margin: 0 auto" in styles
    assert "padding-left: 6px" in styles
    assert '.access-tab-panel[data-access-panel="people"] .access-people-table td {' in styles
    assert "height: 48px" in styles
    assert "vertical-align: middle" in styles
    assert ".access-cell-truncate" in styles
    assert ".access-cell-nowrap" in styles
    assert ".access-cell-actions" not in styles
    for klass in (
        "access-cell-name",
        "access-cell-photo",
        "access-cell-document",
        "access-cell-phone",
        "access-cell-status",
        "access-cell-sync",
    ):
        assert klass in access_js


def test_group_modal_loads_unfiltered_people_list() -> None:
    # O checklist de membros do modal de grupo era montado a partir de
    # _accessPeopleRows, que guarda o resultado JA FILTRADO pela busca/status da
    # aba Pessoas. Como saveAccessGroupFromForm envia os marcados como a lista
    # COMPLETA de member_ids e set_group_members faz DELETE + reinsert, editar um
    # grupo com filtro ativo apagava do grupo todo mundo que nao aparecia na tela.
    # O modal precisa buscar /api/access-control/people sem nenhum parametro.
    access_js = _read(ACCESS_JS)
    assert "async function openAccessGroupModal(" in access_js
    body = access_js.split("async function openAccessGroupModal(", 1)[1].split("\nfunction closeAccessGroupModal", 1)[0]
    # Ignora comentarios: eles citam _accessPeopleRows/filtros justamente para
    # explicar por que o codigo nao os usa.
    body = "\n".join(line for line in body.splitlines() if not line.strip().startswith("//"))
    assert "apiJson('/api/access-control/people'" in body, "modal de grupo deve buscar a lista completa de pessoas"
    assert "access-smart-group-builder" in body
    assert 'id="accessGroupMemberSearch"' in body
    assert 'id="accessGroupAutoSite"' in body
    assert 'id="accessGroupAutoClass"' in body
    assert 'id="btnAccessGroupAddFiltered"' in body
    assert 'id="accessGroupSelectedMembers"' in body
    assert "renderAccessGroupSmartMembers()" in body
    assert "_accessPeopleRows" not in body, "modal de grupo nao pode reusar a lista filtrada da aba Pessoas"
    for filtro in ("accessPeopleSearch", "accessPeopleStatus", "?search=", "URLSearchParams", "active="):
        assert filtro not in body, f"a busca do modal de grupo nao pode carregar filtro ({filtro})"
    # Se a busca falhar, salvar tem que ser bloqueado -- um checklist vazio
    # enviaria member_ids: [] e o backend apagaria os membros reais.
    save_body = access_js.split("async function saveAccessGroupFromForm(", 1)[1].split("\nfunction ", 1)[0]
    assert "_accessGroupPeopleLoadFailed" in save_body


def test_group_modal_detects_load_failure_without_throwing() -> None:
    # apiJson (core.js) NAO lanca em resposta HTTP nao-2xx: um 401/403/500
    # volta como res == null (api() ja devolve null em 401), entao um
    # try/catch sozinho nunca pega esse caso -- people vira [] em silencio e
    # _accessGroupPeopleLoadFailed fica false, deixando o operador salvar um
    # member_ids: [] que apaga a composicao real do grupo. A deteccao de falha
    # precisa checar o formato da resposta explicitamente, nao so o catch.
    access_js = _read(ACCESS_JS)
    assert "async function openAccessGroupModal(" in access_js
    body = access_js.split("async function openAccessGroupModal(", 1)[1].split("\nfunction closeAccessGroupModal", 1)[0]
    assert "!res || !Array.isArray(res.people)" in body, (
        "a deteccao de falha precisa tratar resposta nula/nao-array como erro, nao so exception"
    )


def test_group_modal_disables_save_button_while_people_load() -> None:
    # O modal fica visivel (classList.remove('hidden')) antes do await da
    # busca de pessoas terminar -- sem desabilitar o Salvar nesse intervalo,
    # o operador consegue clicar com o checklist ainda em "Carregando
    # pessoas..." e postar member_ids: [] igual ao bug do load-failure.
    access_js = _read(ACCESS_JS)
    assert "async function openAccessGroupModal(" in access_js
    body = access_js.split("async function openAccessGroupModal(", 1)[1].split("\nfunction closeAccessGroupModal", 1)[0]
    assert "btnAccessGroupSave" in body
    assert "disabled = true" in body
    assert "disabled = false" in body
    # O reset do botao tem que acontecer independente de sucesso/falha da
    # busca (finally), nao so no caminho feliz.
    assert "finally" in body


def test_access_groups_and_rules_tabs_exist() -> None:
    html = _read(INDEX_HTML)
    access_js = _read(ACCESS_JS)
    styles = _read(STYLES)
    assert 'data-access-panel="groups"' in html
    assert 'data-access-panel="rules"' in html
    assert 'id="btnAccessGroupNew"' in html
    assert 'id="btnAccessDoorGroupNew"' in html
    assert 'id="accessGroupsSelectAll"' in html
    assert 'id="accessDoorGroupsSelectAll"' in html
    assert 'id="accessGroupsCount"' in html
    assert 'id="accessDoorGroupsCount"' in html
    assert 'id="btnAccessGroupsFooterEdit"' in html
    assert 'id="btnAccessDoorGroupsFooterEdit"' in html
    assert 'id="btnAccessGroupsFooterDelete"' in html
    assert 'id="btnAccessDoorGroupsFooterDelete"' in html
    groups_table = html.split('id="accessGroupsTable"', 1)[1].split('</table>', 1)[0]
    door_groups_table = html.split('id="accessDoorGroupsTable"', 1)[1].split('</table>', 1)[0]
    assert "<th>Acoes</th>" not in groups_table
    assert "<th>Acoes</th>" not in door_groups_table
    assert 'id="btnAccessRuleNew"' in html
    assert "function loadAccessGroups" in access_js
    assert "function loadAccessRules" in access_js
    assert "data-access-group-row" in access_js
    assert "data-access-door-group-row" in access_js
    assert "function syncAccessGroupFooterActions" in access_js
    assert "function syncAccessDoorGroupFooterActions" in access_js
    assert "function deleteSelectedAccessGroup" in access_js
    assert "function deleteSelectedAccessDoorGroup" in access_js
    assert "/api/access-control/groups/${encodeURIComponent(group.id)}" in access_js
    assert "/api/access-control/door-groups/${encodeURIComponent(group.id)}" in access_js
    assert "#accessGroupsTable tbody tr[data-access-group-row].selected" in styles


def test_access_rules_table_resolves_group_names() -> None:
    # A tabela de regras guarda so people_group_id/door_group_id -- sem resolver
    # pro nome do grupo/grupo de porta a coluna ficaria com UUID cru, inutil pro
    # usuario. loadAccessRules tem que carregar groups/door-groups tambem (nao so
    # rules) pra render funcionar mesmo se o usuario nunca abriu a aba Grupos.
    access_js = _read(ACCESS_JS)
    assert "function renderAccessRules" in access_js
    assert "/api/access-control/groups" in access_js
    assert "/api/access-control/door-groups" in access_js
    assert "/api/access-control/rules" in access_js
    assert "groupName(rule.people_group_id)" in access_js
    assert "doorGroupName(rule.door_group_id)" in access_js


def test_access_rules_can_be_reused_for_another_people_group() -> None:
    html = _read(INDEX_HTML)
    access_js = _read(ACCESS_JS)
    assert 'id="btnAccessRulesFooterReuse"' in html
    assert "function reuseSelectedAccessRule" in access_js
    assert "btnAccessRulesFooterReuse" in access_js
    assert "openAccessRuleModal(rule, { reuse: true })" in access_js
    assert "item.id && !isReuse" in access_js
    assert "accessFirstPeopleGroupWithoutRule" in access_js


def test_access_group_modals_are_fully_implemented() -> None:
    # Task 9 left openAccess*Modal as `// TODO(Task 10): ...` placeholders.
    # Task 10 replaces them with the real implementation, so the marker must
    # be gone and the functions must still exist.
    access_js = _read(ACCESS_JS)
    assert "function openAccessGroupModal" in access_js
    assert "function openAccessDoorGroupModal" in access_js
    assert "function openAccessRuleModal" in access_js
    assert "TODO(Task 10)" not in access_js


def test_load_access_groups_also_fetches_devices_for_door_group_checklist() -> None:
    # Regression: openAccessDoorGroupModal renders its device checklist from
    # _accessDeviceRows, which used to only be populated by visiting the
    # Dispositivos tab (loadAccessDevices(), called from bindAccessTabs()). If the
    # user went straight from Pessoas to Grupos (tabs are independent/unordered)
    # and edited an existing door group, the checklist rendered with nothing
    # checked -- and saving POSTed device_ids: [], which the backend's
    # set_door_group_members() applies as an unconditional DELETE + re-INSERT,
    # permanently wiping the door group's real device membership.
    #
    # loadAccessGroups() must fetch devices too, mirroring how loadAccessRules()
    # already fetches groups/door-groups so it works even if the user never
    # visited the Grupos tab first.
    access_js = _read(ACCESS_JS)
    assert "async function loadAccessGroups(" in access_js
    body = access_js.split("async function loadAccessGroups(", 1)[1].split("\nfunction ", 1)[0]
    assert "/api/access-control/devices" in body
    assert "_accessDeviceRows = " in body


def test_access_group_and_rule_modals_are_functional() -> None:
    html = _read(INDEX_HTML)
    access_js = _read(ACCESS_JS)
    styles = _read(STYLES)
    assert "function saveAccessGroupFromForm" in access_js
    assert "function saveAccessDoorGroupFromForm" in access_js
    assert "function saveAccessRuleFromForm" in access_js
    assert "accessPersonSyncStatus" in access_js
    assert 'id="accessPersonSyncStatus"' in html
    # Checklists pre-check existing members/devices when editing.
    assert "accessGroupMembersChecklist" in access_js
    assert "accessDoorGroupDevicesChecklist" in access_js
    assert "_accessGroupSelectedPeople = new Set(item.member_ids || [])" in access_js
    assert "const memberIds = Array.from(_accessGroupSelectedPeople)" in access_js
    # A selecao de dispositivos vive num Set, nao no DOM: com filtro por site/
    # modelo/status, ler os checkboxes marcados na hora de salvar mandaria
    # device_ids sem os que estao fora do filtro -- e set_door_group_members()
    # apaga e reinsere, entao a diferenca vira perda de vinculo real.
    assert "_accessDoorGroupSelectedIds = new Set(item.device_ids || [])" in access_js
    assert "_accessDoorGroupSelectedIds.has(d.id)" in access_js
    assert "const deviceIds = Array.from(_accessDoorGroupSelectedIds)" in access_js
    assert 'id="accessDoorGroupDevice-${esc(d.id)}"' in access_js
    assert "<strong>${esc(d.name" in access_js
    assert "overflow-x: hidden" in styles
    assert ".access-group-smart-modal" in styles
    assert ".access-smart-filters" in styles
    assert ".access-smart-columns" in styles
    assert ".access-smart-member" in styles
    # Rule modal selects are populated from already-loaded rows, not a fresh fetch.
    assert "_accessGroupRows.map(g =>" in access_js
    assert "_accessDoorGroupRows.map(g =>" in access_js
    # Modal markup exists in index.html following the modal-backdrop convention.
    assert 'id="modalAccessGroup" class="modal-backdrop hidden"' in html
    assert 'id="modalAccessDoorGroup" class="modal-backdrop hidden"' in html
    assert 'id="modalAccessRule" class="modal-backdrop hidden"' in html


if __name__ == "__main__":
    test_access_control_menu_has_own_sidebar_section()
    test_access_control_view_exists_and_is_routable()
    test_access_control_layout_uses_sightops_components()
    test_access_control_planned_flow_panel_is_removed()
    test_access_control_frontend_is_bound()
    test_access_events_kpi_opens_today_report()
    test_access_whatsapp_kpi_opens_connections()
    test_access_control_load_rebinds_kpi_actions()
    test_access_control_module_can_be_enabled_per_tenant()
    test_access_control_backend_router_is_registered()
    test_access_devices_tab_exists()
    test_access_devices_can_test_connection_from_table()
    test_access_device_save_preserves_vendor_and_model()
    test_access_device_default_vendor_is_intelbras()
    test_access_person_save_preserves_site()
    test_access_person_modal_collects_controller_id_and_face_photo()
    test_access_people_table_shows_sync_status_and_save_syncs_person()
    test_access_person_modal_has_access_planning_inside_form()
    test_access_people_table_has_stable_column_layout()
    test_group_modal_loads_unfiltered_people_list()
    test_group_modal_detects_load_failure_without_throwing()
    test_group_modal_disables_save_button_while_people_load()
    test_access_groups_and_rules_tabs_exist()
    test_access_rules_table_resolves_group_names()
    test_access_rules_can_be_reused_for_another_people_group()
    test_access_group_modals_are_fully_implemented()
    test_load_access_groups_also_fetches_devices_for_door_group_checklist()
    test_access_group_and_rule_modals_are_functional()
    print("OK access control shell")
