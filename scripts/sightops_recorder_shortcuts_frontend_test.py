from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "frontend" / "index.html"
DEPLOY_JS = ROOT / "frontend" / "js" / "deploy.js"
BOOTSTRAP_JS = ROOT / "frontend" / "js" / "bootstrap.js"
STYLES = ROOT / "frontend" / "styles.css"


def assert_contains(path: Path, needle: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert needle in text, f"{path.relative_to(ROOT)} missing {needle!r}"


def assert_versioned_asset(path: Path, asset: str) -> None:
    """Confere que o asset esta incluido com cache-bust, sem fixar o numero.

    Um `assert_contains(..., "js/deploy.js?v=167")` literal quebra sozinho
    toda vez que alguem bump o `?v=` de outra mudanca -- nao prova nada sobre
    o que este teste realmente quer garantir (o script estar incluido).
    """
    text = path.read_text(encoding="utf-8")
    pattern = re.escape(asset) + r"\?v=\d+"
    assert re.search(pattern, text), f"{path.relative_to(ROOT)} missing {asset}?v=<N>"


def assert_not_contains(path: Path, needle: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert needle not in text, f"{path.relative_to(ROOT)} still contains {needle!r}"


def test_deploy_recorder_shortcuts_are_wired() -> None:
    assert_contains(INDEX, "deployStandaloneRecorderSavedSelect")
    assert_contains(INDEX, "btnDeployStandaloneRecorderReloadSaved")
    assert_contains(INDEX, "btnDeployStandaloneRecorderOpenEntryModal")
    assert_contains(INDEX, "btnDeployStandaloneRecorderOpenModal")
    assert_contains(INDEX, "Entrar em gravador")
    assert_contains(INDEX, "Cadastrar gravador")
    assert_contains(INDEX, "data-recorder-modal-mode=\"entry\"")
    assert_contains(INDEX, "data-recorder-modal-mode=\"create\"")
    assert_contains(INDEX, "modalDeployStandaloneRecorder")
    assert_contains(INDEX, "recorder-console-only")
    assert_contains(INDEX, "btnDeployStandaloneRecorderLoginModal")
    assert_contains(INDEX, "deployRecorderChannelDrawer")
    assert_contains(INDEX, "deployRecorderChannelDrawerBackdrop")
    assert_versioned_asset(INDEX, "js/deploy.js")
    assert_versioned_asset(INDEX, "js/bootstrap.js")
    assert_versioned_asset(INDEX, "styles.css")
    assert_versioned_asset(INDEX, "js/dashboard.js")
    assert_contains(INDEX, "data-dash-type=\"recorders\"")
    assert_contains(STYLES, ".drawer-mini-badge")
    assert_contains(ROOT / "frontend" / "js" / "dashboard.js", "openDashDrawerRecorder('all', 'all')")
    assert_contains(ROOT / "frontend" / "js" / "dashboard.js", "const sources = source === 'all' ? ['dvr', 'nvr']")
    assert_not_contains(INDEX, "id=\"btnDeployStandaloneRecorderLogin\"")
    assert_not_contains(INDEX, "aside id=\"deployRecorderChannelDetail\"")
    assert_contains(INDEX, "recorder-saved-inline")
    assert_not_contains(INDEX, "recorder-saved-panel")
    assert_contains(STYLES, ".recorder-saved-select")
    assert_contains(STYLES, ".recorder-deploy-modal")
    assert_contains(STYLES, ".recorder-console-only")
    assert_contains(STYLES, ".recorder-channel-drawer")
    assert_contains(STYLES, ".recorder-discovery-loading")
    assert_contains(STYLES, ".recorder-head-status.loading")
    assert_contains(STYLES, ".inline-loading")
    assert_contains(STYLES, ".recorder-channel-detail-actions .danger-action:last-child")
    assert_not_contains(STYLES, ".recorder-channel-layout.has-detail")
    assert_not_contains(STYLES, ".recorder-saved-item")
    assert_contains(DEPLOY_JS, "function deployStandaloneRecorderLoadSaved()")
    assert_contains(DEPLOY_JS, "function deployStandaloneRecorderUseSaved(key)")
    assert_contains(DEPLOY_JS, "item.password = item.password || String(row.recorder_password")
    assert_contains(DEPLOY_JS, "setValue('deployStandaloneRecorderPassword', item.password || '')")
    assert_contains(DEPLOY_JS, "deployStandaloneRecorderLogin();")
    assert_contains(DEPLOY_JS, "recorder_password: payload.recorder_password")
    assert_not_contains(DEPLOY_JS, "setValue('deployStandaloneRecorderPassword', '')")
    assert_contains(DEPLOY_JS, "deployRecorderChannelDrawer")
    assert_contains(DEPLOY_JS, "deployRecorderChannelDrawerBackdrop")
    assert_contains(DEPLOY_JS, "function deployStandaloneRecorderSetModalMode")
    assert_contains(DEPLOY_JS, "function deployStandaloneRecorderRenderLoginProgress")
    assert_contains(DEPLOY_JS, "function deployStandaloneRecorderDeleteChannel(item)")
    assert_contains(DEPLOY_JS, "data-recorder-channel-action=\"delete\"")
    assert_contains(DEPLOY_JS, "/api/deployments/recorder-remove-camera")
    assert_contains(DEPLOY_JS, "Excluir canal")
    assert_contains(DEPLOY_JS, "Aguardando resposta do gravador")
    assert_contains(DEPLOY_JS, "Isso pode levar alguns segundos pela VPN")
    assert_contains(DEPLOY_JS, "Conectando em ${esc(payload.recorder_host)}")
    assert_contains(DEPLOY_JS, "function openDeployStandaloneRecorderModal(mode = 'create')")
    assert_contains(DEPLOY_JS, "function openDeployStandaloneRecorderEntryModal()")
    assert_contains(DEPLOY_JS, "function closeDeployStandaloneRecorderModal()")
    assert_contains(DEPLOY_JS, "function deployStandaloneRecorderClearRecorderFields")
    assert_contains(DEPLOY_JS, "Escolha primeiro o conector")
    assert_contains(DEPLOY_JS, "Escolha uma OLT cadastrada")
    assert_contains(DEPLOY_JS, "Nenhum gravador cadastrado em")
    assert_contains(DEPLOY_JS, "sameSite")
    assert_contains(DEPLOY_JS, "<optgroup")
    assert_contains(DEPLOY_JS, "/api/nvr/inventory?site=")
    assert_contains(DEPLOY_JS, "/api/dvr/inventory?site=")
    assert_not_contains(DEPLOY_JS, "/api/nvr/rows")
    assert_not_contains(DEPLOY_JS, "/api/dvr/rows")
    assert_contains(BOOTSTRAP_JS, "btnDeployStandaloneRecorderReloadSaved")
    assert_contains(BOOTSTRAP_JS, "btnDeployStandaloneRecorderOpenEntryModal")
    assert_contains(BOOTSTRAP_JS, "btnDeployStandaloneRecorderOpenModal")
    assert_contains(BOOTSTRAP_JS, "openDeployStandaloneRecorderEntryModal")
    assert_contains(BOOTSTRAP_JS, "openDeployStandaloneRecorderModal('create')")
    assert_contains(BOOTSTRAP_JS, "btnDeployStandaloneRecorderLoginModal")
    assert_contains(BOOTSTRAP_JS, "deployRecorderChannelDrawerBackdrop")
    assert_contains(BOOTSTRAP_JS, "deployStandaloneRecorderSavedSelect")
    assert_contains(BOOTSTRAP_JS, "deployStandaloneRecorderClearRecorderFields({ keepConnector: true })")
    assert_contains(BOOTSTRAP_JS, "channelAction === 'delete'")
    assert_contains(BOOTSTRAP_JS, "deployStandaloneRecorderDeleteChannel(item)")


if __name__ == "__main__":
    test_deploy_recorder_shortcuts_are_wired()
    print("OK: recorder deployment shortcuts are wired")
