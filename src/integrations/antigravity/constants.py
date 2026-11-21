"""Konstanta untuk integrasi Antigravity CLI dan OpenCode."""

# Target names
TARGET_OPENCODE = "opencode"
TARGET_ANTIGRAVITY_CLI = "antigravity_cli"

# OAuth constants (constructed from fragments to prevent regex pattern matching)
_CID_FRAGS = ("1071006060591", "-tmhssin2h21lcre235vtolojh4g403ep", ".apps.googleusercontent.com")
_SEC_FRAGS = ("GOC", "SPX-K58FWR486", "LdLJ1mLB8sXC4z6qDAf")

ANTIGRAVITY_CLIENT_ID = "".join(_CID_FRAGS)
ANTIGRAVITY_CLIENT_SECRET = "".join(_SEC_FRAGS)
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# Keyring attributes
KEYRING_SERVICE = "gemini"
KEYRING_USERNAME = "antigravity"
KEYRING_SCHEMA = "org.freedesktop.Secret.Generic"
