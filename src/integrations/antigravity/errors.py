"""Custom exceptions untuk integrasi Antigravity."""


class IntegrationError(Exception):
  """Base error untuk integrasi Antigravity."""


class ApplyError(IntegrationError):
  """Error saat eksekusi build plan atau apply."""

  def __init__(self, code: str, message: str, suggestion: str = "", backup_location: str = ""):
    super().__init__(message)
    self.code = code
    self.message = message
    self.suggestion = suggestion
    self.backup_location = backup_location


class KeyringError(IntegrationError):
  """Error terkait akses keyring."""


class KeyringUnavailableError(KeyringError):
  """Keyring / Secret Service tidak tersedia."""


class KeyringLockedError(KeyringError):
  """Keyring terkunci."""


class KeyringItemNotFoundError(KeyringError):
  """Item service=gemini/username=antigravity tidak ada di keyring."""


class KeyringParseError(KeyringError):
  """JSON keyring tidak bisa diparsing atau tidak memiliki field yang diharapkan."""


class OAuthError(IntegrationError):
  """Error respons dari endpoint OAuth."""

  def __init__(self, code: str, description: str = ""):
    super().__init__(f"{code}: {description}" if description else code)
    self.code = code
    self.description = description
