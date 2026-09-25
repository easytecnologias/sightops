# Package: API endpoints (routers)

from .scan import router as scan_router
from .cameras import router as cameras_router
from .olt import router as olt_router
from .tools import router as tools_router
from .maintenance import router as maintenance_router
from .switch import router as switch_router

from .ws import router as ws_router
from .dvr import router as dvr_router
from .nvr import router as nvr_router
from .ia import router as ia_router
from .database import router as database_router
from .auth import router as auth_router
from .system import router as system_router
from .dashboard import router as dashboard_router
from .windows import router as windows_router
from .playback import router as playback_router
from .connectors import router as connectors_router
from .network_tools import router as network_tools_router
from .deployments import router as deployments_router
from .camera_activation import router as camera_activation_router
from .monitoring import router as monitoring_router
from .planning import router as planning_router
from .access_control import router as access_control_router
from .alert import router as alert_router
